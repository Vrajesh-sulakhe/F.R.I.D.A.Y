"""
Token usage tracking, latency monitoring, and cost calculation per LLM request.
"""
import time
import logging
from typing import Any
from .base import TokenUsage

logger = logging.getLogger("FRIDAY.LLMTracker")

# Approximate pricing per 1 million tokens (USD): [prompt_price, completion_price]
PRICING_PER_MILLION: dict[str, tuple[float, float]] = {
    # Anthropic
    "claude-3-7-sonnet": (3.00, 15.00),
    "claude-3-5-sonnet": (3.00, 15.00),
    "claude-3-5-haiku": (0.80, 4.00),
    # OpenRouter common
    "anthropic/claude-3.7-sonnet": (3.00, 15.00),
    "anthropic/claude-3.5-sonnet": (3.00, 15.00),
    "meta-llama/llama-3.3-70b-instruct": (0.35, 0.40),
    "google/gemini-2.0-flash-001": (0.10, 0.40),
    "deepseek/deepseek-r1": (0.55, 2.19),
    "deepseek/deepseek-chat": (0.14, 0.28),
    # NVIDIA NIM common
    "meta/llama-3.3-70b-instruct": (0.35, 0.40),
    "deepseek-ai/deepseek-r1": (0.55, 2.19),
    "mistralai/mistral-large-2-instruct": (2.00, 6.00),
}


class TokenTracker:
    @staticmethod
    def calculate_cost(provider_id: str, model: str, prompt_tokens: int, completion_tokens: int) -> float:
        """Calculate estimated cost. Local models and free-tier are always $0.00."""
        if "local" in provider_id.lower() or "ollama" in provider_id.lower():
            return 0.0

        model_key = model.lower()
        pricing = None

        for key, price_tuple in PRICING_PER_MILLION.items():
            if key in model_key:
                pricing = price_tuple
                break

        if not pricing:
            # Default fallback for unknown commercial models ($1.00 / $3.00)
            pricing = (1.00, 3.00)

        prompt_cost = (prompt_tokens / 1_000_000.0) * pricing[0]
        completion_cost = (completion_tokens / 1_000_000.0) * pricing[1]
        return round(prompt_cost + completion_cost, 6)

    @staticmethod
    def log_request(
        provider: str,
        model: str,
        latency_ms: float,
        prompt_tokens: int,
        completion_tokens: int,
        estimated_cost: float,
    ) -> None:
        """Structured logging of request performance and economics."""
        logger.info(
            f"[LLM Request] Provider: {provider} | Model: {model} | Latency: {latency_ms:.1f}ms | "
            f"Prompt: {prompt_tokens} tokens | Completion: {completion_tokens} tokens | "
            f"Cost: ${estimated_cost:.6f}"
        )


class RequestTimer:
    def __init__(self):
        self.start_time: float = 0.0

    def __enter__(self):
        self.start_time = time.perf_counter()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        pass

    @property
    def elapsed_ms(self) -> float:
        return (time.perf_counter() - self.start_time) * 1000.0
