"""
Native Anthropic Claude API provider adapter.
"""
import json
import logging
from typing import AsyncIterator, Any
import anthropic

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

logger = logging.getLogger("FRIDAY.Anthropic")


class AnthropicProvider(LLMProvider):
    def __init__(
        self,
        provider_id: str,
        name: str,
        base_url: str,
        api_key: str | None,
        default_models: list[str],
    ):
        super().__init__(provider_id, name, base_url, api_key, default_models)
        self._client: anthropic.AsyncAnthropic | None = None
        if api_key:
            self._client = anthropic.AsyncAnthropic(api_key=api_key)

    def _ensure_client(self) -> anthropic.AsyncAnthropic:
        if not self.api_key:
            raise ValueError("Anthropic API key is not set in environment or settings.")
        if self._client is None:
            self._client = anthropic.AsyncAnthropic(api_key=self.api_key)
        return self._client

    def _convert_messages(self, messages: list[ChatMessage]) -> tuple[str | None, list[dict[str, Any]]]:
        system_prompt: str | None = None
        converted: list[dict[str, Any]] = []

        for msg in messages:
            if msg.role == "system":
                # Anthropic expects system instructions as a top-level parameter
                if system_prompt is None:
                    system_prompt = msg.content or ""
                else:
                    system_prompt += "\n" + (msg.content or "")
            elif msg.role == "tool":
                converted.append({
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": msg.tool_call_id or "",
                            "content": msg.content or "",
                        }
                    ],
                })
            elif msg.role == "assistant":
                content_blocks: list[dict[str, Any]] = []
                if msg.content:
                    content_blocks.append({"type": "text", "text": msg.content})
                if msg.tool_calls:
                    for tc in msg.tool_calls:
                        try:
                            args_obj = json.loads(tc.arguments)
                        except Exception:
                            args_obj = {}
                        content_blocks.append({
                            "type": "tool_use",
                            "id": tc.id or f"tool_u_{tc.name}",
                            "name": tc.name,
                            "input": args_obj,
                        })
                converted.append({
                    "role": "assistant",
                    "content": content_blocks if content_blocks else msg.content or "",
                })
            else:
                converted.append({
                    "role": "user",
                    "content": msg.content or "",
                })

        return system_prompt, converted

    def _convert_tools(self, tools: list[ToolDefinition] | None) -> list[dict[str, Any]] | None:
        if not tools:
            return None
        return [
            {
                "name": t.name,
                "description": t.description,
                "input_schema": t.parameters,
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
        client = self._ensure_client()
        system_prompt, formatted_msgs = self._convert_messages(messages)
        formatted_tools = self._convert_tools(tools)

        params: dict[str, Any] = {
            "model": model,
            "messages": formatted_msgs,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if system_prompt:
            params["system"] = system_prompt
        if formatted_tools:
            params["tools"] = formatted_tools

        with RequestTimer() as timer:
            response = await client.messages.create(**params)

        content_text = ""
        tool_calls: list[ToolFunctionCall] = []

        for block in response.content:
            if block.type == "text":
                content_text += block.text
            elif block.type == "tool_use":
                tool_calls.append(
                    ToolFunctionCall(
                        id=block.id,
                        name=block.name,
                        arguments=json.dumps(block.input),
                    )
                )

        prompt_tokens = response.usage.input_tokens
        completion_tokens = response.usage.output_tokens
        cost = TokenTracker.calculate_cost(self.provider_id, model, prompt_tokens, completion_tokens)

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

        return ChatResponse(
            content=content_text,
            tool_calls=tool_calls,
            finish_reason=response.stop_reason or "stop",
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
        client = self._ensure_client()
        system_prompt, formatted_msgs = self._convert_messages(messages)
        formatted_tools = self._convert_tools(tools)

        params: dict[str, Any] = {
            "model": model,
            "messages": formatted_msgs,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if system_prompt:
            params["system"] = system_prompt
        if formatted_tools:
            params["tools"] = formatted_tools

        with RequestTimer() as timer:
            async with client.messages.stream(**params) as stream:
                async for text in stream.text_stream:
                    yield StreamChunk(content=text)

                final_message = await stream.get_final_message()
                tool_calls: list[ToolFunctionCall] = []
                for block in final_message.content:
                    if block.type == "tool_use":
                        tool_calls.append(
                            ToolFunctionCall(
                                id=block.id,
                                name=block.name,
                                arguments=json.dumps(block.input),
                            )
                        )

                prompt_tokens = final_message.usage.input_tokens
                completion_tokens = final_message.usage.output_tokens
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
                    tool_calls=tool_calls,
                    finish_reason=final_message.stop_reason or "stop",
                    usage=usage,
                )

    async def test_connection(self, model: str | None = None) -> tuple[bool, str]:
        if not self.api_key:
            return False, "Anthropic API key is missing in environment."
        target_model = model or (self.default_models[0] if self.default_models else "claude-3-5-haiku-latest")
        try:
            res = await self.chat_complete(
                messages=[ChatMessage(role="user", content="Ping. Respond with Pong.")],
                model=target_model,
                max_tokens=10,
            )
            return True, f"Connection OK ({self.name} - {target_model}): {res.content.strip()}"
        except Exception as e:
            return False, f"Connection failed: {str(e)}"
