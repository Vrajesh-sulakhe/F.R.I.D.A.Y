"""
Async ReAct AgentLoop for F.R.I.D.A.Y.
Coordinates capability-aware routing, BYOK vision delegation, multi-step tool calls,
structured ReAct fallback for non-tool models, and human-in-the-loop Safety Gate.
"""
import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from src.agent.registry import ToolRegistry, ToolRiskTier
from src.llm.base import (
    ChatMessage,
    ModelCapabilities,
    TokenUsage,
    ToolFunctionCall,
)
from src.llm.router import ModelRouter

if TYPE_CHECKING:
    from src.llm.manager import LLMManager

logger = logging.getLogger("FRIDAY.AgentLoop")

EmitFn = Callable[[dict[str, Any]], Awaitable[None]]
ApprovalFn = Callable[[str, str, dict[str, Any], str], Awaitable[bool]]

_TOOL_CALL_RE = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.DOTALL | re.IGNORECASE)
_THINK_BLOCK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


@dataclass
class AgentRunResult:
    reply: str
    provider: str
    model: str
    steps: int
    usage: TokenUsage = field(default_factory=TokenUsage)
    tool_events: list[dict[str, Any]] = field(default_factory=list)


class AgentLoop:
    """Bounded ReAct loop with Safety Gate and transparent HUD step streaming."""

    def __init__(
        self,
        manager: "LLMManager",
        router: ModelRouter,
        registry: ToolRegistry,
        max_steps: int = 8,
        context_provider: Callable[[str], Awaitable[str]] | None = None,
    ):
        self.manager = manager
        self.router = router
        self.registry = registry
        self.max_steps = max(1, max_steps)
        self.context_provider = context_provider

    @staticmethod
    def _clean_final_reply(text: str) -> str:
        cleaned = _THINK_BLOCK_RE.sub("", text or "")
        cleaned = _TOOL_CALL_RE.sub("", cleaned)
        return cleaned.strip()

    @staticmethod
    def _parse_react_tool_calls(text: str) -> list[ToolFunctionCall]:
        calls: list[ToolFunctionCall] = []
        for idx, match in enumerate(_TOOL_CALL_RE.finditer(text or "")):
            raw_json = match.group(1).strip()
            try:
                obj = json.loads(raw_json)
                name = str(obj.get("name", "")).strip()
                args = obj.get("arguments", {})
                if name:
                    calls.append(
                        ToolFunctionCall(
                            id=f"react_{idx}",
                            name=name,
                            arguments=json.dumps(args) if isinstance(args, dict) else str(args),
                        )
                    )
            except json.JSONDecodeError:
                continue
        return calls

    def _build_react_instructions(self) -> str:
        lines = [
            "You have access to the following local tools. Only call a tool when genuinely needed to answer or act:",
        ]
        for td in self.registry.list_definitions():
            lines.append(f"- {td.name}: {td.description} | schema={json.dumps(td.parameters)}")
        lines.append(
            'To invoke a tool, output exactly: <tool_call>{"name": "<tool_name>", "arguments": {<key>: <value>}}</tool_call>'
        )
        lines.append("Wait for the [Tool Result] before writing your final answer. When ready to answer directly, do not output <tool_call>.")
        return "\n".join(lines)

    async def _prepare_messages(
        self,
        messages: list[ChatMessage],
        caps: ModelCapabilities,
        emit: EmitFn | None,
    ) -> list[ChatMessage]:
        """Ensure system prompt is present and delegate attached images if active model lacks vision."""
        prepared: list[ChatMessage] = []
        for m in messages:
            copy_m = m.model_copy(deep=True)
            if copy_m.images and not caps.vision:
                if emit:
                    await emit({"type": "agent_plan", "message": "Delegating visual frame to Vision model..."})
                vision_out = await self.router.inspect_images(
                    copy_m.images,
                    prompt=f"Analyze these image attachments cleanly for this request: {copy_m.content or 'Describe what is visible.'}",
                )
                if vision_out:
                    desc, v_prov, v_model = vision_out
                    note = f"\n\n[Visual Perception via {v_prov} ({v_model})]:\n{desc}"
                else:
                    note = (
                        "\n\n[Visual Perception Unavailable: No vision-capable model is currently configured "
                        "for the active API keys. Inform the user politely if visual details are required.]"
                    )
                copy_m.content = (copy_m.content or "") + note
                copy_m.images = []
            prepared.append(copy_m)

        if not prepared or prepared[0].role != "system":
            prepared.insert(0, ChatMessage(role="system", content=self.manager.get_system_prompt()))

        if self.context_provider is not None:
            latest_user_text = ""
            for m in reversed(prepared):
                if m.role == "user" and m.content:
                    latest_user_text = m.content
                    break
            try:
                ambient_ctx = await self.context_provider(latest_user_text)
                if ambient_ctx:
                    prepared[0] = ChatMessage(
                        role="system",
                        content=f"{prepared[0].content or ''}\n\n{ambient_ctx}",
                    )
            except Exception as e:
                logger.debug(f"Ambient context provider skipped: {e}")

        return prepared

    async def run(
        self,
        messages: list[ChatMessage],
        emit: EmitFn | None = None,
        approval_handler: ApprovalFn | None = None,
        temperature: float = 0.7,
    ) -> AgentRunResult:
        resolved = self.router.resolve_model("chat")
        if not resolved:
            fallback_msg = (
                "No LLM provider is currently configured or reachable, sir. "
                "Please add an API key or ensure Ollama is running."
            )
            if emit:
                await emit({"type": "stream_start", "provider": "Offline", "model": "none"})
                await emit({"type": "stream_chunk", "content": fallback_msg, "finish_reason": "stop", "usage": None})
            return AgentRunResult(reply=fallback_msg, provider="Offline", model="none", steps=0)

        provider, model_id, caps = resolved
        tool_defs = self.registry.list_definitions()
        working = await self._prepare_messages(messages, caps, emit)

        use_native_tools = bool(tool_defs) and caps.tools
        if tool_defs and not use_native_tools:
            working[0] = ChatMessage(
                role="system",
                content=f"{working[0].content or ''}\n\n{self._build_react_instructions()}",
            )

        if emit:
            await emit({"type": "stream_start", "provider": provider.name, "model": model_id})

        total_usage = TokenUsage()
        tool_events: list[dict[str, Any]] = []
        steps_taken = 0

        for step in range(1, self.max_steps + 1):
            steps_taken = step
            try:
                response = await provider.chat_complete(
                    messages=working,
                    model=model_id,
                    tools=tool_defs if use_native_tools else None,
                    temperature=temperature,
                )
            except Exception as e:
                if use_native_tools:
                    logger.warning(f"Native tool call rejected on {provider.name}/{model_id}, switching to ReAct fallback: {e}")
                    use_native_tools = False
                    working[0] = ChatMessage(
                        role="system",
                        content=f"{working[0].content or ''}\n\n{self._build_react_instructions()}",
                    )
                    response = await provider.chat_complete(
                        messages=working,
                        model=model_id,
                        tools=None,
                        temperature=temperature,
                    )
                else:
                    raise

            total_usage.prompt_tokens += response.usage.prompt_tokens
            total_usage.completion_tokens += response.usage.completion_tokens
            total_usage.total_tokens += response.usage.total_tokens
            total_usage.estimated_cost_usd += response.usage.estimated_cost_usd
            total_usage.latency_ms += response.usage.latency_ms

            tool_calls = list(response.tool_calls)
            if not tool_calls and not use_native_tools and tool_defs:
                tool_calls = self._parse_react_tool_calls(response.content)

            if not tool_calls:
                final_text = self._clean_final_reply(response.content)
                if emit and final_text:
                    await emit({
                        "type": "stream_chunk",
                        "content": final_text,
                        "finish_reason": "stop",
                        "usage": total_usage.model_dump(),
                    })
                return AgentRunResult(
                    reply=final_text,
                    provider=provider.name,
                    model=model_id,
                    steps=steps_taken,
                    usage=total_usage,
                    tool_events=tool_events,
                )

            # Append assistant turn with requested tool calls
            if use_native_tools:
                working.append(
                    ChatMessage(
                        role="assistant",
                        content=response.content or None,
                        tool_calls=tool_calls,
                    )
                )
            else:
                working.append(ChatMessage(role="assistant", content=response.content))

            # Execute each requested tool with Safety Gate checks
            react_observations: list[str] = []
            for tc in tool_calls:
                parsed_args, parse_err = self.registry.parse_arguments(tc.arguments)
                risk_tier = self.registry.get_tier(tc.name)

                start_ev = {
                    "type": "tool_start",
                    "step": step,
                    "tool_name": tc.name,
                    "arguments": parsed_args if not parse_err else tc.arguments,
                    "risk_tier": risk_tier.value,
                }
                tool_events.append(start_ev)
                if emit:
                    await emit(start_ev)

                approved = True
                if risk_tier in (ToolRiskTier.CONFIRM, ToolRiskTier.DANGEROUS):
                    if approval_handler is None:
                        approved = False
                    else:
                        req_id = f"apr_{uuid.uuid4().hex[:10]}"
                        approved = await approval_handler(req_id, tc.name, parsed_args, risk_tier.value)

                if not approved:
                    obs_text = (
                        f"Execution of '{tc.name}' was declined by user confirmation gate "
                        "(or requires interactive HUD approval)."
                    )
                    res_ok = False
                else:
                    tool_res = await self.registry.execute(tc.name, tc.arguments)
                    obs_text = tool_res.output
                    res_ok = tool_res.ok

                res_ev = {
                    "type": "tool_result",
                    "step": step,
                    "tool_name": tc.name,
                    "ok": res_ok,
                    "output": obs_text[:600],
                }
                tool_events.append(res_ev)
                if emit:
                    await emit(res_ev)

                if use_native_tools:
                    working.append(
                        ChatMessage(
                            role="tool",
                            name=tc.name,
                            tool_call_id=tc.id or f"call_{step}_{tc.name}",
                            content=obs_text,
                        )
                    )
                else:
                    react_observations.append(f"[Tool Result: {tc.name} | ok={res_ok}]\n{obs_text}")

            if not use_native_tools and react_observations:
                working.append(ChatMessage(role="user", content="\n\n".join(react_observations)))

        cap_reply = (
            f"I reached the agent step limit ({self.max_steps} steps), sir. "
            "Let me know if you'd like me to continue from what I've gathered so far."
        )
        if emit:
            await emit({
                "type": "stream_chunk",
                "content": cap_reply,
                "finish_reason": "stop",
                "usage": total_usage.model_dump(),
            })
        return AgentRunResult(
            reply=cap_reply,
            provider=provider.name,
            model=model_id,
            steps=steps_taken,
            usage=total_usage,
            tool_events=tool_events,
        )
