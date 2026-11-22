"""
Capability-aware BYOK Model Router for F.R.I.D.A.Y.
Adapts seamlessly across frontier cloud keys (Anthropic, OpenRouter) and
free/local endpoints (NVIDIA NIM free, OpenRouter :free, Ollama).
"""
import logging
from typing import TYPE_CHECKING, Any

from .base import ChatMessage, ImageAttachment, LLMProvider, ModelCapabilities

if TYPE_CHECKING:
    from .manager import LLMManager

logger = logging.getLogger("FRIDAY.ModelRouter")

_VISION_PATTERNS = (
    "claude-3-5",
    "claude-3-7",
    "claude-sonnet-4",
    "claude-opus-4",
    "claude-4",
    "gpt-4o",
    "gpt-4.1",
    "gpt-5",
    "gemini-1.5",
    "gemini-2",
    "gemini-3",
    "vision",
    "-vl",
    "vl-",
    "llava",
    "minicpm-v",
    "pixtral",
    "nemotron-parse",
    "minimax-m3",
    "qwen2.5vl",
    "qwen3-vl",
    "gemma-3-12b",
    "gemma-4",
)

_NON_CHAT_PATTERNS = ("embed", "rerank", "guard", "safety", "whisper", "tts")

_NO_TOOLS_PATTERNS = ("deepseek-r1", "llava", "nemotron-parse", "embed", "rerank")

_REASONING_PATTERNS = (
    "deepseek-r1",
    "o1",
    "o3",
    "o4",
    "thinking",
    "reasoner",
    "claude-3-7",
    "nemotron-3.5",
    "qwq",
)

_FAST_PATTERNS = (
    "haiku",
    "flash",
    "mini",
    "bolt",
    "lightning",
    ":3b",
    ":7b",
    ":9b",
    "-4b",
    "-8b",
)

_FRONTIER_PATTERNS = (
    "claude-3-7",
    "claude-3-5-sonnet",
    "claude-sonnet-4",
    "claude-opus-4",
    "gpt-4o",
    "gpt-4.1",
    "gpt-5",
    "gemini-2.5-pro",
    "gemini-3",
    "mistral-large",
    "deepseek-r1",
    "llama-3.2-90b",
    "llama-3.3-70b",
)

_TIER_SCORE = {"frontier": 3, "balanced": 2, "fast": 1}


def infer_model_capabilities(
    provider_id: str,
    model_id: str,
    raw_meta: dict[str, Any] | None = None,
) -> ModelCapabilities:
    """Infer vision, native tool-calling, reasoning, cost, and speed tier for a model."""
    mid = (model_id or "").lower()
    meta = raw_meta or {}

    is_free = (
        "local" in provider_id.lower()
        or "ollama" in provider_id.lower()
        or provider_id == "nvidia_nim"
        or ":free" in mid
        or bool(meta.get("is_free"))
    )

    if any(p in mid for p in _NON_CHAT_PATTERNS):
        return ModelCapabilities(vision=False, tools=False, reasoning=False, is_free=is_free, tier="fast")

    # Vision check: explicit metadata first, then architecture input_modalities, then known VLM IDs
    vision: bool
    if isinstance(meta.get("vision"), bool):
        vision = meta["vision"]
    elif isinstance(meta.get("architecture"), dict) and isinstance(
        meta["architecture"].get("input_modalities"), list
    ):
        modalities = [str(m).lower() for m in meta["architecture"]["input_modalities"]]
        vision = "image" in modalities
    else:
        vision = any(p in mid for p in _VISION_PATTERNS)

    # Native tool calling check
    supported_params = meta.get("supported_parameters")
    if isinstance(supported_params, list):
        tools = "tools" in [str(p).lower() for p in supported_params]
    elif any(p in mid for p in _NO_TOOLS_PATTERNS):
        tools = False
    elif provider_id == "anthropic":
        tools = True
    elif provider_id == "openrouter":
        tools = True
    elif provider_id == "nvidia_nim":
        tools = any(
            k in mid for k in ("nemotron-3.5", "mistral-large", "llama-3.3", "minimax-m3", "gemma", "phi")
        )
    else:
        # Local Ollama modern tool-capable families
        tools = any(k in mid for k in ("qwen3", "qwen2.5", "llama3.2", "llama3.3", "gemma4", "mistral"))

    reasoning = any(p in mid for p in _REASONING_PATTERNS)

    if any(p in mid for p in _FAST_PATTERNS):
        tier = "fast"
    elif any(p in mid for p in _FRONTIER_PATTERNS):
        tier = "frontier"
    else:
        tier = "balanced"

    return ModelCapabilities(
        vision=vision,
        tools=tools,
        reasoning=reasoning,
        is_free=is_free,
        tier=tier,
    )


class ModelRouter:
    """Resolves the right configured model for chat, vision, or fast background tasks."""

    PROVIDER_PRIORITY = ["anthropic", "openrouter", "nvidia_nim", "custom_1", "ollama_local"]

    def __init__(self, manager: "LLMManager"):
        self.manager = manager

    def is_provider_configured(self, provider_id: str) -> bool:
        prov = self.manager.providers.get(provider_id)
        if not prov:
            return False
        if "ollama" in provider_id.lower() or "local" in provider_id.lower():
            return bool(prov.default_models)
        return bool(prov.api_key)

    def get_model_capabilities(self, prov: LLMProvider, model_id: str) -> ModelCapabilities:
        details = getattr(prov, "models_details", None) or []
        for item in details:
            if item.get("id") == model_id:
                caps = item.get("capabilities")
                if isinstance(caps, ModelCapabilities):
                    return caps
                if isinstance(caps, dict):
                    return ModelCapabilities(**caps)
                return infer_model_capabilities(prov.provider_id, model_id, item)
        return infer_model_capabilities(prov.provider_id, model_id)

    def resolve_model(self, role: str = "chat") -> tuple[LLMProvider, str, ModelCapabilities] | None:
        """
        Select the best configured (provider, model, capabilities) for a task role.
        Roles: "chat" (user's active model with fallback), "vision" (multimodal VLM), "fast" (low-latency).
        """
        active_prov, active_model = self.manager.get_active_provider()
        active_configured = self.is_provider_configured(active_prov.provider_id)

        if role == "chat":
            if active_configured and active_model:
                return active_prov, active_model, self.get_model_capabilities(active_prov, active_model)
            for pid in list(self.manager.fallback_chain) + list(self.manager.providers.keys()):
                if self.is_provider_configured(pid):
                    p = self.manager.providers[pid]
                    if p.default_models:
                        m = p.default_models[0]
                        return p, m, self.get_model_capabilities(p, m)
            return None

        if role == "vision":
            if active_configured and active_model:
                active_caps = self.get_model_capabilities(active_prov, active_model)
                if active_caps.vision:
                    return active_prov, active_model, active_caps

            candidates: list[tuple[int, int, int, LLMProvider, str, ModelCapabilities]] = []
            search_order = [active_prov.provider_id] + [
                pid for pid in self.PROVIDER_PRIORITY if pid != active_prov.provider_id
            ] + [pid for pid in self.manager.providers.keys() if pid not in self.PROVIDER_PRIORITY]

            for prov_rank, pid in enumerate(dict.fromkeys(search_order)):
                if not self.is_provider_configured(pid):
                    continue
                prov = self.manager.providers[pid]
                for mid in prov.default_models:
                    caps = self.get_model_capabilities(prov, mid)
                    if not caps.vision:
                        continue
                    same_provider_bonus = 1 if pid == active_prov.provider_id else 0
                    paid_bonus = 0 if caps.is_free else 1
                    score = (
                        _TIER_SCORE.get(caps.tier, 1) * 10
                        + paid_bonus * 5
                        + same_provider_bonus * 3
                        - prov_rank
                    )
                    candidates.append((score, same_provider_bonus, -prov_rank, prov, mid, caps))

            if not candidates:
                return None
            candidates.sort(key=lambda x: (x[0], x[1], x[2]), reverse=True)
            _, _, _, best_prov, best_model, best_caps = candidates[0]
            return best_prov, best_model, best_caps

        if role == "fast":
            if active_configured and active_model:
                active_caps = self.get_model_capabilities(active_prov, active_model)
                if active_caps.tier == "fast":
                    return active_prov, active_model, active_caps
            for pid in [active_prov.provider_id] + self.PROVIDER_PRIORITY:
                if not self.is_provider_configured(pid):
                    continue
                prov = self.manager.providers[pid]
                for mid in prov.default_models:
                    caps = self.get_model_capabilities(prov, mid)
                    if caps.tier == "fast" and caps.tools:
                        return prov, mid, caps
            return self.resolve_model("chat")

        raise ValueError(f"Unknown router role: {role}")

    async def inspect_images(
        self,
        images: list[ImageAttachment],
        prompt: str = "Describe clearly what is visible in these images, focusing on any text, UI, errors, or objects.",
    ) -> tuple[str, str, str] | None:
        """Delegate visual inspection to the best configured vision model."""
        if not images:
            return None
        resolved = self.resolve_model("vision")
        if not resolved:
            return None
        prov, model_id, _ = resolved
        try:
            res = await prov.chat_complete(
                messages=[
                    ChatMessage(role="system", content="You are F.R.I.D.A.Y.'s visual perception module. Be accurate and concise."),
                    ChatMessage(role="user", content=prompt, images=images),
                ],
                model=model_id,
                temperature=0.2,
                max_tokens=900,
            )
            return res.content.strip(), prov.name, model_id
        except Exception as e:
            logger.warning(f"Vision inspection failed on {prov.name}/{model_id}: {e}")
            return None
