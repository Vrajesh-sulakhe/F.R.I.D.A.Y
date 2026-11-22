"""
OpenAI-compatible LLM provider adapter.
Supports OpenRouter, NVIDIA NIM, Ollama (/v1), LM Studio, and generic custom endpoints.
"""
import json
import logging
from typing import AsyncIterator, Any
import httpx

from .base import (
    LLMProvider,
    ChatMessage,
    ChatResponse,
    StreamChunk,
    ToolDefinition,
    ToolFunctionCall,
    TokenUsage,
)
from .token_tracker import TokenTracker, RequestTimer

logger = logging.getLogger("FRIDAY.OpenAICompatible")


class OpenAICompatibleProvider(LLMProvider):
    def __init__(
        self,
        provider_id: str,
        name: str,
        base_url: str,
        api_key: str | None,
        default_models: list[str],
        timeout_seconds: float = 60.0,
    ):
        super().__init__(provider_id, name, base_url, api_key, default_models)
        self.timeout = timeout_seconds

    def _get_headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "FRIDAY-Butler-System/1.0",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        # Optional OpenRouter specific headers
        if "openrouter.ai" in self.base_url:
            headers["HTTP-Referer"] = "http://localhost:4719"
            headers["X-Title"] = "FRIDAY AI Assistant"
        return headers

    def _format_messages(self, messages: list[ChatMessage]) -> list[dict[str, Any]]:
        formatted = []
        for msg in messages:
            item: dict[str, Any] = {"role": msg.role}
            if msg.images:
                parts: list[dict[str, Any]] = []
                if msg.content:
                    parts.append({"type": "text", "text": msg.content})
                for img in msg.images:
                    parts.append({
                        "type": "image_url",
                        "image_url": {"url": f"data:{img.mime_type};base64,{img.base64_data}"},
                    })
                item["content"] = parts
            elif msg.content is not None:
                item["content"] = msg.content
            if msg.name:
                item["name"] = msg.name
            if msg.tool_call_id:
                item["tool_call_id"] = msg.tool_call_id
            if msg.tool_calls:
                item["tool_calls"] = [
                    {
                        "id": tc.id or f"call_{i}",
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": tc.arguments,
                        },
                    }
                    for i, tc in enumerate(msg.tool_calls)
                ]
            formatted.append(item)
        return formatted

    def _format_tools(self, tools: list[ToolDefinition] | None) -> list[dict[str, Any]] | None:
        if not tools:
            return None
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            }
            for t in tools
        ]

    async def chat_complete(
        self,
        messages: list[ChatMessage],
        model: str,
        tools: list[ToolDefinition] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> ChatResponse:
        url = f"{self.base_url}/chat/completions"
        payload: dict[str, Any] = {
            "model": model,
            "messages": self._format_messages(messages),
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        formatted_tools = self._format_tools(tools)
        if formatted_tools:
            payload["tools"] = formatted_tools
            payload["tool_choice"] = "auto"

        with RequestTimer() as timer:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(url, headers=self._get_headers(), json=payload)
                if response.status_code != 200:
                    error_detail = response.text
                    try:
                        err_json = response.json()
                        error_detail = err_json.get("error", {}).get("message", response.text)
                    except Exception:
                        pass
                    raise RuntimeError(f"[{self.name}] Error {response.status_code}: {error_detail}")

                data = response.json()

        choice = data["choices"][0]
        msg = choice.get("message", {})
        content = msg.get("content") or ""
        finish_reason = choice.get("finish_reason") or "stop"

        tool_calls: list[ToolFunctionCall] = []
        if "tool_calls" in msg and msg["tool_calls"]:
            for tc in msg["tool_calls"]:
                fn = tc.get("function", {})
                tool_calls.append(
                    ToolFunctionCall(
                        id=tc.get("id", ""),
                        name=fn.get("name", ""),
                        arguments=fn.get("arguments", "{}"),
                    )
                )

        raw_usage = data.get("usage", {})
        prompt_tokens = raw_usage.get("prompt_tokens", len(str(messages)) // 4)
        completion_tokens = raw_usage.get("completion_tokens", len(content) // 4)
        total_tokens = raw_usage.get("total_tokens", prompt_tokens + completion_tokens)
        cost = TokenTracker.calculate_cost(self.provider_id, model, prompt_tokens, completion_tokens)

        usage = TokenUsage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            estimated_cost_usd=cost,
            latency_ms=timer.elapsed_ms,
        )

        TokenTracker.log_request(
            self.name, model, timer.elapsed_ms, prompt_tokens, completion_tokens, cost
        )

        return ChatResponse(
            content=content,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            usage=usage,
            provider=self.name,
            model=model,
        )

    async def chat_stream(
        self,
        messages: list[ChatMessage],
        model: str,
        tools: list[ToolDefinition] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> AsyncIterator[StreamChunk]:
        url = f"{self.base_url}/chat/completions"
        payload: dict[str, Any] = {
            "model": model,
            "messages": self._format_messages(messages),
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }
        formatted_tools = self._format_tools(tools)
        if formatted_tools:
            payload["tools"] = formatted_tools
            payload["tool_choice"] = "auto"

        # Buffer for accumulating partial tool call deltas
        tool_call_buffers: dict[int, dict[str, str]] = {}
        accumulated_content = ""

        with RequestTimer() as timer:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                async with client.stream("POST", url, headers=self._get_headers(), json=payload) as response:
                    if response.status_code != 200:
                        err_text = await response.aread()
                        raise RuntimeError(f"[{self.name}] Stream error {response.status_code}: {err_text.decode('utf-8', errors='ignore')}")

                    async for line in response.aiter_lines():
                        if not line:
                            continue
                        line = line.strip()
                        if line.startswith("data: "):
                            data_str = line[6:].strip()
                            if data_str == "[DONE]":
                                break
                            try:
                                chunk_data = json.loads(data_str)
                            except json.JSONDecodeError:
                                continue

                            choices = chunk_data.get("choices", [])
                            if not choices:
                                continue
                            delta = choices[0].get("delta", {})
                            finish_reason = choices[0].get("finish_reason")

                            # Handle text content
                            if "content" in delta and delta["content"]:
                                text_piece = delta["content"]
                                accumulated_content += text_piece
                                yield StreamChunk(content=text_piece)

                            # Handle streaming tool calls
                            if "tool_calls" in delta and delta["tool_calls"]:
                                for tc_delta in delta["tool_calls"]:
                                    idx = tc_delta.get("index", 0)
                                    if idx not in tool_call_buffers:
                                        tool_call_buffers[idx] = {
                                            "id": tc_delta.get("id", ""),
                                            "name": tc_delta.get("function", {}).get("name", ""),
                                            "arguments": "",
                                        }
                                    fn_part = tc_delta.get("function", {})
                                    if "name" in fn_part and fn_part["name"]:
                                        tool_call_buffers[idx]["name"] = fn_part["name"]
                                    if "arguments" in fn_part and fn_part["arguments"]:
                                        tool_call_buffers[idx]["arguments"] += fn_part["arguments"]

                            # Final chunk with finish reason
                            if finish_reason:
                                complete_tool_calls: list[ToolFunctionCall] = []
                                for idx in sorted(tool_call_buffers.keys()):
                                    buf = tool_call_buffers[idx]
                                    complete_tool_calls.append(
                                        ToolFunctionCall(
                                            id=buf["id"] or f"call_{idx}",
                                            name=buf["name"],
                                            arguments=buf["arguments"],
                                        )
                                    )

                                prompt_tokens = len(str(messages)) // 4
                                completion_tokens = len(accumulated_content) // 4
                                cost = TokenTracker.calculate_cost(
                                    self.provider_id, model, prompt_tokens, completion_tokens
                                )
                                usage = TokenUsage(
                                    prompt_tokens=prompt_tokens,
                                    completion_tokens=completion_tokens,
                                    total_tokens=prompt_tokens + completion_tokens,
                                    estimated_cost_usd=cost,
                                    latency_ms=timer.elapsed_ms,
                                )
                                TokenTracker.log_request(
                                    self.name, model, timer.elapsed_ms, prompt_tokens, completion_tokens, cost
                                )

                                yield StreamChunk(
                                    content="",
                                    tool_calls=complete_tool_calls,
                                    finish_reason=finish_reason,
                                    usage=usage,
                                )

    async def test_connection(self, model: str | None = None) -> tuple[bool, str]:
        target_model = model or (self.default_models[0] if self.default_models else "")
        if not self.base_url:
            return False, "Base URL not configured"
        try:
            # Quick lightweight test query
            res = await self.chat_complete(
                messages=[ChatMessage(role="user", content="Ping. Reply with Pong.")],
                model=target_model,
                max_tokens=10,
            )
            return True, f"Connection OK ({self.name} - {target_model}): {res.content.strip()}"
        except Exception as e:
            return False, f"Connection failed: {str(e)}"
