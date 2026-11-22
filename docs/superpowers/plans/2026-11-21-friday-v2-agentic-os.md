# F.R.I.D.A.Y v2.0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans or superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade F.R.I.D.A.Y into a multimodal, capability-aware, MCP-ready autonomous macOS AI OS supporting both frontier models and free/local BYOK models across 5 incremental phases.

**Architecture:** Spine-first modular design: Phase 1 introduces multimodal `ChatMessage` image attachments, `ModelRouter` (capability tagging + vision delegation), and an async `AgentLoop` + `ToolRegistry` + WebSocket `SafetyGate`. Subsequent phases plug into this spine: Phase 2 (`EYES`/`WATCH`/`FOCUS`), Phase 3 (`MCP Client` + macOS Computer Use), Phase 4 (SQLite Memory + Live 3D Brain Pulses), Phase 5 (`REFLEX` Daemons).

**Tech Stack:** Python 3.12, FastAPI, WebSockets, Pydantic v2, httpx, Anthropic SDK, Faster-Whisper, Vanilla JS + Three.js (`r128`), pytest + anyio.

**Spec:** [implementation_plan.md](file:///Users/vrajeshsulakhe/.gemini/antigravity/brain/0e1f26a0-cdcd-43c5-aeb4-b157565b4b5e/implementation_plan.md) and [ADR 0001](../../adr/0001-capability-aware-byok-routing.md), [ADR 0002](../../adr/0002-agent-loop-and-safety-gate.md).

## Global Constraints

- Port `4719` FastAPI + WebSocket backend; static frontend served from `src/web/`.
- Preserve existing API contracts (`/api/health`, `/api/system/state`, `/api/providers*`, `/api/chat*`, `/ws/chat`, `/api/stt`, `/api/tts`, `/api/second_brain/graph`).
- Preserve fast-path brain/voice switching commands verified in `tests/test_phase1.py`.
- Zero hardcoded paid-only assumptions: every feature works with free/local BYOK keys where a capable model is configured, or degrades gracefully with an informative in-character explanation.
- Every risky/mutating tool enforces the `CONFIRM` or `DANGEROUS` human-in-the-loop gate before side effects occur.

## Review Focus

1. **Text-only active model receives image (`EYES` / `WATCH`)**: Must automatically delegate visual inspection to a configured VLM (or fail gracefully if zero vision models are configured), never crash by sending `image_url` to DeepSeek R1 or text-only Ollama.
2. **Model rejects or ignores native JSON `tools`**: Must fall back cleanly to ReAct structured text parsing without raising 400/422 errors or infinite loops.
3. **WebSocket disconnects while awaiting `SafetyGate` approval**: Pending `asyncio.Future` must clean up on disconnect/timeout so the backend never leaks tasks or executes orphaned commands later.
4. **Path traversal or runaway shell command in agent tools**: Workspace/filesystem tools must normalize paths, refuse reading secrets (`.env`), and force `CONFIRM`/`DANGEROUS` approval with preview.
5. **Infinite tool loops**: `AgentLoop` must strictly cap iterations (`max_steps=8`) and return a clean partial summary if the cap is reached.

---

### Task 1 (Phase 1A): Multimodal Base Models & Provider Image Formatting

**Files:**
- Modify: `src/llm/base.py`
- Modify: `src/llm/openai_compatible.py`
- Modify: `src/llm/anthropic_provider.py`
- Test: `tests/test_multimodal_providers.py`

**Interfaces:**
- Produces: `ImageAttachment(base64_data: str, mime_type: str = "image/jpeg", label: str | None = None)`, `ModelCapabilities(vision: bool, tools: bool, reasoning: bool, is_free: bool, tier: str)`, `ChatMessage.images: list[ImageAttachment]`.

- [x] Phase 0 docs (`README.md`, ADRs, `task_plan.md`, `findings.md`, `progress.md`) created
- [ ] Write failing unit tests for `ImageAttachment` formatting in `OpenAICompatibleProvider._format_messages` and `AnthropicProvider._convert_messages` (`tests/test_multimodal_providers.py`)
- [ ] Run pytest and verify RED
- [ ] Extend `src/llm/base.py`, `src/llm/openai_compatible.py`, `src/llm/anthropic_provider.py`
- [ ] Run pytest and verify GREEN

---

### Task 2 (Phase 1B): Capability-Aware Model Router (`BYOK` Frontier + Free/Local)

**Files:**
- Create: `src/llm/router.py`
- Modify: `src/llm/__init__.py`
- Modify: `src/llm/manager.py` (wire capability metadata into `models_details` and expose `router`)
- Test: `tests/test_router.py`

**Interfaces:**
- Consumes: `LLMManager.providers`, `ModelCapabilities`
- Produces: `infer_model_capabilities(provider_id: str, model_id: str, raw_meta: dict | None = None) -> ModelCapabilities`, `ModelRouter.resolve_model(role: str = "chat") -> tuple[LLMProvider, str, ModelCapabilities] | None`

- [ ] Write failing unit tests covering: capability inference across Claude/Gemini/Llama-Vision/DeepSeek-R1/Qwen/LLaVA, Frontier vs Free/Local `vision` resolution when active model is text-only (`deepseek-r1`), and `None` return when no configured provider supports `vision` (`tests/test_router.py`)
- [ ] Run pytest and verify RED
- [ ] Implement `src/llm/router.py` and wire into `src/llm/__init__.py` & `src/llm/manager.py`
- [ ] Run pytest and verify GREEN

---

### Task 3 (Phase 1C): Unified ToolRegistry, Core Local Tools & Safety Gate

**Files:**
- Create: `src/agent/__init__.py`
- Create: `src/agent/registry.py`
- Create: `src/tools/workspace.py`
- Modify: `src/tools/__init__.py`
- Test: `tests/test_registry_tools.py`

**Interfaces:**
- Produces: `ToolRiskTier` (`SAFE`, `CONFIRM`, `DANGEROUS`), `RegisteredTool`, `ToolExecutionResult`, `ToolRegistry` (`register`, `list_definitions`, `execute`, `get_tier`)

- [ ] Write failing tests covering: tool registration & OpenAI/Anthropic `ToolDefinition` export, `workspace` `SAFE` tools (`list_directory`, `read_file_snippet`, `search_files`, `system_status`) refusing `.env` reads, `CONFIRM`/`DANGEROUS` metadata on `run_shell` & `write_file_content`, and wrapping `MacAppLauncher` + `REATeardownEngine`
- [ ] Run pytest and verify RED
- [ ] Implement `src/agent/registry.py` and `src/tools/workspace.py`
- [ ] Run pytest and verify GREEN

---

### Task 4 (Phase 1D): Async ReAct AgentLoop + Interactive Safety Gate + HUD Trace

**Files:**
- Create: `src/agent/loop.py`
- Modify: `src/main.py` (`/ws/chat` + `/api/chat` integration, `tool_approval_response` WebSocket action)
- Modify: `src/web/js/app.js` (render live agent step trace & Approve/Deny card in HUD stream)
- Modify: `src/web/css/style.css` (styling for tactical step cards & approval controls)
- Test: `tests/test_agent_loop.py`

**Interfaces:**
- Consumes: `ModelRouter`, `ToolRegistry`, `LLMManager`
- Produces: `AgentLoop.run(...)` emitting events (`agent_plan`, `tool_start`, `tool_approval_request`, `tool_result`, `stream_start`, `stream_chunk`, `stream_end`) and handling approval timeouts/denials safely.

- [ ] Write failing tests covering: multi-step `SAFE` tool call -> observation -> final reply, `CONFIRM` tool awaiting approval (Approve succeeds, Deny returns refusal observation cleanly without executing tool), ReAct text-fallback JSON parser when native `tools` are unsupported, and `max_steps` cap enforcement
- [ ] Run pytest and verify RED
- [ ] Implement `src/agent/loop.py`, wire into `src/main.py`, update `src/web/js/app.js` & `src/web/css/style.css`
- [ ] Run pytest and verify GREEN (both new tests and full existing suite)

---

### Backlog Phases (After Phase 1 Verification)
- **Phase 2 (`EYES`, `WATCH`, `FOCUS`)**: `src/vision/screen.py`, `src/vision/focus.py`, WebSocket toggle + camera snapshot ingestion (`Pillow` dependency).
- **Phase 3 (`MCP Client` + macOS Computer Use)**: `src/tools/mcp_client.py`, `config/mcp_servers.json`, `src/tools/mac_computer_use.py` (`mcp` SDK).
- **Phase 4 (Living 3D Second Brain Memory)**: `src/second_brain/memory.py` (`data/memory.db`), live `graph_pulse` / `graph_node_add` in `src/web/js/graph.js`.
- **Phase 5 (`REFLEX` Proactive Daemons)**: `src/reflex/daemon.py`, `config/reflexes.yaml`, HUD notification queue with `FOCUS` suppression.
