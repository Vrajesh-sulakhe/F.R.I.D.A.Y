# ADR 0002: Custom ReAct Agent Loop & Three-Tier Safety Gate

- **Status:** Accepted
- **Date:** 2026-11-21

## Context

F.R.I.D.A.Y. previously relied on brittle regex routing in `src/main.py` and `LLMManager.handle_voice_or_text_command` for opening Mac apps and running REA teardowns, while `ToolDefinition` and `ToolFunctionCall` in `src/llm/base.py` were unused in the main chat flow. Adding shell execution, filesystem writes, MCP servers, and macOS Computer Use requires multi-step tool chaining, live HUD visibility, and strict safety controls.

## Decision

1. **Custom Async ReAct Loop (`src/agent/loop.py`)**: Keep the loop lightweight and dependency-free inside `src/agent/` (max 8 iterations per turn) rather than importing LangGraph/CrewAI, preserving sub-second streaming and direct WebSocket event emission (`agent_plan`, `tool_start`, `tool_approval_request`, `tool_result`, `stream_chunk`, `stream_end`).
2. **Preserve Zero-Latency Fast Paths**: Brain-switching, voice-switching, and explicit `open <app>` / `teardown <target>` fast paths remain intact while complex natural-language requests automatically engage the agentic loop.
3. **Three-Tier Tool Risk Model (`ToolRiskTier`)**:
   - `SAFE`: Auto-executed (`read_file`, `list_dir`, `search_files`, `list_mac_apps`, `rea_teardown`, `capture_screen`, `get_active_window`, `memory_recall`).
   - `CONFIRM`: Suspends the loop over `asyncio.Future` and emits `tool_approval_request` to the HUD (Approve / Deny button or voice command) before running (`run_shell`, `write_file`, `open_app`, UI click/type).
   - `DANGEROUS`: Requires explicit confirmation with full command/path/diff preview.

## Consequences

- Real-time transparent agent trace in the HUD.
- Safe autonomy on the user's personal Mac with zero blind destructive execution.
- Easy registration for both native tools (`src/tools/`) and dynamic MCP tools in Phase 3.
