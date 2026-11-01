"""
Phase 1 automated tests: LLM multi-provider management, brain switching,
dialogue persona, and API server endpoints.
"""
import pytest
from pathlib import Path
from fastapi.testclient import TestClient

from src.main import app, llm_manager
from src.llm import ChatMessage, TokenTracker

client = TestClient(app)


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
    # 1. Switch to local voice
    handled, reply = llm_manager.handle_voice_or_text_command("Switch to your local voice")
    assert handled is True
    assert "How do I sound, sir? This is my local voice." in reply
    assert llm_manager.active_voice_name == "Jarvis"

    # 2. Switch voice to Zubar B
    handled, reply = llm_manager.handle_voice_or_text_command("Switch your voice to Zubar B")
    assert handled is True
    assert "How do I sound, sir? This is Zubar B." in reply
    assert llm_manager.active_voice_name == "Zubar B"

    # 3. Switch via API
    res = client.post("/api/voice/switch", json={"voice_name": "Jarvis (Local)", "engine": "voice_studio"})
    assert res.status_code == 200
    data = res.json()
    assert data["active_voice"] == "Jarvis (Local)"


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


