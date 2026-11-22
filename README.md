# F.R.I.D.A.Y. — Voice-Controlled Multimodal macOS AI OS

> **Female Replacement Intelligent Digital Assistant Youth** — A local-first, Iron Man-inspired tactical macOS AI OS featuring Faster-Whisper STT, local Irish female / neural voice synthesis, a live Three.js 3D Second Brain galaxy, and a capability-aware agentic core.

## Vision

F.R.I.D.A.Y. combines **daily-driver macOS utility** with a **high-craft Stark HUD interface**. Whether you bring a frontier API key (Anthropic Claude, OpenRouter frontier models), zero-cost cloud endpoints (NVIDIA NIM free endpoints, OpenRouter `:free`), or fully offline local weights (Ollama), F.R.I.D.A.Y. automatically adapts routing, vision delegation, and multi-step tool execution to whatever keys you have configured.

## Core Architecture

- **BYOK Capability-Aware Model Router (`src/llm/`)**: Dynamically discovers models from OpenRouter, NVIDIA NIM, Anthropic, and Ollama; classifies capabilities (`vision`, `tools`, `reasoning`, `is_free`, `tier`); and delegates vision or reasoning tasks across configured providers.
- **ReAct Agent Loop & Safety Gate (`src/agent/`)**: Multi-step Plan → Tool Call → Observe → Verify execution loop with risk tiers (`SAFE`, `CONFIRM`, `DANGEROUS`), streaming live execution traces and interactive Approve/Deny cards in the HUD.
- **Multimodal Perception (`src/vision/`, Phase 2)**: `EYES` (on-demand & change-gated macOS screen awareness), `WATCH` (browser `getUserMedia` camera snapshots), and `FOCUS` (active macOS window awareness & notification gating).
- **Universal Tooling (`src/tools/`)**: Native macOS app/file control, shell/filesystem tools, REA (Reverse Engineer Anything) teardown engine, plus Model Context Protocol (`MCP`) client & macOS Accessibility Computer Use (Phase 3).
- **Living 3D Second Brain & Proactive Daemons (`src/second_brain/`, `src/reflex/`)**: Interactive Three.js 3D galaxy graph that indexes local apps/projects/memory and pulses live during tool execution, paired with background `REFLEX` watchers.

## Architecture Decision Records

- [ADR 0001: Capability-Aware BYOK Routing & Vision Delegation](docs/adr/0001-capability-aware-byok-routing.md)
- [ADR 0002: Custom ReAct Agent Loop & Three-Tier Safety Gate](docs/adr/0002-agent-loop-and-safety-gate.md)
- [ADR 0003: Vision, MCP Integration, Living 3D Memory & REFLEX Daemons](docs/adr/0003-vision-mcp-memory-reflex-architecture.md)

## Quickstart (Localhost)

```bash
# 1. Activate environment
source .venv/bin/activate

# 2. Configure API keys in .env (or via the UI Config -> Brain Engines modal)
#    Supports OPENROUTER_API_KEY, NVIDIA_API_KEY, ANTHROPIC_API_KEY, ELEVENLABS_API_KEY,
#    plus offline local Ollama (http://localhost:11434)
cp .env.example .env

# 3. Start F.R.I.D.A.Y. on port 4719
python -m uvicorn src.main:app --host 0.0.0.0 --port 4719 --reload
```

Open [http://localhost:4719](http://localhost:4719) in Brave, Chrome, or Safari.

## Running Tests

```bash
.venv/bin/python -m pytest -v
```
