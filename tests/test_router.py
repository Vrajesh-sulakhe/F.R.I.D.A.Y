"""Tests for capability inference and BYOK ModelRouter (frontier + free/local)."""
import pytest
from pathlib import Path

from src.llm.base import ModelCapabilities
from src.llm.openai_compatible import OpenAICompatibleProvider
from src.llm.anthropic_provider import AnthropicProvider
from src.llm.router import infer_model_capabilities, ModelRouter


class StubManager:
    """Isolated stub mimicking LLMManager without touching real config/settings.json."""

    def __init__(self, providers, active_provider_id, active_model, fallback_chain=None):
        self.providers = providers
        self.active_provider_id = active_provider_id
        self.active_model = active_model
        self.fallback_chain = fallback_chain or []

    def get_active_provider(self):
        return self.providers[self.active_provider_id], self.active_model


def test_capability_inference_for_frontier_free_and_local_models():
    claude_caps = infer_model_capabilities("anthropic", "claude-3-5-sonnet-latest")
    assert claude_caps.vision is True
    assert claude_caps.tools is True
    assert claude_caps.is_free is False
    assert claude_caps.tier == "frontier"

    nim_r1_caps = infer_model_capabilities("nvidia_nim", "deepseek-ai/deepseek-r1")
    assert nim_r1_caps.vision is False
    assert nim_r1_caps.reasoning is True
    assert nim_r1_caps.is_free is True

    nim_vlm_caps = infer_model_capabilities("nvidia_nim", "meta/llama-3.2-90b-vision-instruct")
    assert nim_vlm_caps.vision is True
    assert nim_vlm_caps.is_free is True

    or_meta_caps = infer_model_capabilities(
        "openrouter",
        "google/gemini-2.0-flash-exp:free",
        raw_meta={
            "is_free": True,
            "architecture": {"input_modalities": ["text", "image"]},
            "supported_parameters": ["tools", "temperature"],
        },
    )
    assert or_meta_caps.vision is True
    assert or_meta_caps.tools is True
    assert or_meta_caps.is_free is True

    ollama_qwen_caps = infer_model_capabilities("ollama_local", "qwen3.5:9b")
    assert ollama_qwen_caps.vision is False
    assert ollama_qwen_caps.tools is True
    assert ollama_qwen_caps.is_free is True


def test_router_prefers_active_model_if_vision_capable():
    anthropic = AnthropicProvider("anthropic", "Anthropic", "https://api.anthropic.com/v1", "sk-ant", ["claude-3-5-sonnet-latest"])
    nim = OpenAICompatibleProvider("nvidia_nim", "NVIDIA NIM", "https://integrate.api.nvidia.com/v1", "nvapi-123", ["meta/llama-3.2-90b-vision-instruct"])
    mgr = StubManager({"anthropic": anthropic, "nvidia_nim": nim}, "anthropic", "claude-3-5-sonnet-latest")

    router = ModelRouter(mgr)
    prov, model, caps = router.resolve_model("vision")
    assert prov.provider_id == "anthropic"
    assert model == "claude-3-5-sonnet-latest"
    assert caps.vision is True


def test_router_delegates_vision_from_text_only_model_to_configured_free_vlm():
    # User's active brain is text-only deepseek-r1 on NIM; no Anthropic key; NIM key is present with Llama Vision
    anthropic = AnthropicProvider("anthropic", "Anthropic", "https://api.anthropic.com/v1", None, ["claude-3-5-sonnet-latest"])
    nim = OpenAICompatibleProvider(
        "nvidia_nim",
        "NVIDIA NIM",
        "https://integrate.api.nvidia.com/v1",
        "nvapi-test",
        ["deepseek-ai/deepseek-r1", "meta/llama-3.2-90b-vision-instruct"],
    )
    mgr = StubManager({"anthropic": anthropic, "nvidia_nim": nim}, "nvidia_nim", "deepseek-ai/deepseek-r1")

    router = ModelRouter(mgr)
    resolved = router.resolve_model("vision")
    assert resolved is not None
    prov, model, caps = resolved
    assert prov.provider_id == "nvidia_nim"
    assert model == "meta/llama-3.2-90b-vision-instruct"
    assert caps.vision is True
    assert caps.is_free is True


def test_router_returns_none_when_no_configured_vision_model_exists():
    # Only text-only Ollama running, no cloud API keys
    anthropic = AnthropicProvider("anthropic", "Anthropic", "https://api.anthropic.com/v1", None, ["claude-3-5-sonnet-latest"])
    ollama = OpenAICompatibleProvider("ollama_local", "Ollama", "http://localhost:11434/v1", None, ["qwen3.5:9b"])
    mgr = StubManager({"anthropic": anthropic, "ollama_local": ollama}, "ollama_local", "qwen3.5:9b")

    router = ModelRouter(mgr)
    assert router.resolve_model("vision") is None
