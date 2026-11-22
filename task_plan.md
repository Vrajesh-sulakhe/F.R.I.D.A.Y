# F.R.I.D.A.Y v2.0 — Master Task Plan

**Goal:** Turn F.R.I.D.A.Y into a multimodal, capability-aware, MCP-ready autonomous macOS AI OS supporting both Frontier BYOK keys and Free/Local models (Phases 0–7).

## Phases

- [x] **Phase 0: Docs & Working Memory Setup**
  - Created `README.md`, ADRs, `task_plan.md`, `findings.md`, `progress.md`, and detailed plan.
- [x] **Phase 1: Multimodal Core + BYOK Router + ReAct Agent Loop + Safety Gate**
  - Tasks 1A–1D implemented & verified (`38 passed`, only pre-existing live NIM count assertion `33 >= 50` failing).
- [x] **Phase 2: Vision & Perception (`EYES`, `WATCH`, `FOCUS`)**
  - [x] `src/vision/screen.py` (screencapture + Pillow resize + dhash dedup + 3-frame buffer)
  - [x] `src/vision/focus.py` (macOS active window detector + quiet mode gating)
  - [x] WebSocket `toggle_state` (`eyes`, `watch`, `focus`), `capture_screen` & `get_active_window` tools, browser `WATCH` PiP camera frame capture
- [x] **Phase 3: Universal Tooling — MCP Client + macOS Computer Use**
  - [x] `src/tools/mcp_client.py` + `config/mcp_servers.json`
  - [x] `src/tools/mac_computer_use.py` (clipboard, Accessibility UI tree reader, guarded UI actions)
- [x] **Phase 4: Living 3D Second Brain & Persistent Semantic Memory**
  - [x] `src/second_brain/memory.py` (`data/memory.db` SQLite store + recall/remember tools)
  - [x] Live Three.js `graph_pulse` & `graph_node_add` in `indexer.py` + `graph.js`
- [x] **Phase 5: Proactive Autonomous Daemons (`REFLEX`)**
  - [x] `src/reflex/daemon.py` + `config/reflexes.yaml` + FastAPI lifespan handler + HUD `REFLEX` alerts (respecting `FOCUS`)
- [x] **Phase 6: Long-Horizon Mission Control & Voice-Driven Approval**
  - [x] `src/agent/missions.py` (persisted multi-step missions, scheduled intervals, checkpointing)
  - [x] Hands-free Voice/Text Safety Gate approval (`"Approve"` / `"Deny"`)
- [x] **Phase 7: Portfolio Polish, Capability Badges, Telemetry & End-to-End Hardening**
  - [x] Model capability badges (`👁` Vision, `🔧` Tools, `🧠` Reasoning, `🎁` Free) + MCP & Memory & Mission HUD panels + Cost/Latency Telemetry
  - [x] Full regression + boundary test verification (`52 passed`, only pre-existing live NIM `33 >= 50` failure) + live server on `:4719`

## Errors Encountered
| Error | Attempt | Resolution |
| :--- | :--- | :--- |
| `test_nvidia_nim_dynamic_discovery` pre-existing failure (`33 >= 50`) | Baseline check | Live NIM `/models` currently returns 33 filtered models vs hardcoded 50 assertion in `tests/test_phase1.py:159`. |
| `test_websocket_agent_approval_flow` hung before timeout | Phase 1D run | Unanchored `re.search` in `manager.py` hijacked `"Open Notes..."` prompt; fixed by anchoring fast-path regex to short single-intent app launches. |
