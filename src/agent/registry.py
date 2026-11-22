"""
Unified ToolRegistry and three-tier safety taxonomy for F.R.I.D.A.Y.
Handles native macOS/workspace tools and dynamic MCP tools uniformly.
"""
import inspect
import json
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any, Awaitable, Callable

from pydantic import BaseModel, Field

from src.llm.base import ToolDefinition

logger = logging.getLogger("FRIDAY.ToolRegistry")


class ToolRiskTier(str, Enum):
    SAFE = "safe"          # Auto-executed read/inspection tools
    CONFIRM = "confirm"    # Requires HUD / voice approval before running
    DANGEROUS = "dangerous"  # Destructive / elevated operations requiring explicit confirmation


class ToolExecutionResult(BaseModel):
    """Normalized output from any native or MCP tool execution."""

    ok: bool
    output: str
    data: dict[str, Any] = Field(default_factory=dict)
    artifacts: list[str] = Field(default_factory=list)


@dataclass
class RegisteredTool:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: Callable[..., Awaitable[ToolExecutionResult] | ToolExecutionResult]
    risk_tier: ToolRiskTier = ToolRiskTier.SAFE
    source: str = "native"

    def to_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self.name,
            description=self.description,
            parameters=self.parameters,
        )


class ToolRegistry:
    """Central registry for agent tools with uniform schema export and execution."""

    def __init__(self):
        self._tools: dict[str, RegisteredTool] = {}

    def register(self, tool: RegisteredTool) -> None:
        self._tools[tool.name] = tool

    def unregister_by_source(self, source: str) -> None:
        to_remove = [name for name, t in self._tools.items() if t.source == source]
        for name in to_remove:
            del self._tools[name]

    def get(self, name: str) -> RegisteredTool | None:
        return self._tools.get(name)

    def get_tier(self, name: str) -> ToolRiskTier:
        tool = self._tools.get(name)
        return tool.risk_tier if tool else ToolRiskTier.CONFIRM

    def list_definitions(self) -> list[ToolDefinition]:
        return [t.to_definition() for t in self._tools.values()]

    def list_metadata(self) -> list[dict[str, Any]]:
        return [
            {
                "name": t.name,
                "description": t.description,
                "risk_tier": t.risk_tier.value,
                "source": t.source,
            }
            for t in self._tools.values()
        ]

    @staticmethod
    def parse_arguments(arguments: dict[str, Any] | str | None) -> tuple[dict[str, Any], str | None]:
        if arguments is None or arguments == "":
            return {}, None
        if isinstance(arguments, dict):
            return arguments, None
        try:
            parsed = json.loads(arguments)
            if isinstance(parsed, dict):
                return parsed, None
            return {}, "Tool arguments JSON must be an object."
        except json.JSONDecodeError as e:
            return {}, f"Invalid JSON arguments: {e}"

    async def execute(self, name: str, arguments: dict[str, Any] | str | None = None) -> ToolExecutionResult:
        tool = self._tools.get(name)
        if not tool:
            return ToolExecutionResult(ok=False, output=f"Unknown tool: {name}")

        kwargs, err = self.parse_arguments(arguments)
        if err:
            return ToolExecutionResult(ok=False, output=err)

        try:
            res = tool.handler(**kwargs)
            if inspect.isawaitable(res):
                res = await res
            if isinstance(res, ToolExecutionResult):
                return res
            return ToolExecutionResult(ok=True, output=str(res))
        except TypeError as e:
            return ToolExecutionResult(ok=False, output=f"Invalid parameters for {name}: {e}")
        except Exception as e:
            logger.exception(f"Tool execution error in {name}: {e}")
            return ToolExecutionResult(ok=False, output=f"Tool {name} raised an error: {e}")
