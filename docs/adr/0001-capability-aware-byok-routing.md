# ADR 0001: Capability-Aware BYOK Model Routing & Vision Delegation

- **Status:** Accepted
- **Date:** 2026-11-21

## Context

F.R.I.D.A.Y. supports users across two distinct runtime profiles depending strictly on which API keys they enter:
1. **Frontier keys** (Anthropic, paid OpenRouter GPT/Claude/Gemini) — native vision, reliable parallel JSON tool calling, high reasoning bandwidth.
2. **Zero-cost cloud or local weights** (NVIDIA NIM free endpoints, OpenRouter `:free`, local Ollama) — often text-only (e.g. `deepseek-ai/deepseek-r1`, `qwen3.5:9b`) or lacking native OpenAI function-calling support on some endpoints.

Hardcoding frontier models locks out free-tier users; naively sending images or `tools=[]` to text-only models breaks runtime requests.

## Decision

1. **Per-model capability metadata (`ModelCapabilities`)**: Every discovered model carries `{vision, tools, reasoning, is_free, tier}` inferred from OpenRouter architecture metadata and curated NIM/Anthropic/Ollama patterns.
2. **Automatic Vision Delegation (`ModelRouter.resolve_vision_model`)**: If the user's active model lacks `vision=True` and a turn contains image attachments (e.g. `EYES` screen capture or `WATCH` camera frame), F.R.I.D.A.Y. automatically selects the highest-tier *configured* vision-capable model available from the user's keys (Priority: configured Frontier VLM → configured Free Cloud VLM like NIM/OpenRouter `:free` → local Ollama VLM like `qwen2.5vl`/`llava`), obtains a crisp visual analysis, and feeds it into the active brain.
3. **Structured ReAct Text Fallback**: When an active provider/model has `tools=False` or rejects native `tools` payloads, `AgentLoop` seamlessly falls back to an inline JSON/XML action block prompt parser.

## Consequences

- Zero configuration friction: entering any single key (even NVIDIA NIM or OpenRouter free-only) or running local Ollama keeps all agentic and vision workflows functional where any vision model exists.
- Clean separation between discovery (`LLMManager`) and task-role selection (`ModelRouter`).
