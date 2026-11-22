"""Tests for multimodal image attachments and model capability models."""
from src.llm.base import ChatMessage, ImageAttachment, ModelCapabilities
from src.llm.openai_compatible import OpenAICompatibleProvider
from src.llm.anthropic_provider import AnthropicProvider


def test_model_capabilities_defaults():
    caps = ModelCapabilities()
    assert caps.vision is False
    assert caps.tools is False
    assert caps.reasoning is False
    assert caps.is_free is False
    assert caps.tier == "balanced"


def test_openai_compatible_formats_multimodal_and_text_messages():
    provider = OpenAICompatibleProvider(
        provider_id="openrouter",
        name="OpenRouter",
        base_url="https://openrouter.ai/api/v1",
        api_key="test-key",
        default_models=["google/gemini-2.0-flash-001"],
    )
    img = ImageAttachment(base64_data="ZmFrZWJ5dGVz", mime_type="image/png", label="screen")
    messages = [
        ChatMessage(role="system", content="You are FRIDAY."),
        ChatMessage(role="user", content="Plain question"),
        ChatMessage(role="user", content="What is on screen?", images=[img]),
    ]

    formatted = provider._format_messages(messages)

    assert formatted[0] == {"role": "system", "content": "You are FRIDAY."}
    # Plain text-only user messages remain strings for strict local endpoint compatibility
    assert formatted[1] == {"role": "user", "content": "Plain question"}
    assert isinstance(formatted[2]["content"], list)
    assert formatted[2]["content"][0] == {"type": "text", "text": "What is on screen?"}
    assert formatted[2]["content"][1] == {
        "type": "image_url",
        "image_url": {"url": "data:image/png;base64,ZmFrZWJ5dGVz"},
    }


def test_anthropic_formats_multimodal_messages():
    provider = AnthropicProvider(
        provider_id="anthropic",
        name="Anthropic",
        base_url="https://api.anthropic.com/v1",
        api_key="test-key",
        default_models=["claude-3-5-sonnet-latest"],
    )
    img = ImageAttachment(base64_data="aGVsbG8=", mime_type="image/jpeg")
    messages = [
        ChatMessage(role="system", content="System instructions."),
        ChatMessage(role="user", content="Analyze this frame.", images=[img]),
    ]

    system_prompt, converted = provider._convert_messages(messages)

    assert system_prompt == "System instructions."
    assert len(converted) == 1
    assert converted[0]["role"] == "user"
    blocks = converted[0]["content"]
    assert isinstance(blocks, list)
    assert blocks[0] == {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": "image/jpeg",
            "data": "aGVsbG8=",
        },
    }
    assert blocks[1] == {"type": "text", "text": "Analyze this frame."}
