"""Tests for async AgentLoop: multi-step tools, Safety Gate, ReAct fallback, vision delegation, and step caps."""
import json
import pytest

from src.agent.registry import RegisteredTool, ToolExecutionResult, ToolRegistry, ToolRiskTier
from src.agent.loop import AgentLoop
from src.llm.base import (
    ChatMessage,
    ChatResponse,
    ImageAttachment,
    LLMProvider,
    StreamChunk,
    TokenUsage,
    ToolFunctionCall,
)
from src.llm.router import ModelRouter


class FakeProvider(LLMProvider):
    def __init__(self, provider_id, name, scripted_responses, api_key="test-key", default_models=None):
        super().__init__(provider_id, name, "https://fake.local/v1", api_key, default_models or ["fake-model"])
        self.scripted = list(scripted_responses)
        self.calls = []

    async def chat_complete(self, messages, model, tools=None, temperature=0.7, max_tokens=2048):
        self.calls.append({"messages": list(messages), "model": model, "tools": tools})
        if not self.scripted:
            return ChatResponse(content="Done.", provider=self.name, model=model)
        nxt = self.scripted.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt

    async def chat_stream(self, messages, model, tools=None, temperature=0.7, max_tokens=2048):
        res = await self.chat_complete(messages, model, tools=tools, temperature=temperature, max_tokens=max_tokens)
        yield StreamChunk(content=res.content, tool_calls=res.tool_calls, finish_reason="stop", usage=res.usage)

    async def test_connection(self, model=None):
        return True, "OK"


class StubManager:
    def __init__(self, providers, active_provider_id, active_model, system_prompt="You are FRIDAY."):
        self.providers = providers
        self.active_provider_id = active_provider_id
        self.active_model = active_model
        self.fallback_chain = []
        self._prompt = system_prompt

    def get_active_provider(self):
        return self.providers[self.active_provider_id], self.active_model

    def get_system_prompt(self):
        return self._prompt


@pytest.mark.anyio
async def test_agent_loop_executes_safe_tool_and_returns_final_answer():
    reg = ToolRegistry()
    reg.register(
        RegisteredTool(
            name="get_time",
            description="Get current local time",
            parameters={"type": "object", "properties": {}},
            handler=lambda: ToolExecutionResult(ok=True, output="21:00 IST"),
            risk_tier=ToolRiskTier.SAFE,
        )
    )

    prov = FakeProvider(
        "openrouter",
        "OpenRouter",
        [
            ChatResponse(
                content="",
                tool_calls=[ToolFunctionCall(id="call_1", name="get_time", arguments="{}")],
                finish_reason="tool_calls",
                provider="OpenRouter",
                model="anthropic/claude-3.5-sonnet",
            ),
            ChatResponse(
                content="It is currently 21:00 IST, sir.",
                provider="OpenRouter",
                model="anthropic/claude-3.5-sonnet",
                usage=TokenUsage(total_tokens=42),
            ),
        ],
        default_models=["anthropic/claude-3.5-sonnet"],
    )
    mgr = StubManager({"openrouter": prov}, "openrouter", "anthropic/claude-3.5-sonnet")
    loop = AgentLoop(mgr, ModelRouter(mgr), reg)

    events = []

    async def emit(ev):
        events.append(ev)

    result = await loop.run(
        messages=[ChatMessage(role="user", content="What time is it?")],
        emit=emit,
    )

    assert "21:00 IST" in result.reply
    assert result.steps == 2
    assert any(e["type"] == "tool_start" and e["tool_name"] == "get_time" for e in events)
    assert any(e["type"] == "tool_result" and e["ok"] is True for e in events)
    assert any(e["type"] == "stream_chunk" for e in events)


@pytest.mark.anyio
async def test_agent_loop_enforces_safety_gate_approval_and_denial():
    ran_commands = []
    reg = ToolRegistry()
    reg.register(
        RegisteredTool(
            name="run_shell",
            description="Run shell",
            parameters={"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]},
            handler=lambda command: (ran_commands.append(command), ToolExecutionResult(ok=True, output="ok"))[1],
            risk_tier=ToolRiskTier.DANGEROUS,
        )
    )

    # Denied case: tool must NOT execute
    prov_deny = FakeProvider(
        "openrouter",
        "OpenRouter",
        [
            ChatResponse(
                content="",
                tool_calls=[ToolFunctionCall(id="c1", name="run_shell", arguments='{"command": "rm -rf /tmp/x"}')],
            ),
            ChatResponse(content="Understood, sir. I canceled the command."),
        ],
        default_models=["anthropic/claude-3.5-sonnet"],
    )
    mgr_deny = StubManager({"openrouter": prov_deny}, "openrouter", "anthropic/claude-3.5-sonnet")
    loop_deny = AgentLoop(mgr_deny, ModelRouter(mgr_deny), reg)

    async def deny_all(req_id, tool_name, args, risk_tier):
        return False

    res_deny = await loop_deny.run(
        messages=[ChatMessage(role="user", content="Delete /tmp/x")],
        approval_handler=deny_all,
    )
    assert ran_commands == []
    assert "canceled" in res_deny.reply.lower()

    # Approved case: tool executes
    prov_ok = FakeProvider(
        "openrouter",
        "OpenRouter",
        [
            ChatResponse(
                content="",
                tool_calls=[ToolFunctionCall(id="c2", name="run_shell", arguments='{"command": "ls -la"}')],
            ),
            ChatResponse(content="Command finished, sir."),
        ],
        default_models=["anthropic/claude-3.5-sonnet"],
    )
    mgr_ok = StubManager({"openrouter": prov_ok}, "openrouter", "anthropic/claude-3.5-sonnet")
    loop_ok = AgentLoop(mgr_ok, ModelRouter(mgr_ok), reg)

    async def approve_all(req_id, tool_name, args, risk_tier):
        return True

    res_ok = await loop_ok.run(
        messages=[ChatMessage(role="user", content="List files")],
        approval_handler=approve_all,
    )
    assert ran_commands == ["ls -la"]
    assert "finished" in res_ok.reply.lower()


@pytest.mark.anyio
async def test_agent_loop_react_text_fallback_for_non_tool_models():
    reg = ToolRegistry()
    reg.register(
        RegisteredTool(
            name="system_status",
            description="Get OS status",
            parameters={"type": "object", "properties": {}},
            handler=lambda: ToolExecutionResult(ok=True, output="macOS arm64 load 1.2"),
            risk_tier=ToolRiskTier.SAFE,
        )
    )

    # deepseek-r1 on NIM has tools=False -> AgentLoop parses <tool_call> JSON tag
    prov = FakeProvider(
        "nvidia_nim",
        "NVIDIA NIM",
        [
            ChatResponse(
                content='Let me check.\n<tool_call>{"name": "system_status", "arguments": {}}</tool_call>',
                provider="NVIDIA NIM",
                model="deepseek-ai/deepseek-r1",
            ),
            ChatResponse(
                content="Your Mac is running smoothly on arm64 with load 1.2, sir.",
                provider="NVIDIA NIM",
                model="deepseek-ai/deepseek-r1",
            ),
        ],
        default_models=["deepseek-ai/deepseek-r1"],
    )
    mgr = StubManager({"nvidia_nim": prov}, "nvidia_nim", "deepseek-ai/deepseek-r1")
    loop = AgentLoop(mgr, ModelRouter(mgr), reg)

    res = await loop.run(messages=[ChatMessage(role="user", content="Check system status")])
    assert "arm64" in res.reply
    assert prov.calls[0]["tools"] is None


@pytest.mark.anyio
async def test_agent_loop_delegates_vision_from_text_only_model():
    reg = ToolRegistry()
    prov = FakeProvider(
        "nvidia_nim",
        "NVIDIA NIM",
        [
            ChatResponse(content="VS Code shows a SyntaxError on line 12."),  # vision inspection
            ChatResponse(content="Sir, the SyntaxError on line 12 needs a closing parenthesis."),  # final text reply
        ],
        default_models=["deepseek-ai/deepseek-r1", "meta/llama-3.2-90b-vision-instruct"],
    )
    mgr = StubManager({"nvidia_nim": prov}, "nvidia_nim", "deepseek-ai/deepseek-r1")
    loop = AgentLoop(mgr, ModelRouter(mgr), reg)

    img = ImageAttachment(base64_data="abc", mime_type="image/jpeg", label="screen")
    res = await loop.run(messages=[ChatMessage(role="user", content="What's wrong on my screen?", images=[img])])

    assert "closing parenthesis" in res.reply
    assert prov.calls[0]["model"] == "meta/llama-3.2-90b-vision-instruct"
    assert prov.calls[1]["model"] == "deepseek-ai/deepseek-r1"
    assert not prov.calls[1]["messages"][-1].images


@pytest.mark.anyio
async def test_agent_loop_caps_infinite_tool_loops():
    reg = ToolRegistry()
    reg.register(
        RegisteredTool(
            name="ping",
            description="Ping",
            parameters={"type": "object", "properties": {}},
            handler=lambda: ToolExecutionResult(ok=True, output="pong"),
            risk_tier=ToolRiskTier.SAFE,
        )
    )

    endless_calls = [
        ChatResponse(content="", tool_calls=[ToolFunctionCall(id=f"c{i}", name="ping", arguments="{}")])
        for i in range(12)
    ]
    prov = FakeProvider("openrouter", "OpenRouter", endless_calls, default_models=["anthropic/claude-3.5-sonnet"])
    mgr = StubManager({"openrouter": prov}, "openrouter", "anthropic/claude-3.5-sonnet")
    loop = AgentLoop(mgr, ModelRouter(mgr), reg, max_steps=3)

    res = await loop.run(messages=[ChatMessage(role="user", content="Keep pinging")])
    assert res.steps == 3
    assert "step limit" in res.reply.lower() or "3 steps" in res.reply.lower()
