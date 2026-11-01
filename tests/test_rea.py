"""
Automated tests for REA (Reverse Engineer Anything) integration in FRIDAY.
Tests web teardown, macOS app teardown, codebase analysis, file inspection,
REST API endpoints, and WebSocket real-time progress streaming.
"""
import pytest
from fastapi.testclient import TestClient

from src.main import app, extract_teardown_target
from src.tools.rea import REATeardownEngine

client = TestClient(app)


def test_extract_teardown_target():
    """Verify natural language voice and text intent parsing for reverse engineering."""
    cases = [
        ("FRIDAY, can you reverse engineer igloo.inc for me?", "igloo.inc"),
        ("Jarvis, teardown Calculator please", "Calculator"),
        ("can you reverse engineer apple.com for me", "apple.com"),
        ("reverse engineer https://github.com", "https://github.com"),
        ("teardown /System/Applications/Calculator.app", "/System/Applications/Calculator.app"),
        ("reverse engineer src", "src"),
        ("teardown src/main.py", "src/main.py"),
        ("deconstruct Safari", "Safari"),
    ]
    for prompt, expected in cases:
        extracted = extract_teardown_target(prompt)
        assert extracted == expected, f"Failed on prompt: {prompt}. Got {extracted}, expected {expected}"


def test_classify_target():
    """Verify target classification (web, app, codebase, file)."""
    assert REATeardownEngine.classify_target("https://igloo.inc") == "web"
    assert REATeardownEngine.classify_target("igloo.inc") == "web"
    assert REATeardownEngine.classify_target("apple.com") == "web"
    assert REATeardownEngine.classify_target("Calculator") == "app"
    assert REATeardownEngine.classify_target("src") == "codebase"
    assert REATeardownEngine.classify_target("src/main.py") == "file"


@pytest.mark.anyio
async def test_teardown_app_calculator():
    """Verify macOS application bundle inspection on Calculator."""
    progress_steps = []

    async def cb(step, cur, tot):
        progress_steps.append((step, cur, tot))

    res = await REATeardownEngine.teardown("Calculator", progress_cb=cb)
    assert res["status"] == "success"
    assert res["type"] == "app"
    assert res["bundle_id"] == "com.apple.calculator"
    assert "sir" in res["spoken_summary"]
    assert "SwiftUI" in res["dossier"] or "AppKit" in res["dossier"]
    assert len(progress_steps) == 5
    assert progress_steps[0][0] == "REA is inspecting the application bundle"
    assert progress_steps[4][0] == "writing the teardown"


@pytest.mark.anyio
async def test_teardown_codebase_src():
    """Verify codebase folder inspection and AST symbol mapping on src/."""
    progress_steps = []

    async def cb(step, cur, tot):
        progress_steps.append((step, cur, tot))

    res = await REATeardownEngine.teardown("src", progress_cb=cb)
    assert res["status"] == "success"
    assert res["type"] == "codebase"
    assert "sir" in res["spoken_summary"]
    assert "Language Breakdown" in res["dossier"]
    assert len(progress_steps) == 5
    assert progress_steps[0][0] == "REA is indexing directory tree"
    assert progress_steps[4][0] == "writing the teardown"


@pytest.mark.anyio
async def test_teardown_single_file():
    """Verify single file format detection and structural parsing."""
    progress_steps = []

    async def cb(step, cur, tot):
        progress_steps.append((step, cur, tot))

    res = await REATeardownEngine.teardown("src/main.py", progress_cb=cb)
    assert res["status"] == "success"
    assert res["type"] == "file"
    assert "sir" in res["spoken_summary"]
    assert "SHA-256 Digest" in res["dossier"]
    assert len(progress_steps) == 5
    assert progress_steps[0][0] == "REA is analyzing file magic and format"
    assert progress_steps[4][0] == "writing the teardown"


def test_api_teardown_endpoint():
    """Verify REST API POST /api/tools/teardown."""
    res = client.post("/api/tools/teardown", json={"target": "Calculator", "type": "app"})
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "success"
    assert data["type"] == "app"
    assert "spoken_summary" in data
    assert "dossier" in data


def test_chat_endpoint_with_teardown_command():
    """Verify chat endpoint intercepts teardown command without cloud billing."""
    res = client.post("/api/chat", json={"message": "FRIDAY, can you reverse engineer Calculator for me?"})
    assert res.status_code == 200
    data = res.json()
    assert data["is_command"] is True
    assert "REA" in data["provider"]
    assert "Calculator" in data["reply"]
    assert "sir" in data["reply"]


def test_websocket_teardown_streaming():
    """Verify WebSocket streaming of sub-step ticker updates and complete dossier."""
    with client.websocket_connect("/ws/chat") as ws:
        # Initial handshake message
        init_msg = ws.receive_json()
        assert init_msg["type"] == "init"

        # Trigger teardown over WebSocket
        ws.send_json({"action": "teardown", "target": "Calculator"})

        # Collect progress events
        progress_events = []
        complete_event = None

        while True:
            msg = ws.receive_json()
            if msg["type"] == "teardown_progress":
                progress_events.append(msg)
            elif msg["type"] == "teardown_complete":
                complete_event = msg
                break

        assert len(progress_events) == 5
        assert progress_events[0]["step"] == "REA is inspecting the application bundle"
        assert progress_events[1]["step"] == "reading Info.plist and entitlements"
        assert progress_events[2]["step"] == "analyzing binary architectures and frameworks"
        assert progress_events[3]["step"] == "disassembling symbol table and linked libraries"
        assert progress_events[4]["step"] == "writing the teardown"

        assert complete_event is not None
        assert complete_event["target"] == "Calculator"
        assert "sir" in complete_event["reply"]
        assert "dossier" in complete_event
        assert "com.apple.calculator" in complete_event["dossier"]

