"""Integration tests for /ws/chat AgentLoop execution and interactive Safety Gate over WebSocket."""
import json
from unittest.mock import patch
from fastapi.testclient import TestClient

from src.main import app, agent_loop, llm_manager
from src.llm.base import ChatResponse, TokenUsage, ToolFunctionCall


client = TestClient(app)


def test_tools_endpoint_includes_agent_tools():
    res = client.get("/api/tools")
    assert res.status_code == 200
    data = res.json()
    assert "tools" in data
    assert "agent_tools" in data
    names = [t["name"] for t in data["agent_tools"]]
    assert "list_directory" in names
    assert "read_file_snippet" in names
    assert "run_shell" in names


def test_websocket_agent_approval_flow_executes_and_returns_reply():
    executed = []

    async def fake_chat_complete(messages, model, tools=None, temperature=0.7, max_tokens=2048):
        # First call asks for CONFIRM tool open_mac_app; second call returns final answer
        if not executed:
            return ChatResponse(
                content="",
                tool_calls=[ToolFunctionCall(id="call_app", name="open_mac_app", arguments='{"app_name": "Notes"}')],
                provider="Mock",
                model="claude-3-5-sonnet-latest",
            )
        return ChatResponse(
            content="Notes is open for you, sir.",
            provider="Mock",
            model="claude-3-5-sonnet-latest",
            usage=TokenUsage(total_tokens=25),
        )

    def fake_open_app(app_name: str):
        executed.append(app_name)
        from src.agent.registry import ToolExecutionResult
        return ToolExecutionResult(ok=True, output=f"Launched {app_name}")

    orig_prov = llm_manager.active_provider_id
    orig_model = llm_manager.active_model
    try:
        llm_manager.active_provider_id = "openrouter"
        llm_manager.active_model = "anthropic/claude-3.5-sonnet"
        prov = llm_manager.providers["openrouter"]
        orig_key = prov.api_key
        prov.api_key = "test-key"

        tool = agent_loop.registry.get("open_mac_app")
        orig_handler = tool.handler
        tool.handler = fake_open_app

        try:
            with patch.object(prov, "chat_complete", side_effect=fake_chat_complete):
                with client.websocket_connect("/ws/chat") as ws:
                    init_msg = ws.receive_json()
                    assert init_msg["type"] == "init"

                    ws.send_json({"action": "chat", "message": "Please launch Notes using the open_mac_app tool."})

                    seen_types = []
                    for _ in range(15):
                        ev = ws.receive_json()
                        seen_types.append(ev["type"])
                        if ev["type"] == "tool_approval_request":
                            assert ev["tool_name"] == "open_mac_app"
                            ws.send_json({
                                "action": "tool_approval_response",
                                "request_id": ev["request_id"],
                                "approved": True,
                            })
                        if ev["type"] in ("stream_end", "state_update"):
                            break

                    assert "tool_start" in seen_types
                    assert "tool_approval_request" in seen_types
                    assert "tool_result" in seen_types
                    assert "stream_end" in seen_types
                    assert executed == ["Notes"]
        finally:
            tool.handler = orig_handler
            prov.api_key = orig_key
    finally:
        llm_manager.active_provider_id = orig_prov
        llm_manager.active_model = orig_model
