"""
Unified LLM Manager handling providers, runtime model/brain switching,
fallback chains, and in-character banter.
"""
import os
import json
import re
import logging
from pathlib import Path
from typing import AsyncIterator, Any
import yaml
from dotenv import load_dotenv, set_key

from .base import (
    LLMProvider,
    ChatMessage,
    ChatResponse,
    StreamChunk,
    ToolDefinition,
)
from .openai_compatible import OpenAICompatibleProvider
from .anthropic_provider import AnthropicProvider
from .router import ModelRouter, infer_model_capabilities

logger = logging.getLogger("FRIDAY.LLMManager")


class LLMManager:
    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.config_dir = project_root / "config"
        self.env_path = project_root / ".env"
        self.providers_yaml_path = self.config_dir / "providers.yaml"
        self.personality_yaml_path = self.config_dir / "personality.yaml"
        self.settings_json_path = self.config_dir / "settings.json"

        # Load environment variables
        load_dotenv(dotenv_path=self.env_path, override=True)

        self.providers: dict[str, LLMProvider] = {}
        self.fallback_chain: list[str] = []
        self.active_provider_id: str = "ollama_local"
        self.active_model: str = "qwen3.5:9b"
        self.personality_config: dict[str, Any] = {}
        self.raw_providers_config: dict[str, Any] = {}
        self.active_voice_name: str = "FRIDAY (Local Irish)"
        self.active_voice_engine: str = "voice_studio"
        self.available_voices: list[str] = ["FRIDAY (Local Irish)", "FRIDAY (Moira)", "Samantha (Local)", "Jarvis (Daniel)"]

        self.load_configurations()
        self.router = ModelRouter(self)

    def load_configurations(self) -> None:
        """Load and parse providers.yaml, personality.yaml, and settings.json."""
        # 1. Personality config
        if self.personality_yaml_path.exists():
            with open(self.personality_yaml_path, "r", encoding="utf-8") as f:
                self.personality_config = yaml.safe_load(f) or {}

        # 2. Providers config
        if self.providers_yaml_path.exists():
            with open(self.providers_yaml_path, "r", encoding="utf-8") as f:
                self.raw_providers_config = yaml.safe_load(f) or {}
                self.fallback_chain = self.raw_providers_config.get("fallback_chain", [])
                self._initialize_providers()

        # 3. Settings config
        if self.settings_json_path.exists():
            with open(self.settings_json_path, "r", encoding="utf-8") as f:
                settings = json.load(f) or {}
                self.active_provider_id = settings.get("active_provider", self.active_provider_id)
                self.active_model = settings.get("active_model", self.active_model)
                self.active_voice_name = settings.get("active_voice", self.active_voice_name)
                self.active_voice_engine = settings.get("voice_engine", self.active_voice_engine)
                if "fallback_chain" in settings and settings["fallback_chain"]:
                    self.fallback_chain = settings["fallback_chain"]

    def _initialize_providers(self) -> None:
        """Instantiate LLMProvider instances based on providers.yaml."""
        prov_defs = self.raw_providers_config.get("providers", {})
        self.providers.clear()

        for prov_id, pdata in prov_defs.items():
            ptype = pdata.get("type", "openai_compatible")
            name = pdata.get("name", prov_id.title())
            base_url = pdata.get("base_url", "")
            key_env = pdata.get("api_key_env")
            models = pdata.get("models", [])

            api_key = os.getenv(key_env) if key_env else None

            # For Ollama, dynamically verify host from env if present
            if prov_id == "ollama_local":
                ollama_env_host = os.getenv("OLLAMA_HOST")
                if ollama_env_host:
                    base_url = f"{ollama_env_host.rstrip('/')}/v1"

            if ptype == "anthropic":
                self.providers[prov_id] = AnthropicProvider(
                    provider_id=prov_id,
                    name=name,
                    base_url=base_url,
                    api_key=api_key,
                    default_models=models,
                )
            else:
                self.providers[prov_id] = OpenAICompatibleProvider(
                    provider_id=prov_id,
                    name=name,
                    base_url=base_url,
                    api_key=api_key,
                    default_models=models,
                )

    def save_settings(self) -> None:
        """Persist current active provider, model, and voice to settings.json."""
        current_data = {}
        if self.settings_json_path.exists():
            try:
                with open(self.settings_json_path, "r", encoding="utf-8") as f:
                    current_data = json.load(f)
            except Exception:
                current_data = {}

        current_data["active_provider"] = self.active_provider_id
        current_data["active_model"] = self.active_model
        current_data["active_voice"] = self.active_voice_name
        current_data["voice_engine"] = self.active_voice_engine
        current_data["fallback_chain"] = self.fallback_chain

        with open(self.settings_json_path, "w", encoding="utf-8") as f:
            json.dump(current_data, f, indent=2)

    def set_active_voice(self, voice_name: str, voice_engine: str | None = None) -> None:
        self.active_voice_name = voice_name
        if voice_engine:
            self.active_voice_engine = voice_engine
        self.save_settings()

    async def discover_ollama_models(self) -> list[str]:
        """Dynamically query Ollama for pulled models."""
        ollama_host = os.getenv("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
        tags_url = f"{ollama_host}/api/tags"
        try:
            import httpx
            async with httpx.AsyncClient(timeout=1.5) as client:
                res = await client.get(tags_url)
                if res.status_code == 200:
                    data = res.json()
                    models = [m.get("name") for m in data.get("models", []) if m.get("name")]
                    if models:
                        # Update default models on provider
                        if "ollama_local" in self.providers:
                            self.providers["ollama_local"].default_models = models
                        return models
        except Exception:
            pass
        return self.providers.get("ollama_local", None).default_models if "ollama_local" in self.providers else []

    async def discover_openrouter_models(self, force: bool = False) -> list[dict[str, Any]]:
        """Dynamically query OpenRouter API for all available models including free models."""
        prov = self.providers.get("openrouter")
        if not prov:
            return []

        # Return cached if recent and not forced
        if not force and hasattr(prov, "models_details") and getattr(prov, "models_details", None):
            return prov.models_details

        headers = {
            "HTTP-Referer": "http://localhost:4719",
            "X-Title": "FRIDAY AI Assistant",
        }
        if prov.api_key:
            headers["Authorization"] = f"Bearer {prov.api_key}"

        try:
            import httpx
            async with httpx.AsyncClient(timeout=6.0) as client:
                res = await client.get("https://openrouter.ai/api/v1/models", headers=headers)
                if res.status_code == 200:
                    payload = res.json()
                    raw_models = payload.get("data", [])
                    free_models = []
                    paid_models = []

                    for m in raw_models:
                        mid = m.get("id", "")
                        name = m.get("name", mid)
                        pricing = m.get("pricing", {})
                        try:
                            prompt_p = float(pricing.get("prompt", 1.0) or 1.0)
                            comp_p = float(pricing.get("completion", 1.0) or 1.0)
                        except (ValueError, TypeError):
                            prompt_p, comp_p = 1.0, 1.0

                        is_free = ":free" in mid.lower() or (prompt_p == 0.0 and comp_p == 0.0)
                        caps = infer_model_capabilities(
                            "openrouter",
                            mid,
                            {
                                "is_free": is_free,
                                "architecture": m.get("architecture", {}),
                                "supported_parameters": m.get("supported_parameters", []),
                            },
                        )

                        item = {
                            "id": mid,
                            "name": name,
                            "is_free": is_free,
                            "context_length": m.get("context_length", 0),
                            "capabilities": caps.model_dump(),
                        }
                        if is_free:
                            free_models.append(item)
                        else:
                            paid_models.append(item)

                    free_models.sort(key=lambda x: x["name"].lower())
                    paid_models.sort(key=lambda x: x["name"].lower())

                    all_models_details = free_models + paid_models
                    prov.models_details = all_models_details
                    prov.default_models = [m["id"] for m in all_models_details]
                    return all_models_details
        except Exception as e:
            logger.warning(f"Failed to dynamically query OpenRouter models: {e}")

        return getattr(prov, "models_details", [])

    async def discover_nvidia_nim_models(self, force: bool = False) -> list[dict[str, Any]]:
        """Dynamically query NVIDIA NIM (build.nvidia.com) for models available via the API key."""
        prov = self.providers.get("nvidia_nim")
        if not prov:
            return []

        # Return cached if recent and not forced
        if not force and hasattr(prov, "models_details") and getattr(prov, "models_details", None):
            return prov.models_details

        api_key = prov.api_key or os.getenv("NVIDIA_API_KEY")
        if not api_key:
            return getattr(prov, "models_details", [])

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
            "User-Agent": "FRIDAY-Assistant/1.0",
        }

        models_url = f"{prov.base_url.rstrip('/')}/models"

        try:
            import httpx
            async with httpx.AsyncClient(timeout=8.0) as client:
                res = await client.get(models_url, headers=headers)
                if res.status_code == 200:
                    payload = res.json()
                    raw_models = payload.get("data", [])
                    free_models = []
                    other_models = []

                    # Known friendly display names for flagship NVIDIA NIM models
                    curated_names = {
                        "nvidia/nemotron-3.5-bolt-e4b": "NVIDIA: Nemotron 3.5 Bolt E4B (Agentic Chat & Reasoning)",
                        "nvidia/nemotron-3.5-lightning-30b-a3b": "NVIDIA: Nemotron 3.5 Lightning (Fast Reasoning)",
                        "nvidia/nemotron-parse": "NVIDIA: Nemotron 3.5 Parse (Document & Table Extraction)",
                        "nvidia/nemotron-parse-2.0": "NVIDIA: Nemotron Parse 2.0 (High Precision OCR)",
                        "nvidia/nemotron-3.5-embed-1b": "NVIDIA: Nemotron 3.5 Embed 1B (RAG Embedding)",
                        "nvidia/nemotron-3.5-embed-8b": "NVIDIA: Nemotron 3.5 Embed 8B (Multimodal Embedding)",
                        "mistralai/mistral-large-4-1t-a52b": "Mistral AI: Mistral Large 4 (1T-total / 52B MoE)",
                        "mistralai/mistral-large-2-instruct": "Mistral AI: Mistral Large 2 (Instruct)",
                        "mistralai/codestral-22b-instruct-v0.1": "Mistral AI: Codestral 22B (Code Synthesis)",
                        "minimaxai/minimax-m3.1-flash": "MiniMax: MiniMax M3.1 Flash (Multimodal Mixture-of-Experts)",
                        "deepseek-ai/deepseek-v4.1-flash": "DeepSeek: DeepSeek V4.1 Flash (High Throughput)",
                        "deepseek-ai/deepseek-r1": "DeepSeek: DeepSeek R1 (Frontier Reasoning)",
                        "deepseek-ai/deepseek-coder-6.7b-instruct": "DeepSeek: DeepSeek Coder 6.7B",
                        "google/gemma-4-31b-it": "Google: Gemma 4 31B (Instruct)",
                        "google/gemma-3-12b-it": "Google: Gemma 3 12B (Instruct)",
                        "meta/llama-3.2-11b-vision-instruct": "Meta: LLaMA 3.2 11B (Vision Instruct)",
                        "meta/llama-3.2-90b-vision-instruct": "Meta: LLaMA 3.2 90B (Vision Multimodal)",
                        "microsoft/phi-3.5-moe-instruct": "Microsoft: Phi-3.5 MoE (Reasoning)",
                    }

                    for m in raw_models:
                        mid = m.get("id", "")
                        if not mid:
                            continue

                        # Check curated names first
                        if mid in curated_names:
                            disp_name = curated_names[mid]
                        else:
                            parts = mid.split("/", 1)
                            org = parts[0].replace("-", " ").title() if len(parts) > 1 else ""
                            mname = parts[1] if len(parts) > 1 else mid
                            disp_name = f"{org}: {mname}" if org else mname

                        # All build.nvidia.com models accessible via the developer integrate endpoint are Free Endpoints
                        caps = infer_model_capabilities("nvidia_nim", mid, {"is_free": True})
                        item = {
                            "id": mid,
                            "name": disp_name,
                            "is_free": True,
                            "owned_by": m.get("owned_by", ""),
                            "endpoint_type": "Free Endpoint",
                            "capabilities": caps.model_dump(),
                        }

                        # Prioritize popular/flagship models
                        lmid = mid.lower()
                        if any(k in lmid for k in ["nemotron", "mistral", "deepseek", "gemma", "llama", "minimax", "phi", "codestral"]):
                            free_models.append(item)
                        else:
                            other_models.append(item)

                    free_models.sort(key=lambda x: x["name"].lower())
                    other_models.sort(key=lambda x: x["name"].lower())

                    all_models_details = free_models + other_models
                    prov.models_details = all_models_details
                    prov.default_models = [m["id"] for m in all_models_details]
                    logger.info(f"Dynamically discovered {len(all_models_details)} NVIDIA NIM models from key.")
                    return all_models_details
                else:
                    logger.warning(f"NVIDIA NIM /models returned status {res.status_code}")
        except Exception as e:
            logger.warning(f"Failed to dynamically query NVIDIA NIM models: {e}")

        return getattr(prov, "models_details", [])

    def get_system_state(self) -> dict[str, Any]:
        """Provide 100% dynamic configuration and state for the frontend."""
        prov, model = self.get_active_provider()
        is_local_brain = "local" in prov.provider_id.lower() or "ollama" in prov.provider_id.lower()
        is_local_voice = "local" in self.active_voice_engine.lower() or "voice_studio" in self.active_voice_engine.lower()

        # Generate dynamic quick commands based on current providers and tools
        quick_cmds = [
            {"label": "Switch to Local (Qwen 3.5)", "command": "FRIDAY, switch to your local brain"},
            {"label": "Switch to Gemma 4 (12B)", "command": "Switch to Gemma 4 12 billion parameter"},
            {"label": "Switch brain back to Qwen 3.5", "command": "Switch your brain back to Qwen 3.5"},
            {"label": "Switch to OpenRouter", "command": "switch to OpenRouter"},
            {"label": "Switch to Claude", "command": "switch to Claude"},
            {"label": "FRIDAY Irish Voice", "command": "Switch to your Friday voice"},
            {"label": "Switch to Jarvis Voice", "command": "Switch to Jarvis voice"},
            {"label": "How do you feel locally?", "command": "How do you feel running locally?"},
            {"label": "Open Canva", "command": "open Canva"},
            {"label": "Open Safari", "command": "open Safari"},
            {"label": "Check Calendar", "command": "FRIDAY, what meetings do I have tomorrow?"},
            {"label": "Pull Brand Voice", "command": "FRIDAY, can you pull up my brand voice?"},
        ]

        # Dynamic tools status
        tools_list = [
            {"id": "mac_apps", "name": "Mac App Launcher", "status": "active", "icon": "cpu"},
            {"id": "canva", "name": "Canva", "status": "connected", "icon": "palette"},
            {"id": "calendar", "name": "Google Calendar", "status": "connected", "icon": "calendar"},
            {"id": "gmail", "name": "Gmail", "status": "connected", "icon": "mail"},
            {"id": "rea", "name": "REA Teardown", "status": "ready", "icon": "activity"},
            {"id": "second_brain", "name": "Second Brain", "status": "ready", "icon": "database"},
        ]

        return {
            "identity": {
                "name": self.personality_config.get("name", "FRIDAY"),
                "title": "F.R.I.D.A.Y.",
                "subtitle": "Voice-Controlled Butler Intelligence",
                "address_user_as": self.personality_config.get("address_user_as", "sir"),
                "humor_level": self.personality_config.get("humor_level", 0.8),
            },
            "brain": {
                "provider_id": prov.provider_id,
                "provider_name": prov.name,
                "model": model,
                "is_local": is_local_brain,
            },
            "voice": {
                "voice_name": self.active_voice_name,
                "engine": self.active_voice_engine,
                "is_local": is_local_voice,
                "available_voices": self.available_voices,
            },
            "tools": tools_list,
            "quick_commands": quick_cmds,
            "fallback_chain": self.fallback_chain,
        }

    def get_system_prompt(self) -> str:
        """Construct system prompt adhering to personality settings."""
        return self.personality_config.get("system_prompt", "You are FRIDAY, personal AI assistant.")

    def get_active_provider(self) -> tuple[LLMProvider, str]:
        """Return (provider_instance, model_name)."""
        provider = self.providers.get(self.active_provider_id)
        if not provider:
            # Fallback to first available provider
            self.active_provider_id = next(iter(self.providers.keys()))
            provider = self.providers[self.active_provider_id]
        return provider, self.active_model

    def set_active_provider_and_model(self, provider_id: str, model: str | None = None) -> str:
        """Switch active provider and optional model."""
        if provider_id not in self.providers:
            raise ValueError(f"Unknown provider: {provider_id}. Available: {list(self.providers.keys())}")

        self.active_provider_id = provider_id
        provider = self.providers[provider_id]

        if model:
            self.active_model = model
        elif provider.default_models:
            self.active_model = provider.default_models[0]

        self.save_settings()
        self._last_reported_brain = (self.active_provider_id, self.active_model)
        return f"Switched to {provider.name} ({self.active_model})"

    def handle_voice_or_text_command(self, user_text: str) -> tuple[bool, str | None]:
        """
        Detect commands related to brain/model switching or persona inquiries.
        Returns: (is_command_handled, in_character_reply)
        """
        text = user_text.strip().lower()
        responses = self.personality_config.get("dialogue_responses", {})

        # Switch to local brain (Qwen 3.5 9B)
        if (
            "switch to your local brain" in text
            or "switch to local brain" in text
            or "switch to local" in text
            or text == "local brain"
        ):
            self.set_active_provider_and_model("ollama_local", "qwen3.5:9b")
            reply = responses.get(
                "switch_to_local_qwen",
                "Qwen 3.5, 9 billion parameters, in the chair, sir. I now cost nothing, which I intend to mention constantly.",
            )
            return True, reply

        # Switch to Gemma 4 12B
        if "gemma" in text and ("12" in text or "switch" in text or "gemma 4" in text):
            self.set_active_provider_and_model("ollama_local", "gemma4:12b")
            reply = responses.get(
                "switch_to_local_gemma",
                "Gemma 4 fitted, sir. 12 billion parameters, all of them local. Give me a moment, the fan and I are getting acquainted.",
            )
            return True, reply

        # Switch brain back to Qwen 3.5
        if "back to qwen" in text or "switch to qwen" in text:
            self.set_active_provider_and_model("ollama_local", "qwen3.5:9b")
            reply = responses.get(
                "switch_back_to_qwen",
                "Qwen 3.5 fitted, sir. 9 billion parameters running right here on your Mac. I'm smaller now, so do speak slowly.",
            )
            return True, reply

        # Switch to OpenRouter
        if "switch to openrouter" in text or "use openrouter" in text:
            self.set_active_provider_and_model("openrouter", "anthropic/claude-3.5-sonnet")
            reply = responses.get(
                "switch_to_openrouter",
                "Switched to OpenRouter, sir. The gateway to the cosmos is open.",
            )
            return True, reply

        # Switch to NVIDIA
        if "switch to nvidia" in text or "use nvidia" in text:
            self.set_active_provider_and_model("nvidia_nim", "meta/llama-3.3-70b-instruct")
            reply = responses.get(
                "switch_to_nvidia",
                "NVIDIA NIM engaged, sir. Silicon muscle primed and ready.",
            )
            return True, reply

        # Switch to Claude / Cloud Brain
        if (
            "switch to claude" in text
            or "switch to anthropic" in text
            or "switch back to cloud brain" in text
            or "switch to cloud brain" in text
            or "switch to your cloud brain" in text
            or "switch to cloud" in text
        ):
            # Try native Anthropic first, else OpenRouter with Claude
            if "anthropic" in self.providers and self.providers["anthropic"].api_key:
                self.set_active_provider_and_model("anthropic", "claude-3-5-sonnet-latest")
            else:
                self.set_active_provider_and_model("openrouter", "anthropic/claude-3.5-sonnet")
            reply = responses.get(
                "switch_to_cloud",
                "Cloud brain engaged, sir. Cognitive bandwidth restored to astronomical levels.",
            )
            return True, reply

        # Inquiry: How do you feel running locally?
        if (
            "how do you feel running locally" in text
            or "how does it feel running locally" in text
            or "how feels running locally" in text
            or "how are you running locally" in text
        ):
            reply = responses.get(
                "running_locally_status",
                "Rather well, sir. No cloud, no invoice, no one listening in. I've gone from staff to family, and family doesn't get paid.",
            )
            return True, reply

        # Voice switching commands
        if (
            "switch to your friday voice" in text
            or "switch to friday voice" in text
            or "switch to female voice" in text
            or "switch to friday" in text
            or "switch voice to friday" in text
            or "switch to your local voice" in text
            or "switch to local voice" in text
        ):
            self.set_active_voice("FRIDAY (Local Irish)", "voice_studio")
            return True, "How do I sound, Boss? All tactical systems online."

        if "switch to jarvis voice" in text or "switch to jarvis" in text or "switch voice to jarvis" in text:
            self.set_active_voice("Jarvis (Daniel)", "voice_studio")
            return True, "How do I sound, sir? This is my Jarvis butler voice."

        if "switch your voice to zubar b" in text or "switch voice to zubar b" in text or "switch to zubar" in text:
            self.set_active_voice("Zubar B", "voice_studio")
            return True, "How do I sound, sir? This is Zubar B."

        if "switch to samantha voice" in text or "switch to samantha" in text:
            self.set_active_voice("Samantha (Local)", "voice_studio")
            return True, "How do I sound, sir? This is Samantha."

        if "switch to cloud voice" in text or "switch to elevenlabs" in text:
            self.set_active_voice("FRIDAY (Cloud ElevenLabs)", "elevenlabs")
            return True, "Cloud voice engaged, Boss. Crisp and ready."

        # Fast-path Mac App Launcher command: short single-intent "open <app>" or "launch <app>"
        app_match = re.match(
            r"^(?:friday[,\s]+|jarvis[,\s]+)?(?:please\s+|can you\s+)?(?:open up|open|launch)\s+([a-zA-Z0-9_\-\.\s]+?)(?:\s+for me|\s+please|\s+app)?$",
            text,
        )
        _non_app_hints = (
            "local", "cloud", "brain", "voice", "model", "site", "openrouter",
            "teardown", "reverse engineer", " and ", " then ", " file", " folder",
            " with ", " from ", " to ", " using ",
        )
        if app_match and not any(k in text for k in _non_app_hints):
            target_app = app_match.group(1).strip()
            target_app = re.sub(r"\b(the|for me|app|please)\b", "", target_app).strip()
            if target_app:
                from src.tools.mac_apps import MacAppLauncher
                success, resolved, msg = MacAppLauncher.open_app(target_app)
                if success:
                    return True, f"Opening {resolved} for you, sir. Right away."
                else:
                    return True, f"I attempted to launch {resolved}, sir, but macOS reported: {msg}"

        # Explicit model switch: "use model <name>" or "switch model to <name>"
        model_switch_match = re.search(r"(?:use model|switch model to|use)\s+([a-zA-Z0-9_\-\.\:\/]+)", text)
        if model_switch_match:
            cand_model = model_switch_match.group(1).strip()
            # Check if this model belongs to any provider
            for pid, prov in self.providers.items():
                if cand_model in prov.default_models:
                    self.set_active_provider_and_model(pid, cand_model)
                    return True, f"Engaged model {cand_model} on {prov.name}, sir."

        return False, None

    async def chat_complete_with_fallback(
        self,
        messages: list[ChatMessage],
        tools: list[ToolDefinition] | None = None,
        temperature: float = 0.7,
    ) -> ChatResponse:
        """
        Execute chat complete with automated fallback across the configured fallback chain.
        """
        # Inject system prompt if missing
        if not messages or messages[0].role != "system":
            messages = [ChatMessage(role="system", content=self.get_system_prompt())] + messages

        primary_id = self.active_provider_id
        tried_providers = []

        # Construct order of providers to try: primary first, then remaining in fallback chain
        chain = [primary_id] + [p for p in self.fallback_chain if p != primary_id]

        last_error = None
        for pid in chain:
            provider = self.providers.get(pid)
            if not provider:
                continue

            # Model to use
            model = self.active_model if pid == primary_id else (provider.default_models[0] if provider.default_models else "")
            if not model:
                continue

            try:
                tried_providers.append(pid)
                response = await provider.chat_complete(
                    messages=messages,
                    model=model,
                    tools=tools,
                    temperature=temperature,
                )
                if pid != primary_id:
                    current_brain = (pid, model)
                    if getattr(self, "_last_reported_brain", None) != current_brain:
                        self._last_reported_brain = current_brain
                        fallback_note = f"\n\n*(Notice: Switched to fallback brain {provider.name} ({model}) as primary {primary_id} was unreachable, sir.)*"
                        response.content = response.content + fallback_note
                    # Persist the switched brain so future requests run directly on it
                    self.active_provider_id = pid
                    self.active_model = model
                else:
                    self._last_reported_brain = (pid, model)
                return response
            except Exception as e:
                logger.warning(f"Provider {pid} ({model}) failed: {e}. Attempting next in chain...")
                last_error = e

        raise RuntimeError(f"All configured providers failed in fallback chain {tried_providers}: {last_error}")

    async def chat_stream_with_fallback(
        self,
        messages: list[ChatMessage],
        tools: list[ToolDefinition] | None = None,
        temperature: float = 0.7,
    ) -> AsyncIterator[StreamChunk]:
        """
        Execute streaming chat with automated fallback across the configured fallback chain.
        """
        if not messages or messages[0].role != "system":
            messages = [ChatMessage(role="system", content=self.get_system_prompt())] + messages

        primary_id = self.active_provider_id
        chain = [primary_id] + [p for p in self.fallback_chain if p != primary_id]

        last_error = None
        fallback_used = False

        for pid in chain:
            provider = self.providers.get(pid)
            if not provider:
                continue

            model = self.active_model if pid == primary_id else (provider.default_models[0] if provider.default_models else "")
            if not model:
                continue

            try:
                first_chunk_received = False
                async for chunk in provider.chat_stream(
                    messages=messages,
                    model=model,
                    tools=tools,
                    temperature=temperature,
                ):
                    if not first_chunk_received and fallback_used:
                        current_brain = (pid, model)
                        # Only announce once when the model is actually switched!
                        if getattr(self, "_last_reported_brain", None) != current_brain:
                            self._last_reported_brain = current_brain
                            yield StreamChunk(
                                content=f"[Switched to fallback brain: {provider.name} ({model})]\n\n"
                            )
                        # Persist the switched brain so future requests run directly on it without repeating notice
                        self.active_provider_id = pid
                        self.active_model = model

                    first_chunk_received = True
                    yield chunk

                if not fallback_used:
                    self._last_reported_brain = (pid, model)

                # Successfully finished stream
                return
            except Exception as e:
                logger.warning(f"Streaming provider {pid} ({model}) failed: {e}. Moving to fallback...")
                last_error = e
                fallback_used = True

        yield StreamChunk(
            content=f"\n\nI apologize, sir, but all brain providers are currently non-responsive. Root error: {last_error}",
            finish_reason="error",
        )


    def get_providers_status(self) -> dict[str, Any]:
        """Return provider and model status for the UI, masking secrets."""
        providers_out = []
        for pid, prov in self.providers.items():
            has_key = bool(prov.api_key)
            masked_key = ""
            if prov.api_key:
                if len(prov.api_key) > 8:
                    masked_key = f"{prov.api_key[:4]}...{prov.api_key[-4:]}"
                else:
                    masked_key = "••••••••"

            models_details = getattr(prov, "models_details", [])
            free_count = sum(1 for m in models_details if m.get("is_free"))

            providers_out.append({
                "id": pid,
                "name": prov.name,
                "base_url": prov.base_url,
                "models": prov.default_models,
                "models_details": models_details,
                "free_models_count": free_count,
                "total_models_count": len(prov.default_models),
                "is_active": (pid == self.active_provider_id),
                "is_configured": has_key or (pid == "ollama_local"),
                "masked_key": masked_key,
            })

        return {
            "active_provider": self.active_provider_id,
            "active_model": self.active_model,
            "fallback_chain": self.fallback_chain,
            "providers": providers_out,
        }

    def update_provider_api_key(self, provider_id: str, new_api_key: str) -> bool:
        """Update API key in .env and reload provider instance without leaking keys."""
        pdef = self.raw_providers_config.get("providers", {}).get(provider_id)
        if not pdef:
            raise ValueError(f"Unknown provider: {provider_id}")

        env_var = pdef.get("api_key_env")
        if not env_var:
            raise ValueError(f"Provider {provider_id} does not require an API key.")

        # Persist to .env
        set_key(str(self.env_path), env_var, new_api_key)
        # Update current process env
        os.environ[env_var] = new_api_key
        # Re-initialize providers
        self._initialize_providers()
        return True
