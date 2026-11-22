"""
Model Context Protocol (MCP) Client Manager for F.R.I.D.A.Y.
Dynamically connects to configured stdio MCP servers, discovers tools,
maps risk tiers, and registers them into ToolRegistry using task-owned lifecycles.
"""
import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from src.agent.registry import RegisteredTool, ToolExecutionResult, ToolRegistry, ToolRiskTier

logger = logging.getLogger("FRIDAY.MCP")

_READ_PREFIXES = ("get_", "list_", "read_", "search_", "fetch_", "query_", "inspect_", "find_")
_DANGEROUS_HINTS = ("delete", "remove", "drop", "destroy", "exec", "shell", "sudo", "kill", "format")


def infer_mcp_risk_tier(tool_name: str, description: str = "") -> ToolRiskTier:
    lower_name = (tool_name or "").lower()
    lower_desc = (description or "").lower()
    if any(h in lower_name for h in _DANGEROUS_HINTS):
        return ToolRiskTier.DANGEROUS
    if lower_name.startswith(_READ_PREFIXES) and "write" not in lower_desc and "delete" not in lower_desc:
        return ToolRiskTier.SAFE
    return ToolRiskTier.CONFIRM


@dataclass
class MCPServerStatus:
    name: str
    transport: str = "stdio"
    enabled: bool = True
    connected: bool = False
    tool_count: int = 0
    error: str | None = None
    tools: list[str] = field(default_factory=list)


class _MCPServerWorker:
    """Owns a single MCP server connection inside one dedicated asyncio Task for AnyIO safety."""

    def __init__(self, name: str, cfg: dict[str, Any]):
        self.name = name
        self.cfg = cfg
        self.status = MCPServerStatus(
            name=name,
            transport=str(cfg.get("transport", "stdio")),
            enabled=bool(cfg.get("enabled", True)),
        )
        self.discovered_tools: list[Any] = []
        self._ready_event = asyncio.Event()
        self._stop_event = asyncio.Event()
        self._req_queue: asyncio.Queue[tuple[str, dict[str, Any], asyncio.Future[ToolExecutionResult]]] = asyncio.Queue()
        self._task: asyncio.Task | None = None

    async def start(self, timeout: float = 12.0) -> None:
        self._task = asyncio.create_task(self._run(), name=f"mcp_worker_{self.name}")
        try:
            await asyncio.wait_for(self._ready_event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            self.status.error = f"Timed out connecting to MCP server '{self.name}'."
            await self.stop()

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task:
            try:
                await asyncio.wait_for(self._task, timeout=5.0)
            except Exception:
                self._task.cancel()
            self._task = None
        while not self._req_queue.empty():
            _, _, fut = self._req_queue.get_nowait()
            if not fut.done():
                fut.set_result(ToolExecutionResult(ok=False, output=f"MCP server '{self.name}' closed."))

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> ToolExecutionResult:
        if not self.status.connected or not self._task or self._task.done():
            return ToolExecutionResult(ok=False, output=f"MCP server '{self.name}' is not connected.")
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[ToolExecutionResult] = loop.create_future()
        await self._req_queue.put((tool_name, arguments, fut))
        return await fut

    async def _run(self) -> None:
        command = str(self.cfg.get("command", "")).strip()
        args = [str(a) for a in (self.cfg.get("args") or [])]
        raw_env = self.cfg.get("env") or {}
        env = {**os.environ, **{str(k): str(v) for k, v in raw_env.items()}} if raw_env else None

        if not command:
            self.status.error = "Missing 'command' for stdio MCP server."
            self._ready_event.set()
            return

        params = StdioServerParameters(command=command, args=args, env=env)
        try:
            async with stdio_client(params) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    tools_res = await session.list_tools()
                    self.discovered_tools = list(getattr(tools_res, "tools", []) or [])
                    self.status.connected = True
                    self.status.tool_count = len(self.discovered_tools)
                    self.status.tools = [t.name for t in self.discovered_tools]
                    self._ready_event.set()

                    while not self._stop_event.is_set():
                        get_req = asyncio.create_task(self._req_queue.get())
                        wait_stop = asyncio.create_task(self._stop_event.wait())
                        done, pending = await asyncio.wait(
                            {get_req, wait_stop},
                            return_when=asyncio.FIRST_COMPLETED,
                        )
                        for p in pending:
                            p.cancel()
                        if self._stop_event.is_set():
                            break
                        if get_req in done:
                            tname, targs, fut = get_req.result()
                            try:
                                result = await session.call_tool(tname, arguments=targs)
                                blocks = getattr(result, "content", []) or []
                                texts = [
                                    getattr(b, "text", str(b))
                                    for b in blocks
                                ]
                                out_text = "\n".join(texts).strip() or "(MCP tool returned empty output)"
                                if not fut.done():
                                    fut.set_result(
                                        ToolExecutionResult(
                                            ok=not bool(getattr(result, "isError", False)),
                                            output=out_text[:4000],
                                        )
                                    )
                            except Exception as e:
                                if not fut.done():
                                    fut.set_result(ToolExecutionResult(ok=False, output=f"MCP call failed: {e}"))
        except Exception as e:
            self.status.connected = False
            self.status.error = str(e)
            logger.warning(f"MCP server '{self.name}' failed: {e}")
        finally:
            self.status.connected = False
            self._ready_event.set()


class MCPClientManager:
    """Loads config/mcp_servers.json, manages MCP workers, and registers tools into ToolRegistry."""

    def __init__(self, config_path: Path, registry: ToolRegistry):
        self.config_path = config_path
        self.registry = registry
        self._workers: dict[str, _MCPServerWorker] = {}
        self._disabled_statuses: list[MCPServerStatus] = []

    def load_config(self) -> dict[str, dict[str, Any]]:
        if not self.config_path.exists():
            return {}
        try:
            data = json.loads(self.config_path.read_text(encoding="utf-8"))
            servers = data.get("servers", {})
            return servers if isinstance(servers, dict) else {}
        except Exception as e:
            logger.warning(f"Failed reading MCP config {self.config_path}: {e}")
            return {}

    async def reload(self) -> list[dict[str, Any]]:
        await self.close_all()
        self._disabled_statuses.clear()
        servers = self.load_config()

        for name, cfg in servers.items():
            if not isinstance(cfg, dict):
                continue
            enabled = bool(cfg.get("enabled", True))
            transport = str(cfg.get("transport", "stdio")).lower()
            if not enabled:
                self._disabled_statuses.append(
                    MCPServerStatus(name=name, transport=transport, enabled=False, connected=False)
                )
                continue
            if transport != "stdio":
                st = MCPServerStatus(
                    name=name,
                    transport=transport,
                    enabled=True,
                    connected=False,
                    error=f"Unsupported MCP transport '{transport}' (only stdio supported locally).",
                )
                self._disabled_statuses.append(st)
                continue

            worker = _MCPServerWorker(name, cfg)
            await worker.start()
            self._workers[name] = worker
            if worker.status.connected:
                self._register_worker_tools(worker)

        return self.list_servers_status()

    def _register_worker_tools(self, worker: _MCPServerWorker) -> None:
        source_tag = f"mcp:{worker.name}"
        self.registry.unregister_by_source(source_tag)
        for tool_meta in worker.discovered_tools:
            orig_name = tool_meta.name
            desc = getattr(tool_meta, "description", None) or f"MCP tool {orig_name} from {worker.name}"
            schema = getattr(tool_meta, "inputSchema", None) or {"type": "object", "properties": {}}
            reg_name = f"mcp__{worker.name}__{orig_name}"

            async def _invoke(_w=worker, _t=orig_name, **kwargs) -> ToolExecutionResult:
                return await _w.call_tool(_t, kwargs)

            self.registry.register(
                RegisteredTool(
                    name=reg_name,
                    description=f"[MCP:{worker.name}] {desc}",
                    parameters=schema,
                    handler=_invoke,
                    risk_tier=infer_mcp_risk_tier(orig_name, desc),
                    source=source_tag,
                )
            )

    def list_servers_status(self) -> list[dict[str, Any]]:
        statuses: list[MCPServerStatus] = [w.status for w in self._workers.values()] + list(self._disabled_statuses)
        return [
            {
                "name": s.name,
                "transport": s.transport,
                "enabled": s.enabled,
                "connected": s.connected,
                "tool_count": s.tool_count,
                "tools": s.tools,
                "error": s.error,
            }
            for s in statuses
        ]

    async def close_all(self) -> None:
        for name, worker in list(self._workers.items()):
            self.registry.unregister_by_source(f"mcp:{name}")
            await worker.stop()
        self._workers.clear()
