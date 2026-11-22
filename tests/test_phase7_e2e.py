"""End-to-end integration tests for Phase 3-7 APIs, voice approval, ambient context, and telemetry."""
from unittest.mock import patch
from fastapi.testclient import TestClient

from src.main import app, agent_loop, llm_manager, memory_store
from src.llm.base import ChatResponse, TokenUsage, ToolFunctionCall


client = TestClient(app)


def test_phase3_to_7_api_endpoints():
    # Memories API CRUD
    res_add = client.post(
        "/api/memories",
        json={"topic": "Stack Note", "content": "FastAPI serves on 4719.", "category": "Tech", "importance": 4},
    )
    assert res_add.status_code == 200
    mem_id = res_add.json()["memory"]["id"]

    res_list = client.get("/api/memories")
    assert res_list.status_code == 200
    assert any(m["id"] == mem_id for m in res_list.json()["memories"])

    res_del = client.delete(f"/api/memories/{mem_id}")
    assert res_del.status_code == 200
    assert res_del.json()["deleted"] is True

    # MCP servers API
    res_mcp = client.get("/api/mcp/servers")
    assert res_mcp.status_code == 200
    assert "servers" in res_mcp.json()

    # Reflex status + on-demand briefing trigger
    res_rfx = client.get("/api/reflex/status")
    assert res_rfx.status_code == 200
    assert res_rfx.json()["armed"] is True

    res_brief = client.post("/api/reflex/trigger/tactical_briefing")
    assert res_brief.status_code == 200
    assert len(res_brief.json()["alerts"]) == 1

    # Missions API
    res_msn = client.post("/api/missions", json={"title": "Smoke Mission", "goal": "Check system vitals"})
    assert res_msn.status_code == 200
    msn_id = res_msn.json()["mission"]["id"]
    assert res_msn.json()["mission"]["status"] == "pending"

    res_msns = client.get("/api/missions")
    assert any(m["id"] == msn_id for m in res_msns.json()["missions"])


def test_websocket_hands_free_voice_approval():
    executed = []

    async def fake_chat_complete(messages, model, tools=None, temperature=0.7, max_tokens=2048):
        if not executed:
            return ChatResponse(
                content="",
                tool_calls=[ToolFunctionCall(id="v1", name="open_mac_app", arguments='{"app_name": "Safari"}')],
                provider="Mock",
                model="claude-3-5-sonnet-latest",
            )
        return ChatResponse(
            content="Safari launched via voice approval, sir.",
            provider="Mock",
            model="claude-3-5-sonnet-latest",
            usage=TokenUsage(total_tokens=18),
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
                    assert ws.receive_json()["type"] == "init"
                    ws.send_json({"action": "chat", "message": "Please launch Safari using the app tool."})

                    seen = []
                    for _ in range(15):
                        ev = ws.receive_json()
                        seen.append(ev["type"])
                        if ev["type"] == "tool_approval_request":
                            # User speaks "approve" as a chat message instead of clicking button!
                            ws.send_json({"action": "chat", "message": "approve"})
                        if ev["type"] == "stream_end":
                            break

                    assert "approval_voice_ack" in seen
                    assert "tool_result" in seen
                    assert executed == ["Safari"]
        finally:
            tool.handler = orig_handler
            prov.api_key = orig_key
    finally:
        llm_manager.active_provider_id = orig_prov
        llm_manager.active_model = orig_model
