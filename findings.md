# Findings & Architectural Notes

## Codebase Audit (2026-11-21)
- **Existing LLM adapters are ready for tools**: Both `src/llm/openai_compatible.py` and `src/llm/anthropic_provider.py` already accept `tools: list[ToolDefinition]` and accumulate `tool_calls` cleanly in both `chat_complete` and `chat_stream`. However, `src/main.py` never passes `tools` and never executes multi-step loops.
- **Image support missing**: `ChatMessage.content` is currently `str | None = None`, with no `images` field or multipart formatting in OpenAI (`image_url`) or Anthropic (`type: "image"`).
- **Dynamic model catalogs**:
  - `LLMManager.discover_openrouter_models()` fetches OpenRouter `/api/v1/models` with `pricing`; `:free` or zero-pricing models are tagged `is_free`. OpenRouter payloads also include `architecture.input_modalities` and `supported_parameters`, which we can leverage for accurate `vision` and `tools` capability inference.
  - `LLMManager.discover_nvidia_nim_models()` queries `integrate.api.nvidia.com/v1/models`. Baseline run returned 33 filtered models (causing pre-existing `tests/test_phase1.py::test_nvidia_nim_dynamic_discovery` asserting `>= 50` to fail).
- **HUD & Frontend**:
  - `src/web/index.html` already includes interactive `.toggle-switch-btn` controls for `eyes`, `watch`, `holo`, `focus`, and a status pill for `REFLEX`.
  - `src/web/js/app.js` handles WebSocket `/ws/chat` messages (`init`, `teardown_progress`, `teardown_complete`, `state_update`, `stream_start`, `stream_chunk`, `stream_end`) and `galaxy.highlightByQuery()`. Note a subtle existing bug in `app.js:1153`: teardown checks `this.ws` while `connectWebSocket()` stores `this.socket`.
- **Environment Dependencies**:
  - `Pillow` and `mcp` are not installed in `.venv` yet; Phase 1 uses stdlib + existing packages (`pydantic`, `httpx`, `anthropic`, `fastapi`). `Pillow` will be needed in Phase 2 (`EYES`) and `mcp` in Phase 3.
- **Test Side Effect**:
  - `tests/test_phase1.py` mutates `llm_manager` directly and writes `config/settings.json` on `set_active_provider_and_model` calls. Tests for new modules should avoid clobbering `config/settings.json` (use `tmp_path` or restore config).
