"""
FRIDAY - Voice-Controlled Personal AI Assistant Server
FastAPI backend running on port 4719.
"""
import os
import json
import logging
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from src.llm import LLMManager, ChatMessage

# Configure structured logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("FRIDAY.Server")

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
WEB_DIR = PROJECT_ROOT / "src" / "web"

# Initialize LLM Manager
llm_manager = LLMManager(PROJECT_ROOT)

app = FastAPI(
    title="FRIDAY Assistant Server",
    description="Local voice-controlled AI assistant backend",
    version="1.0.0",
)

# CORS setup for local web access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Request & Response Models
class ChatRequest(BaseModel):
    message: str
    session_history: list[ChatMessage] = Field(default_factory=list)
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


@app.get("/api/system/state")
async def get_system_state():
    """100% dynamic state delivering all HUD labels, providers, tools, voices, and commands."""
    return llm_manager.get_system_state()


@app.get("/api/tools")
async def get_tools():
    """Dynamic list of tools and connection statuses."""
    return {"tools": llm_manager.get_system_state()["tools"]}


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
        return {"status": "success", "message": f"API key for {payload.provider_id} updated successfully."}
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

    # 2. Build conversation context
    messages = list(req.session_history)
    messages.append(ChatMessage(role="user", content=user_text))

    try:
        res = await llm_manager.chat_complete_with_fallback(
            messages=messages,
            temperature=req.temperature,
        )
        return ChatResponsePayload(
            reply=res.content,
            is_command=False,
            provider=res.provider,
            model=res.model,
            latency_ms=res.usage.latency_ms,
            prompt_tokens=res.usage.prompt_tokens,
            completion_tokens=res.usage.completion_tokens,
            estimated_cost_usd=res.usage.estimated_cost_usd,
        )
    except Exception as e:
        logger.error(f"Chat failed across fallback chain: {e}")
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


# Real-time WebSocket connection
@app.websocket("/ws/chat")
async def websocket_chat_endpoint(websocket: WebSocket):
    await websocket.accept()
    logger.info("WebSocket client connected to FRIDAY chat")
    try:
        # Send initial status with full dynamic state
        greeting = llm_manager.personality_config.get(
            "dialogue_responses", {}
        ).get("session_greeting", "Hello, sir.")
        await websocket.send_json({
            "type": "init",
            "greeting": greeting,
            "state": llm_manager.get_system_state(),
        })

        while True:
            raw_text = await websocket.receive_text()
            data = json.loads(raw_text)
            action = data.get("action", "chat")

            if action == "chat":
                user_msg = data.get("message", "").strip()
                if not user_msg:
                    continue

                # Check if it's a brain-switching or voice-switching command
                handled, reply = llm_manager.handle_voice_or_text_command(user_msg)
                if handled and reply is not None:
                    await websocket.send_json({
                        "type": "state_update",
                        "reply": reply,
                        "state": llm_manager.get_system_state(),
                    })
                    continue

                # Stream regular response
                history_data = data.get("session_history", [])
                history = [ChatMessage(**m) for m in history_data]
                history.append(ChatMessage(role="user", content=user_msg))

                current_p, current_m = llm_manager.get_active_provider()
                await websocket.send_json({
                    "type": "stream_start",
                    "provider": current_p.name,
                    "model": current_m,
                })

                async for chunk in llm_manager.chat_stream_with_fallback(messages=history):
                    await websocket.send_json({
                        "type": "stream_chunk",
                        "content": chunk.content,
                        "finish_reason": chunk.finish_reason,
                        "usage": chunk.usage.model_dump() if chunk.usage else None,
                    })

                await websocket.send_json({"type": "stream_end"})

            elif action == "switch_brain":
                pid = data.get("provider_id")
                model_name = data.get("model")
                msg = llm_manager.set_active_provider_and_model(pid, model_name)
                await websocket.send_json({
                    "type": "state_update",
                    "reply": msg,
                    "state": llm_manager.get_system_state(),
                })

            elif action == "switch_voice":
                voice_name = data.get("voice_name")
                engine = data.get("engine")
                llm_manager.set_active_voice(voice_name, engine)
                await websocket.send_json({
                    "type": "state_update",
                    "reply": f"Voice set to {voice_name}",
                    "state": llm_manager.get_system_state(),
                })

    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")


# Serve Frontend Web App
if WEB_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")

    @app.get("/")
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
