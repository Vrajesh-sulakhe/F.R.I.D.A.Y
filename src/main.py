"""
FRIDAY - Voice-Controlled Personal AI Assistant Server
FastAPI backend running on port 4719.
"""
import os
import re
import json
import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, status, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from src.llm import LLMManager, ChatMessage, ImageAttachment
from src.agent import AgentLoop, MissionManager, register_mission_tools
from src.tools import build_default_registry, MCPClientManager
from src.vision import ScreenVisionEngine, FocusMonitor
from src.second_brain import MemoryStore, register_memory_tools
from src.reflex import ReflexDaemon, load_reflex_rules

# Configure structured logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("FRIDAY.Server")

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
WEB_DIR = PROJECT_ROOT / "src" / "web"

# Initialize Core Subsystems
llm_manager = LLMManager(PROJECT_ROOT)
screen_engine = ScreenVisionEngine(max_frames=3)
focus_monitor = FocusMonitor()
memory_store = MemoryStore(PROJECT_ROOT / "data" / "memory.db")
tool_registry = build_default_registry(
    PROJECT_ROOT,
    screen_engine=screen_engine,
    focus_monitor=focus_monitor,
    router=llm_manager.router,
)
mcp_manager = MCPClientManager(PROJECT_ROOT / "config" / "mcp_servers.json", tool_registry)

active_ws_senders: set = set()
session_metrics: dict[str, float | int] = {
    "requests": 0,
    "prompt_tokens": 0,
    "completion_tokens": 0,
    "total_tokens": 0,
    "total_cost_usd": 0.0,
    "total_latency_ms": 0.0,
}


async def broadcast_ws_event(payload: dict) -> None:
    for sender in list(active_ws_senders):
        try:
            await sender(payload)
        except Exception:
            pass


def _on_memory_added(mem_obj: dict) -> None:
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(broadcast_ws_event({"type": "memory_added", "memory": mem_obj}))
    except RuntimeError:
        pass


register_memory_tools(tool_registry, memory_store, on_memory_added=_on_memory_added)


async def gather_ambient_context(query: str) -> str:
    parts: list[str] = []
    if focus_monitor.enabled:
        await focus_monitor.refresh_active_window()
        fctx = focus_monitor.format_prompt_context()
        if fctx:
            parts.append(fctx)
    mem_ctx = memory_store.format_prompt_memories(query, limit=3)
    if mem_ctx:
        parts.append(mem_ctx)
    return "\n\n".join(parts)


agent_loop = AgentLoop(
    llm_manager,
    llm_manager.router,
    tool_registry,
    context_provider=gather_ambient_context,
)
mission_manager = MissionManager(memory_store, agent_loop=agent_loop)
register_mission_tools(tool_registry, mission_manager)

reflex_daemon = ReflexDaemon(
    rules=load_reflex_rules(PROJECT_ROOT / "config" / "reflexes.yaml"),
    focus_monitor=focus_monitor,
    on_alert=broadcast_ws_event,
    project_root=PROJECT_ROOT,
    memory_store=memory_store,
)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    from src.voice.engine import warmup_stt
    asyncio.get_running_loop().run_in_executor(None, warmup_stt)
    try:
        await mcp_manager.reload()
    except Exception as e:
        logger.warning(f"Initial MCP discovery skipped: {e}")
    reflex_daemon.start()
    try:
        yield
    finally:
        await reflex_daemon.stop()
        await mcp_manager.close_all()


app = FastAPI(
    title="FRIDAY Assistant Server",
    description="Local voice-controlled AI assistant backend",
    version="2.0.0",
    lifespan=lifespan,
)

# CORS setup for local web access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_no_cache_headers(request: Request, call_next):
    """Prevent aggressive browser caching for local frontend files."""
    response = await call_next(request)
    if request.url.path.startswith("/static") or request.url.path == "/":
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response



# Request & Response Models
class ChatRequest(BaseModel):
    message: str
    session_history: list[ChatMessage] = Field(default_factory=list)
    images: list[ImageAttachment] = Field(default_factory=list)
    temperature: float = 0.7


class ChatResponsePayload(BaseModel):
    reply: str
    is_command: bool = False
    provider: str
    model: str
    latency_ms: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    estimated_cost_usd: float = 0.0


class ProviderSwitchRequest(BaseModel):
    provider_id: str
    model: str | None = None


class ProviderKeyUpdateRequest(BaseModel):
    provider_id: str
    api_key: str


class ProviderTestRequest(BaseModel):
    provider_id: str
    model: str | None = None


class VoiceSwitchRequest(BaseModel):
    voice_name: str
    engine: str | None = None


# REST API Endpoints
@app.get("/api/health")
async def health_check():
    """Health status and active brain info."""
    prov, model = llm_manager.get_active_provider()
    return {
        "status": "online",
        "system": "FRIDAY",
        "port": 4719,
        "active_provider": prov.provider_id,
        "active_provider_name": prov.name,
        "active_model": model,
        "active_voice": llm_manager.active_voice_name,
    }


def _build_full_system_state() -> dict:
    state = llm_manager.get_system_state()
    reqs = max(1, int(session_metrics["requests"]))
    state["telemetry"] = {
        **session_metrics,
        "avg_latency_ms": round(float(session_metrics["total_latency_ms"]) / reqs, 1) if session_metrics["requests"] else 0.0,
    }
    state["vision"] = {
        "eyes_enabled": screen_engine.enabled,
        "focus_enabled": focus_monitor.enabled,
        "active_app": focus_monitor._cached_context.app_name,
        "buffered_frames": len(screen_engine.recent_frames),
    }
    state["reflex"] = reflex_daemon.status()
    return state


@app.get("/api/system/state")
async def get_system_state():
    """100% dynamic state delivering all HUD labels, providers, tools, voices, telemetry, and vision."""
    return _build_full_system_state()


@app.get("/api/tools")
async def get_tools():
    """Dynamic list of HUD integrations and registered agent tools."""
    return {
        "tools": llm_manager.get_system_state()["tools"],
        "agent_tools": tool_registry.list_metadata(),
        "vision": {
            "eyes_enabled": screen_engine.enabled,
            "focus_enabled": focus_monitor.enabled,
            "buffered_frames": len(screen_engine.recent_frames),
        },
    }


@app.post("/api/vision/screen")
async def capture_screen_endpoint():
    """On-demand screen capture for EYES verification & HUD preview."""
    att = await screen_engine.capture_now(label="api_screen")
    if not att:
        raise HTTPException(status_code=503, detail=screen_engine.last_error or "Screen capture failed.")
    return {
        "success": True,
        "mime_type": att.mime_type,
        "size_b64": len(att.base64_data),
        "buffered_frames": len(screen_engine.recent_frames),
    }


class OpenAppRequest(BaseModel):
    app_name: str


class TTSRequest(BaseModel):
    text: str
    voice: str | None = None


class MemoryCreateRequest(BaseModel):
    topic: str
    content: str
    category: str = "Fact"
    importance: int = 3


class MissionCreateRequest(BaseModel):
    title: str
    goal: str
    interval_seconds: int = 0


@app.post("/api/stt")
async def speech_to_text(request: Request):
    """Transcribe an uploaded WAV utterance locally with Whisper."""
    import asyncio
    from src.voice.engine import transcribe_wav
    audio = await request.body()
    if len(audio) < 2000:
        return {"text": ""}
    try:
        text = await asyncio.get_event_loop().run_in_executor(None, transcribe_wav, audio)
        return {"text": text}
    except Exception as e:
        logger.error(f"STT failed: {e}")
        raise HTTPException(status_code=500, detail=f"Transcription failed: {e}")


@app.post("/api/tts")
async def text_to_speech(payload: TTSRequest):
    """Render FRIDAY's reply as a British butler voice WAV."""
    import asyncio
    from fastapi.responses import Response
    from src.voice.engine import synthesize_wav, TTS_VOICE
    try:
        wav = await asyncio.get_event_loop().run_in_executor(
            None, synthesize_wav, payload.text, payload.voice or TTS_VOICE
        )
    except Exception as e:
        logger.error(f"TTS failed: {e}")
        raise HTTPException(status_code=500, detail=f"Speech synthesis failed: {e}")
    if not wav:
        raise HTTPException(status_code=204, detail="Nothing to say")
    return Response(content=wav, media_type="audio/wav")


class PathActionRequest(BaseModel):
    path: str


class TeardownRequest(BaseModel):
    target: str
    type: str = "auto"


def extract_teardown_target(text: str) -> str | None:
    """Detect voice or text commands requesting reverse engineering or teardown."""
    import re
    clean = text.strip().rstrip("?!.")
    clean = re.sub(r"^(?:friday|jarvis)[,\s]+", "", clean, flags=re.IGNORECASE)
    m = re.search(
        r"(?:can you\s+)?(?:reverse engineer|teardown|deconstruct|take apart|inspect stack of)\s+(.+?)(?:\s+for me|\s+please)?$",
        clean,
        re.IGNORECASE,
    )
    if m:
        target = m.group(1).strip(" \"'`")
        if target:
            return target
    return None


@app.post("/api/tools/teardown")
async def run_teardown(payload: TeardownRequest):
    """Reverse engineer a website, macOS application bundle, codebase folder, or raw file."""
    from src.tools.rea import REATeardownEngine
    result = await REATeardownEngine.teardown(payload.target, mode=payload.type)
    return result


@app.post("/api/tools/open_app")
async def open_mac_app(payload: OpenAppRequest):
    """Open an installed macOS application."""
    from src.tools.mac_apps import MacAppLauncher
    success, resolved, msg = MacAppLauncher.open_app(payload.app_name)
    return {"success": success, "app_name": resolved, "message": msg}


@app.post("/api/tools/open_file")
async def open_local_file(payload: PathActionRequest):
    """Open any file or directory in its default macOS handler."""
    from src.tools.mac_apps import MacAppLauncher
    success, msg = MacAppLauncher.open_file_path(payload.path)
    return {"success": success, "path": payload.path, "message": msg}


@app.post("/api/tools/reveal_in_finder")
async def reveal_in_finder(payload: PathActionRequest):
    """Reveal any file, app, or directory in macOS Finder."""
    from src.tools.mac_apps import MacAppLauncher
    success, msg = MacAppLauncher.reveal_in_finder(payload.path)
    return {"success": success, "path": payload.path, "message": msg}


@app.get("/api/tools/read_file")
async def read_local_file(path: str):
    """Read local text content for preview or speech synthesis."""
    from src.tools.mac_apps import MacAppLauncher
    success, content = MacAppLauncher.read_file_preview(path)
    if not success:
        raise HTTPException(status_code=404, detail=content)
    return {"success": True, "path": path, "content": content}


@app.get("/api/tools/mac_apps")
async def get_mac_apps():
    """List detected macOS applications."""
    from src.tools.mac_apps import MacAppLauncher
    apps = MacAppLauncher.get_installed_apps()
    return {"apps": sorted(list(set(apps.values())))}


@app.get("/api/second_brain/graph")
async def get_second_brain_graph():
    """Scan and return real local macOS applications, files, memories, and MCP tools for the 3D galaxy."""
    from src.second_brain import SecondBrainIndexer
    return SecondBrainIndexer.scan_local_machine(memory_store=memory_store, mcp_manager=mcp_manager)


@app.get("/api/mcp/servers")
async def list_mcp_servers():
    return {"servers": mcp_manager.list_servers_status()}


@app.post("/api/mcp/reload")
async def reload_mcp_servers():
    statuses = await mcp_manager.reload()
    return {"status": "ok", "servers": statuses, "agent_tools": tool_registry.list_metadata()}


@app.get("/api/memories")
async def list_memories(q: str = "", limit: int = 30):
    items = memory_store.recall(q, limit=limit) if q.strip() else memory_store.list_recent(limit=limit)
    return {"memories": items}


@app.post("/api/memories")
async def create_memory(payload: MemoryCreateRequest):
    mid = memory_store.remember(
        topic=payload.topic,
        content=payload.content,
        category=payload.category,
        importance=payload.importance,
        source="manual",
    )
    mem_obj = {
        "id": mid,
        "topic": payload.topic,
        "category": payload.category,
        "content": payload.content,
        "importance": payload.importance,
    }
    await broadcast_ws_event({"type": "memory_added", "memory": mem_obj})
    return {"status": "created", "memory": mem_obj}


@app.delete("/api/memories/{memory_id}")
async def delete_memory(memory_id: str):
    return {"deleted": memory_store.forget(memory_id), "id": memory_id}


@app.get("/api/missions")
async def list_missions_endpoint():
    return {"missions": mission_manager.list_missions()}


@app.post("/api/missions")
async def create_mission_endpoint(payload: MissionCreateRequest):
    mission = mission_manager.create_mission(
        title=payload.title,
        goal=payload.goal,
        interval_seconds=payload.interval_seconds,
    )
    return {"status": "created", "mission": mission}


@app.post("/api/missions/{mission_id}/run")
async def run_mission_endpoint(mission_id: str):
    try:
        mission = await mission_manager.run_mission(mission_id, emit=broadcast_ws_event)
        return {"status": "ok", "mission": mission}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/api/missions/{mission_id}/cancel")
async def cancel_mission_endpoint(mission_id: str):
    return {"canceled": mission_manager.cancel_mission(mission_id), "id": mission_id}


@app.get("/api/reflex/status")
async def get_reflex_status():
    return reflex_daemon.status()


@app.post("/api/reflex/trigger/{rule_id}")
async def trigger_reflex_rule(rule_id: str):
    alerts = await reflex_daemon.trigger_rule(rule_id)
    return {"status": "triggered", "alerts": alerts}



@app.post("/api/voice/switch")
async def switch_voice(payload: VoiceSwitchRequest):
    """Dynamically switch voice profile (e.g. Jarvis, Zubar B, ElevenLabs)."""
    llm_manager.set_active_voice(payload.voice_name, payload.engine)
    return {
        "status": "success",
        "active_voice": llm_manager.active_voice_name,
        "voice_engine": llm_manager.active_voice_engine,
        "state": llm_manager.get_system_state(),
    }


@app.get("/api/session/fresh")
async def fresh_session():
    """Reset session and return standard Jarvis greeting and full dynamic state."""
    greeting = llm_manager.personality_config.get(
        "dialogue_responses", {}
    ).get("session_greeting", "Hello, sir.")
    return {
        "status": "fresh",
        "greeting": greeting,
        "state": llm_manager.get_system_state(),
    }


@app.get("/api/providers")
async def list_providers():
    """List all configured LLM providers, dynamically discovering local and cloud models."""
    await llm_manager.discover_ollama_models()
    await llm_manager.discover_openrouter_models()
    await llm_manager.discover_nvidia_nim_models()
    return llm_manager.get_providers_status()


@app.post("/api/providers/switch")
async def switch_provider(payload: ProviderSwitchRequest):
    """Switch the active LLM provider or model."""
    try:
        msg = llm_manager.set_active_provider_and_model(payload.provider_id, payload.model)
        prov, model = llm_manager.get_active_provider()
        return {
            "status": "success",
            "message": msg,
            "active_provider": prov.provider_id,
            "active_provider_name": prov.name,
            "active_model": model,
            "state": llm_manager.get_system_state(),
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/providers/key")
async def update_provider_key(payload: ProviderKeyUpdateRequest):
    """Safely update an API key in .env and reload provider with immediate model discovery."""
    try:
        llm_manager.update_provider_api_key(payload.provider_id, payload.api_key)
        if payload.provider_id == "openrouter":
            await llm_manager.discover_openrouter_models(force=True)
        elif payload.provider_id == "nvidia_nim":
            await llm_manager.discover_nvidia_nim_models(force=True)
        return {"status": "success", "message": f"API key for {payload.provider_id} updated successfully and model catalog synced."}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/providers/test")
async def test_provider_connection(payload: ProviderTestRequest):
    """Test connection to a provider."""
    provider = llm_manager.providers.get(payload.provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail=f"Provider {payload.provider_id} not found.")

    success, message = await provider.test_connection(payload.model)
    return {
        "provider_id": payload.provider_id,
        "success": success,
        "message": message,
    }


@app.post("/api/chat", response_model=ChatResponsePayload)
async def chat_endpoint(req: ChatRequest):
    """Non-streaming text chat endpoint."""
    user_text = req.message.strip()
    if not user_text:
        raise HTTPException(status_code=400, detail="Empty message received.")

    # 1. Check for brain-switching or persona voice/text commands
    handled, reply = llm_manager.handle_voice_or_text_command(user_text)
    if handled and reply is not None:
        prov, model = llm_manager.get_active_provider()
        return ChatResponsePayload(
            reply=reply,
            is_command=True,
            provider=prov.name,
            model=model,
            latency_ms=1.0,
            prompt_tokens=len(user_text) // 4,
            completion_tokens=len(reply) // 4,
            estimated_cost_usd=0.0,
        )

    # 1b. Check for REA reverse engineering / teardown commands
    td_target = extract_teardown_target(user_text)
    if td_target:
        from src.tools.rea import REATeardownEngine
        res = await REATeardownEngine.teardown(td_target)
        td_reply = res.get("spoken_summary") or f"Teardown of {td_target} complete, sir."
        return ChatResponsePayload(
            reply=td_reply,
            is_command=True,
            provider="REA (Reverse Engineer Anything)",
            model="Safe-Tracer",
            latency_ms=10.0,
            prompt_tokens=len(user_text) // 4,
            completion_tokens=len(td_reply) // 4,
            estimated_cost_usd=0.0,
        )

    # 2. Build conversation context and run agentic loop (SAFE tools auto-run; CONFIRM gated)
    messages = list(req.session_history)
    messages.append(ChatMessage(role="user", content=user_text, images=req.images))

    try:
        res = await agent_loop.run(
            messages=messages,
            temperature=req.temperature,
        )
        return ChatResponsePayload(
            reply=res.reply,
            is_command=False,
            provider=res.provider,
            model=res.model,
            latency_ms=res.usage.latency_ms,
            prompt_tokens=res.usage.prompt_tokens,
            completion_tokens=res.usage.completion_tokens,
            estimated_cost_usd=res.usage.estimated_cost_usd,
        )
    except Exception as e:
        logger.error(f"Chat failed across agent loop: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"I apologize, sir, but all brain systems failed to respond: {str(e)}",
        )


@app.post("/api/chat/stream")
async def chat_stream_endpoint(req: ChatRequest):
    """Server-Sent Events (SSE) streaming endpoint."""
    user_text = req.message.strip()
    if not user_text:
        raise HTTPException(status_code=400, detail="Empty message received.")

    async def event_generator() -> AsyncIterator[str]:
        # Check command first
        handled, reply = llm_manager.handle_voice_or_text_command(user_text)
        if handled and reply is not None:
            prov, model = llm_manager.get_active_provider()
            yield f"data: {json.dumps({'content': reply, 'is_command': True, 'provider': prov.name, 'model': model, 'finish_reason': 'stop'})}\n\n"
            yield "data: [DONE]\n\n"
            return

        # Check for REA teardown command
        td_target = extract_teardown_target(user_text)
        if td_target:
            from src.tools.rea import REATeardownEngine
            res = await REATeardownEngine.teardown(td_target)
            td_reply = res.get("spoken_summary") or f"Teardown of {td_target} complete, sir."
            yield f"data: {json.dumps({'content': td_reply, 'is_command': True, 'dossier': res.get('dossier'), 'provider': 'REA', 'model': 'Safe-Tracer', 'finish_reason': 'stop'})}\n\n"
            yield "data: [DONE]\n\n"
            return

        messages = list(req.session_history)
        messages.append(ChatMessage(role="user", content=user_text))

        prov, model = llm_manager.get_active_provider()
        try:
            async for chunk in llm_manager.chat_stream_with_fallback(
                messages=messages,
                temperature=req.temperature,
            ):
                payload = {
                    "content": chunk.content,
                    "is_command": False,
                    "provider": prov.name,
                    "model": model,
                    "finish_reason": chunk.finish_reason,
                }
                if chunk.usage:
                    payload["usage"] = chunk.usage.model_dump()
                yield f"data: {json.dumps(payload)}\n\n"

            yield "data: [DONE]\n\n"
        except Exception as e:
            err_payload = {
                "content": f"\n\nCognitive failure, sir: {str(e)}",
                "finish_reason": "error",
            }
            yield f"data: {json.dumps(err_payload)}\n\n"
            yield "data: [DONE]\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


_VOICE_APPROVE = {"approve", "approved", "yes", "confirm", "go ahead", "proceed", "do it", "allow"}
_VOICE_DENY = {"deny", "denied", "no", "cancel", "stop", "reject", "abort", "decline"}


def _record_usage(usage) -> None:
    session_metrics["requests"] += 1
    if not usage:
        return
    session_metrics["prompt_tokens"] += int(usage.prompt_tokens or 0)
    session_metrics["completion_tokens"] += int(usage.completion_tokens or 0)
    session_metrics["total_tokens"] += int(usage.total_tokens or 0)
    session_metrics["total_cost_usd"] = round(
        float(session_metrics["total_cost_usd"]) + float(usage.estimated_cost_usd or 0.0),
        6,
    )
    session_metrics["total_latency_ms"] += float(usage.latency_ms or 0.0)


# Real-time WebSocket connection
@app.websocket("/ws/chat")
async def websocket_chat_endpoint(websocket: WebSocket):
    await websocket.accept()
    logger.info("WebSocket client connected to FRIDAY chat")
    ws_send_lock = asyncio.Lock()
    pending_approvals: dict[str, asyncio.Future[bool]] = {}
    active_agent_task: asyncio.Task | None = None

    async def send_ws_json(payload: dict):
        async with ws_send_lock:
            await websocket.send_json(payload)

    active_ws_senders.add(send_ws_json)

    async def ws_approval_handler(request_id: str, tool_name: str, arguments: dict, risk_tier: str) -> bool:
        fut: asyncio.Future[bool] = asyncio.get_running_loop().create_future()
        pending_approvals[request_id] = fut
        await send_ws_json({
            "type": "tool_approval_request",
            "request_id": request_id,
            "tool_name": tool_name,
            "arguments": arguments,
            "risk_tier": risk_tier,
        })
        try:
            return await asyncio.wait_for(fut, timeout=60.0)
        except asyncio.TimeoutError:
            return False
        except asyncio.CancelledError:
            return False
        finally:
            pending_approvals.pop(request_id, None)

    async def run_agent_chat(history: list[ChatMessage]):
        try:
            res = await agent_loop.run(
                messages=history,
                emit=send_ws_json,
                approval_handler=ws_approval_handler,
            )
            _record_usage(res.usage)
            await send_ws_json({
                "type": "stream_end",
                "state": _build_full_system_state(),
            })
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"Agent WebSocket execution failed: {e}")
            await send_ws_json({
                "type": "stream_chunk",
                "content": f"\n\nI apologize, sir, an execution error occurred: {str(e)}",
                "finish_reason": "error",
            })
            await send_ws_json({
                "type": "stream_end",
                "state": _build_full_system_state(),
            })

    try:
        # Send initial status with full dynamic state
        greeting = llm_manager.personality_config.get(
            "dialogue_responses", {}
        ).get("session_greeting", "Hello, sir.")
        await send_ws_json({
            "type": "init",
            "greeting": greeting,
            "state": _build_full_system_state(),
        })

        while True:
            raw_text = await websocket.receive_text()
            data = json.loads(raw_text)
            action = data.get("action", "chat")

            if action == "tool_approval_response":
                req_id = data.get("request_id", "")
                approved = bool(data.get("approved", False))
                fut = pending_approvals.pop(req_id, None)
                if fut and not fut.done():
                    fut.set_result(approved)
                continue

            if action == "teardown":
                target = data.get("target", "igloo.inc")
                mode = data.get("type", "auto")
                from src.tools.rea import REATeardownEngine

                async def ws_progress(step, cur, tot):
                    try:
                        await send_ws_json({
                            "type": "teardown_progress",
                            "step": step,
                            "stage": cur,
                            "total": tot,
                            "target": target,
                        })
                    except Exception:
                        pass

                res = await REATeardownEngine.teardown(target, mode=mode, progress_cb=ws_progress)
                await send_ws_json({
                    "type": "teardown_complete",
                    "target": target,
                    "target_type": res.get("type"),
                    "title": res.get("title"),
                    "reply": res.get("spoken_summary"),
                    "dossier": res.get("dossier"),
                    "snapshot_url": res.get("snapshot_url"),
                    "tech_stack": res.get("tech_stack"),
                    "state": _build_full_system_state(),
                })
                continue

            elif action == "chat":
                user_msg = data.get("message", "").strip()
                raw_images = data.get("images") or []
                if not user_msg and not raw_images:
                    continue

                # Hands-free Voice/Text Safety Gate confirmation when approval is pending
                if pending_approvals and user_msg and not raw_images:
                    clean_voice = re.sub(r"^(?:friday|jarvis)[,\s]+", "", user_msg.lower()).strip(" .!?")
                    if clean_voice in _VOICE_APPROVE or clean_voice in _VOICE_DENY:
                        decision = clean_voice in _VOICE_APPROVE
                        req_id = next(iter(pending_approvals.keys()))
                        fut = pending_approvals.pop(req_id, None)
                        if fut and not fut.done():
                            fut.set_result(decision)
                        await send_ws_json({
                            "type": "approval_voice_ack",
                            "request_id": req_id,
                            "approved": decision,
                        })
                        continue

                # Check if it's a brain-switching or voice-switching command
                if user_msg and not raw_images:
                    handled, reply = llm_manager.handle_voice_or_text_command(user_msg)
                    if handled and reply is not None:
                        await send_ws_json({
                            "type": "state_update",
                            "reply": reply,
                            "state": _build_full_system_state(),
                        })
                        continue

                    # Check for REA Teardown fast-path command
                    td_target = extract_teardown_target(user_msg)
                    if td_target:
                        from src.tools.rea import REATeardownEngine

                        async def ws_progress(step, cur, tot):
                            try:
                                await send_ws_json({
                                    "type": "teardown_progress",
                                    "step": step,
                                    "stage": cur,
                                    "total": tot,
                                    "target": td_target,
                                })
                            except Exception:
                                pass

                        res = await REATeardownEngine.teardown(td_target, progress_cb=ws_progress)
                        await send_ws_json({
                            "type": "teardown_complete",
                            "target": td_target,
                            "target_type": res.get("type"),
                            "title": res.get("title"),
                            "reply": res.get("spoken_summary"),
                            "dossier": res.get("dossier"),
                            "snapshot_url": res.get("snapshot_url"),
                            "tech_stack": res.get("tech_stack"),
                            "state": _build_full_system_state(),
                        })
                        continue

                history_data = data.get("session_history", [])
                history = [ChatMessage(**m) for m in history_data]
                attachments = [ImageAttachment(**img) for img in raw_images]

                # When EYES is enabled on the HUD, attach current compressed screen frame cleanly
                if screen_engine.enabled:
                    screen_att = await screen_engine.capture_now(label="eyes_screen")
                    if screen_att:
                        attachments.append(screen_att)

                history.append(ChatMessage(role="user", content=user_msg, images=attachments))

                if active_agent_task and not active_agent_task.done():
                    active_agent_task.cancel()
                active_agent_task = asyncio.create_task(run_agent_chat(history))

            elif action == "toggle_state":
                tname = str(data.get("toggle", "")).lower()
                enabled = bool(data.get("enabled", False))
                if tname == "eyes":
                    screen_engine.enabled = enabled
                    if enabled:
                        await screen_engine.capture_now(label="eyes_warmup")
                elif tname == "focus":
                    focus_monitor.set_focus_mode(enabled)
                    if enabled:
                        await focus_monitor.refresh_active_window()
                    else:
                        await reflex_daemon.flush_queued()
                await send_ws_json({
                    "type": "toggle_ack",
                    "toggle": tname,
                    "enabled": enabled,
                    "state": _build_full_system_state(),
                })

            elif action == "switch_brain":
                pid = data.get("provider_id")
                model_name = data.get("model")
                msg = llm_manager.set_active_provider_and_model(pid, model_name)
                await send_ws_json({
                    "type": "state_update",
                    "reply": msg,
                    "state": _build_full_system_state(),
                })

            elif action == "switch_voice":
                voice_name = data.get("voice_name")
                engine = data.get("engine")
                llm_manager.set_active_voice(voice_name, engine)
                await send_ws_json({
                    "type": "state_update",
                    "reply": f"Voice set to {voice_name}",
                    "state": _build_full_system_state(),
                })

    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        active_ws_senders.discard(send_ws_json)
        for req_id, fut in list(pending_approvals.items()):
            if not fut.done():
                fut.set_result(False)
        pending_approvals.clear()
        if active_agent_task and not active_agent_task.done():
            active_agent_task.cancel()


# Serve Frontend Web App
if WEB_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")

    @app.api_route("/", methods=["GET", "HEAD"])
    async def serve_index():
        index_file = WEB_DIR / "index.html"
        if index_file.exists():
            return FileResponse(index_file)
        return {"message": "FRIDAY server running. Frontend index.html not yet initialized."}


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "4719"))
    host = os.getenv("HOST", "0.0.0.0")
    uvicorn.run("src.main:app", host=host, port=port, reload=True)
