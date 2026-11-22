# ADR 0003: Vision, MCP Integration, Living 3D Memory & REFLEX Daemons

- **Status:** Accepted
- **Date:** 2026-11-22

## Context

To elevate F.R.I.D.A.Y from an interactive voice wrapper into a daily-driver macOS AI OS and portfolio showcase, it needs:
1. Screen (`EYES`), camera (`WATCH`), and active-app (`FOCUS`) perception without burning tokens on identical frames.
2. Standards-based extensibility via MCP alongside native macOS Accessibility automation.
3. Durable episodic/semantic memory synced into the Three.js 3D Second Brain.
4. Proactive background monitoring (`REFLEX`) and long-horizon autonomous missions (`MissionManager`) with hands-free Safety Gate approvals.

## Decision

1. **Change-Gated Vision (`src/vision/`)**: `ScreenVisionEngine` downscales via Pillow (`max_width=1280`, JPEG q=75) and deduplicates consecutive captures via 64-bit `dhash` Hamming distance; `WATCH` uses browser `getUserMedia` JPEG frames to avoid fragile native camera permission dialogs.
2. **Task-Owned MCP Lifecycle (`src/tools/mcp_client.py`)**: Each stdio MCP server is owned inside a dedicated `asyncio.Task` so AnyIO cancel scopes enter and exit cleanly in the same task across FastAPI lifespan reloads and pytest runs.
3. **Unified SQLite Store (`data/memory.db`)**: `MemoryStore` persists semantic memories and `MissionManager` task records; `SecondBrainIndexer` renders both memories and MCP servers in the 3D galaxy while `/ws/chat` emits live synaptic `tool_start` / `memory_added` pulse triggers.
4. **FOCUS-Aware `REFLEX` & Hands-Free Voice Approvals**: `ReflexDaemon` queues non-critical alerts when `FOCUS` mode is active and flushes upon exit; pending WebSocket Safety Gate prompts accept both HUD button clicks and spoken `"approve"` / `"deny"` phrases.

## Consequences

- Complete modular separation between perception (`src/vision/`), external protocols (`src/tools/mcp_client.py`), persistent memory (`src/second_brain/memory.py`), background reflexes (`src/reflex/`), and autonomous execution (`src/agent/`).
