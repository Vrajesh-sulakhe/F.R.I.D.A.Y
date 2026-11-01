"""
Base abstractions for LLM providers and message models.
"""
from abc import ABC, abstractmethod
from typing import AsyncIterator, Any
from pydantic import BaseModel, Field


class ToolFunctionCall(BaseModel):
    id: str = ""
    name: str
    arguments: str  # JSON string


class ChatMessage(BaseModel):
    role: str  # "system", "user", "assistant", "tool"
    content: str | None = None
    name: str | None = None
    tool_call_id: str | None = None
    tool_calls: list[ToolFunctionCall] = Field(default_factory=list)


class ToolDefinition(BaseModel):
    name: str
    description: str
    parameters: dict[str, Any]


class TokenUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_usd: float = 0.0
    latency_ms: float = 0.0


class StreamChunk(BaseModel):
    content: str = ""
    tool_calls: list[ToolFunctionCall] = Field(default_factory=list)
    finish_reason: str | None = None
    usage: TokenUsage | None = None


class ChatResponse(BaseModel):
    content: str
    tool_calls: list[ToolFunctionCall] = Field(default_factory=list)
    finish_reason: str = "stop"
    usage: TokenUsage = Field(default_factory=TokenUsage)
    provider: str = ""
    model: str = ""


class LLMProvider(ABC):
    """Abstract Base Class for LLM providers."""

    def __init__(self, provider_id: str, name: str, base_url: str, api_key: str | None, default_models: list[str]):
        self.provider_id = provider_id
        self.name = name
        self.base_url = base_url.rstrip("/") if base_url else ""
        self.api_key = api_key
        self.default_models = default_models

    @abstractmethod
    async def chat_complete(
        self,
        messages: list[ChatMessage],
        model: str,
        tools: list[ToolDefinition] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> ChatResponse:
        """Execute a non-streaming chat completion."""
        pass

    @abstractmethod
    async def chat_stream(
        self,
        messages: list[ChatMessage],
        model: str,
        tools: list[ToolDefinition] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> AsyncIterator[StreamChunk]:
        """Execute a streaming chat completion yielding incremental chunks."""
        pass

    @abstractmethod
    async def test_connection(self, model: str | None = None) -> tuple[bool, str]:
        """Test API connectivity and model readiness."""
        pass
