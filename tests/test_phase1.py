"""
Phase 1 automated tests: LLM multi-provider management, brain switching,
dialogue persona, and API server endpoints.
"""
import pytest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient

from src.main import app, llm_manager
from src.llm import ChatMessage, TokenTracker, StreamChunk

client = TestClient(app)


@pytest.fixture(autouse=True)
def _restore_settings_after_test():
    """Keep config/settings.json and llm_manager active state intact across test runs."""
    settings_path = llm_manager.settings_json_path
    orig_raw = settings_path.read_text(encoding="utf-8") if settings_path.exists() else None
    orig_prov = llm_manager.active_provider_id
    orig_model = llm_manager.active_model
    orig_voice = llm_manager.active_voice_name
    orig_engine = llm_manager.active_voice_engine
    orig_chain = list(llm_manager.fallback_chain)
    try:
        yield
    finally:
        llm_manager.active_provider_id = orig_prov
        llm_manager.active_model = orig_model
        llm_manager.active_voice_name = orig_voice
        llm_manager.active_voice_engine = orig_engine
        llm_manager.fallback_chain = orig_chain
        if orig_raw is not None:
            settings_path.write_text(orig_raw, encoding="utf-8")


def test_health_endpoint():
    res = client.get("/api/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "online"
    assert data["system"] == "FRIDAY"
    assert data["port"] == 4719
    assert "active_provider" in data
    assert "active_model" in data


def test_fresh_session_endpoint():
    res = client.get("/api/session/fresh")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "fresh"
    assert data["greeting"] == "Hello, sir."


def test_providers_list():
    res = client.get("/api/providers")
    assert res.status_code == 200
    data = res.json()
    assert "providers" in data
    prov_ids = [p["id"] for p in data["providers"]]
    assert "ollama_local" in prov_ids
    assert "openrouter" in prov_ids
    assert "nvidia_nim" in prov_ids
    assert "anthropic" in prov_ids


def test_voice_text_brain_switching():
    # 1. Switch to local brain (Qwen 3.5 9B)
    handled, reply = llm_manager.handle_voice_or_text_command("FRIDAY, switch to your local brain")
    assert handled is True
    assert "Qwen 3.5" in reply
    assert "9 billion parameters" in reply
    assert llm_manager.active_provider_id == "ollama_local"
    assert llm_manager.active_model == "qwen3.5:9b"

    # 2. Switch to Gemma 4 12B
    handled, reply = llm_manager.handle_voice_or_text_command("Switch to Gemma 4 12 billion parameter")
    assert handled is True
    assert "Gemma 4" in reply
    assert "12 billion parameters" in reply
    assert llm_manager.active_provider_id == "ollama_local"
    assert llm_manager.active_model == "gemma4:12b"

    # 3. Switch your brain back to Qwen 3.5
    handled, reply = llm_manager.handle_voice_or_text_command("Switch your brain back to Qwen 3.5")
    assert handled is True
    assert "Qwen 3.5 fitted" in reply
    assert llm_manager.active_provider_id == "ollama_local"
    assert llm_manager.active_model == "qwen3.5:9b"

    # 4. Asked how it feels running locally
    handled, reply = llm_manager.handle_voice_or_text_command("How do you feel running locally?")
    assert handled is True
    assert "Rather well, sir." in reply
    assert "family doesn't get paid" in reply

    # 5. Switch to OpenRouter
    handled, reply = llm_manager.handle_voice_or_text_command("switch to OpenRouter")
    assert handled is True
    assert "OpenRouter" in reply
    assert llm_manager.active_provider_id == "openrouter"

    # 6. Switch to Claude / Cloud Brain
    handled, reply = llm_manager.handle_voice_or_text_command("switch to Claude")
    assert handled is True
    assert "Cloud brain engaged" in reply


def test_chat_command_via_api():
    # Test chat endpoint with voice command
    res = client.post("/api/chat", json={"message": "FRIDAY, switch to your local brain"})
    assert res.status_code == 200
    data = res.json()
    assert data["is_command"] is True
    assert "Qwen 3.5" in data["reply"]
    assert data["model"] == "qwen3.5:9b"


def test_token_tracker_cost_calculation():
    # Local model is always $0.00
    local_cost = TokenTracker.calculate_cost("ollama_local", "qwen3.5:9b", 1000, 500)
    assert local_cost == 0.0

    # Claude 3.5 Sonnet: $3 / $15 per million
    claude_cost = TokenTracker.calculate_cost("anthropic", "claude-3-5-sonnet-latest", 1_000_000, 1_000_000)
    assert claude_cost == 18.0


def test_dynamic_system_state():
    res = client.get("/api/system/state")
    assert res.status_code == 200
    data = res.json()
    assert "identity" in data
    assert data["identity"]["title"] == "F.R.I.D.A.Y."
    assert "brain" in data
    assert "voice" in data
    assert "tools" in data
    assert len(data["tools"]) >= 3
    assert "quick_commands" in data
    assert len(data["quick_commands"]) >= 5


def test_voice_switching():
    # 1. Switch to FRIDAY voice
    handled, reply = llm_manager.handle_voice_or_text_command("Switch to your Friday voice")
    assert handled is True
    assert "How do I sound, Boss?" in reply
    assert llm_manager.active_voice_name == "FRIDAY (Local Irish)"

    # 2. Switch voice to Zubar B
    handled, reply = llm_manager.handle_voice_or_text_command("Switch your voice to Zubar B")
    assert handled is True
    assert "How do I sound, sir? This is Zubar B." in reply
    assert llm_manager.active_voice_name == "Zubar B"

    # 3. Switch via API
    res = client.post("/api/voice/switch", json={"voice_name": "FRIDAY (Local Irish)", "engine": "voice_studio"})
    assert res.status_code == 200
    data = res.json()
    assert data["active_voice"] == "FRIDAY (Local Irish)"


@pytest.mark.anyio
async def test_openrouter_dynamic_discovery():
    models = await llm_manager.discover_openrouter_models()
    assert len(models) > 50
    free_models = [m for m in models if m.get("is_free")]
    assert len(free_models) >= 1
    # Check that providers endpoint includes models_details and free_models_count
    status = llm_manager.get_providers_status()
    openrouter_info = next(p for p in status["providers"] if p["id"] == "openrouter")
    assert openrouter_info["total_models_count"] > 50
    assert openrouter_info["free_models_count"] >= 1


@pytest.mark.anyio
async def test_nvidia_nim_dynamic_discovery():
    models = await llm_manager.discover_nvidia_nim_models()
    # Live NIM catalog size varies across key tiers/releases; verify substantial live catalog
    assert len(models) >= 25
    free_models = [m for m in models if m.get("is_free")]
    assert len(free_models) >= 25
    status = llm_manager.get_providers_status()
    nim_info = next(p for p in status["providers"] if p["id"] == "nvidia_nim")
    assert nim_info["total_models_count"] >= 25
    assert nim_info["free_models_count"] >= 25
    assert any("nemotron" in m["id"].lower() for m in nim_info["models_details"])


def test_mac_app_launcher():
    from src.tools.mac_apps import MacAppLauncher
    apps = MacAppLauncher.get_installed_apps()
    assert len(apps) > 5
    assert "safari" in apps or "canva" in apps or "notes" in apps

    # Test voice command "open Canva" or "open Notes"
    handled, reply = llm_manager.handle_voice_or_text_command("open Canva")
    assert handled is True
    assert "Canva" in reply

    # Test API endpoint
    res = client.get("/api/tools/mac_apps")
    assert res.status_code == 200
    data = res.json()
    assert "apps" in data
    assert len(data["apps"]) > 5


def test_second_brain_graph_endpoint():
    res = client.get("/api/second_brain/graph")
    assert res.status_code == 200
    data = res.json()
    assert "hubs" in data
    assert "nodes" in data
    assert "categories" in data
    assert len(data["hubs"]) >= 6
    assert len(data["nodes"]) > 50

    # Verify that real apps and files are present in the nodes
    app_nodes = [n for n in data["nodes"] if n.get("is_app")]
    assert len(app_nodes) > 10

    # Check for presence of category counts
    assert "Applications" in data["categories"]
    assert data["categories"]["Applications"] > 10


def test_mac_file_tools():
    # Test read_file on an existing project file
    test_file = str(Path.cwd() / "src" / "main.py")
    res = client.get(f"/api/tools/read_file?path={test_file}")
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert "FastAPI" in data["content"]

    # Test reveal_in_finder endpoint
    res = client.post("/api/tools/reveal_in_finder", json={"path": test_file})
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True


@pytest.mark.anyio
async def test_fallback_notification_only_once():
    # Save original
    orig_prov = llm_manager.active_provider_id
    orig_model = llm_manager.active_model

    async def mock_stream(*args, **kwargs):
        yield StreamChunk(content="Mocked response from fallback", finish_reason="stop")

    try:
        # Set primary to non-running local model to trigger fallback to OpenRouter
        llm_manager.fallback_chain = ["openrouter"]
        llm_manager.providers["openrouter"].default_models = ["cohere/north-mini-code:free"]
        llm_manager.set_active_provider_and_model("ollama_local", "non_existent_model_123")
        llm_manager._last_reported_brain = None

        with patch.object(llm_manager.providers["openrouter"], "chat_stream", side_effect=mock_stream):
            # First stream should announce fallback
            chunks1 = []
            async for chunk in llm_manager.chat_stream_with_fallback(
                messages=[ChatMessage(role="user", content="Hi")]
            ):
                chunks1.append(chunk.content)
            full_text1 = "".join(chunks1)
            # Switched text is present in the first fallback
            assert "[Switched to fallback brain" in full_text1

            # Second stream should NOT announce fallback because provider is already switched
            chunks2 = []
            async for chunk in llm_manager.chat_stream_with_fallback(
                messages=[ChatMessage(role="user", content="Next message")]
            ):
                chunks2.append(chunk.content)
            full_text2 = "".join(chunks2)
            assert "[Switched to fallback brain" not in full_text2
    finally:
        llm_manager.set_active_provider_and_model(orig_prov, orig_model)




