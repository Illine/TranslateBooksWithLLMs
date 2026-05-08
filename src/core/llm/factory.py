"""
Factory for creating LLM provider instances.

This module provides the create_llm_provider() function which instantiates
the appropriate provider based on the provider_type parameter.
"""

import os
from typing import List, Optional, Union

from src.config import (
    API_ENDPOINT, DEFAULT_MODEL, OLLAMA_NUM_CTX,
    OPENROUTER_API_KEY, OPENROUTER_MODEL,
    MISTRAL_API_KEY, MISTRAL_MODEL, MISTRAL_API_ENDPOINT,
    DEEPSEEK_API_KEY, DEEPSEEK_MODEL, DEEPSEEK_API_ENDPOINT,
    DEEPSEEK_DISABLE_THINKING,
    POE_API_KEY, POE_MODEL, POE_API_ENDPOINT,
    NIM_API_KEY, NIM_MODEL, NIM_API_ENDPOINT
)
from .base import LLMProvider
from .providers.ollama import OllamaProvider
from .providers.openai import OpenAICompatibleProvider
from .providers.gemini import GeminiProvider
from .providers.openrouter import OpenRouterProvider
from .providers.mistral import MistralProvider
from .providers.deepseek import DeepSeekProvider
from .providers.poe import PoeProvider


def _normalize_keys(
    raw: Optional[Union[str, List[str]]]
) -> Optional[Union[str, List[str]]]:
    """Normalize an api_key argument to support multi-key pools.

    A user can supply keys as:
        - None / "" → returned as-is (caller raises if required)
        - "single_key" → returned as the same string (single-key pool)
        - "k1,k2,k3" → split on commas/newlines/whitespace, returned as list
        - ["k1", "k2"] → returned as the same list

    Whitespace and empty fragments are trimmed. Order is preserved (used for
    round-robin in the pool).
    """
    if raw is None:
        return None
    if isinstance(raw, str):
        if "," not in raw and "\n" not in raw:
            return raw  # single key, no parsing
        parts = [p.strip() for p in raw.replace("\n", ",").split(",")]
        parts = [p for p in parts if p]
        if not parts:
            return None
        return parts[0] if len(parts) == 1 else parts
    return list(raw)


def create_llm_provider(provider_type: str = "ollama", **kwargs) -> LLMProvider:
    """
    Create an LLM provider instance.

    Auto-detection: If provider_type is "ollama" and model name starts with "gemini",
    automatically switches to Gemini provider.

    Args:
        provider_type: Type of provider ("ollama", "openai", "gemini", "openrouter", "mistral", "deepseek", "poe")
        **kwargs: Provider-specific parameters:
            - api_endpoint: API endpoint URL (Ollama, OpenAI)
            - model: Model name/identifier
            - api_key: API key (Gemini, OpenAI, OpenRouter)
            - context_window: Context window size (Ollama, OpenAI)
            - log_callback: Logging callback function (Ollama, OpenAI)

    Returns:
        Instantiated LLMProvider subclass

    Raises:
        ValueError: If provider_type is unknown or required parameters are missing

    Examples:
        >>> # Ollama provider
        >>> provider = create_llm_provider("ollama", model="llama3")

        >>> # OpenAI-compatible provider
        >>> provider = create_llm_provider("openai", api_key="sk-...", model="gpt-4")

        >>> # Gemini provider (auto-detected from model name)
        >>> provider = create_llm_provider("ollama", model="gemini-2.0-flash")

        >>> # OpenRouter provider
        >>> provider = create_llm_provider("openrouter", api_key="sk-or-...", model="anthropic/claude-sonnet-4")
    """
    # Auto-detect provider from model name if not explicitly set
    model = kwargs.get("model", DEFAULT_MODEL)
    if provider_type == "ollama" and model and model.startswith("gemini"):
        # Auto-switch to Gemini provider when Gemini model is detected
        provider_type = "gemini"

    if provider_type.lower() == "ollama":
        return OllamaProvider(
            api_endpoint=kwargs.get("api_endpoint") or kwargs.get("endpoint") or API_ENDPOINT,
            model=kwargs.get("model", DEFAULT_MODEL),
            context_window=kwargs.get("context_window") or OLLAMA_NUM_CTX,
            log_callback=kwargs.get("log_callback")
        )
    elif provider_type.lower() == "openai":
        api_endpoint = kwargs.get("api_endpoint") or kwargs.get("endpoint") or ""
        # Distinguish official OpenAI from local llama.cpp/vLLM/LM Studio for log clarity
        pname = "openai" if "api.openai.com" in api_endpoint else "openai-compatible"
        return OpenAICompatibleProvider(
            api_endpoint=api_endpoint,
            model=kwargs.get("model", DEFAULT_MODEL),
            api_key=_normalize_keys(kwargs.get("api_key") or kwargs.get("openai_api_key")),
            context_window=kwargs.get("context_window") or OLLAMA_NUM_CTX,
            log_callback=kwargs.get("log_callback"),
            provider_name=pname,
        )
    elif provider_type.lower() == "gemini":
        api_key = _normalize_keys(
            kwargs.get("api_key") or kwargs.get("gemini_api_key") or os.getenv("GEMINI_API_KEY")
        )
        if not api_key:
            raise ValueError("Gemini provider requires an API key. Set GEMINI_API_KEY environment variable or pass api_key parameter.")
        return GeminiProvider(
            api_key=api_key,
            model=kwargs.get("model", "gemini-2.0-flash")
        )
    elif provider_type.lower() == "openrouter":
        api_key = _normalize_keys(
            kwargs.get("api_key") or kwargs.get("openrouter_api_key")
            or os.getenv("OPENROUTER_API_KEY", OPENROUTER_API_KEY)
        )
        if not api_key:
            raise ValueError("OpenRouter provider requires an API key. Set OPENROUTER_API_KEY environment variable or pass api_key parameter.")
        return OpenRouterProvider(
            api_key=api_key,
            model=kwargs.get("model", OPENROUTER_MODEL)
        )
    elif provider_type.lower() == "mistral":
        api_key = _normalize_keys(
            kwargs.get("api_key") or kwargs.get("mistral_api_key")
            or os.getenv("MISTRAL_API_KEY", MISTRAL_API_KEY)
        )
        if not api_key:
            raise ValueError("Mistral provider requires an API key. Set MISTRAL_API_KEY environment variable or pass api_key parameter.")
        return MistralProvider(
            api_key=api_key,
            model=kwargs.get("model", MISTRAL_MODEL),
            api_endpoint=MISTRAL_API_ENDPOINT
        )
    elif provider_type.lower() == "deepseek":
        api_key = _normalize_keys(
            kwargs.get("api_key") or kwargs.get("deepseek_api_key")
            or os.getenv("DEEPSEEK_API_KEY", DEEPSEEK_API_KEY)
        )
        if not api_key:
            raise ValueError("DeepSeek provider requires an API key. Set DEEPSEEK_API_KEY environment variable or pass api_key parameter.")
        return DeepSeekProvider(
            api_key=api_key,
            model=kwargs.get("model", DEEPSEEK_MODEL),
            api_endpoint=DEEPSEEK_API_ENDPOINT,
            disable_thinking=kwargs.get("deepseek_disable_thinking", DEEPSEEK_DISABLE_THINKING)
        )
    elif provider_type.lower() == "poe":
        api_key = _normalize_keys(
            kwargs.get("api_key") or kwargs.get("poe_api_key")
            or os.getenv("POE_API_KEY", POE_API_KEY)
        )
        if not api_key:
            raise ValueError("Poe provider requires an API key. Get your key at https://poe.com/api_key")
        return PoeProvider(
            api_key=api_key,
            model=kwargs.get("model", POE_MODEL),
            api_endpoint=POE_API_ENDPOINT
        )
    elif provider_type.lower() == "nim":
        api_key = _normalize_keys(
            kwargs.get("api_key") or kwargs.get("nim_api_key")
            or os.getenv("NIM_API_KEY", NIM_API_KEY)
        )
        if not api_key:
            raise ValueError("NVIDIA NIM provider requires an API key. Get your key at https://build.nvidia.com/")
        return OpenAICompatibleProvider(
            api_key=api_key,
            model=kwargs.get("model", NIM_MODEL),
            api_endpoint=kwargs.get("api_endpoint", NIM_API_ENDPOINT),
            provider_name="nim",
        )

    else:
        raise ValueError(f"Unknown provider type: {provider_type}")
