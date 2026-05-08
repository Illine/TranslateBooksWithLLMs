"""
Base classes and data structures for LLM providers.

This module defines the abstract base class that all LLM providers must implement,
as well as common data structures like LLMResponse.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Iterable, Optional, Union
import httpx

from src.config import TRANSLATE_TAG_IN, TRANSLATE_TAG_OUT, REQUEST_TIMEOUT
from src.utils.telemetry import get_telemetry_headers
from src.core.llm.utils.extraction import TranslationExtractor
from src.core.llm.key_pool import KeyPool


@dataclass
class LLMResponse:
    """Response from LLM with token usage information"""
    content: str
    prompt_tokens: int = 0  # Number of tokens in the prompt
    completion_tokens: int = 0  # Number of tokens in the response
    context_used: int = 0  # Total context used (prompt + completion)
    context_limit: int = 0  # Context limit that was set for this request
    was_truncated: bool = False  # True if response was truncated due to context limit


class LLMProvider(ABC):
    """Abstract base class for LLM providers"""

    def __init__(
        self,
        model: str,
        api_keys: Optional[Union[str, Iterable[str]]] = None,
        provider_name: str = "",
    ):
        """
        Initialize the LLM provider.

        Args:
            model: Model name/identifier.
            api_keys: A single API key or an iterable of keys. When given,
                wrapped in a KeyPool that supports rotation on HTTP 429.
                Pass None for providers that don't use API keys (e.g. Ollama).
            provider_name: Logical name used for log messages and rate-limit
                error reports. Defaults to the empty string ("unknown" in logs).
        """
        self.model = model
        self._extractor = TranslationExtractor(TRANSLATE_TAG_IN, TRANSLATE_TAG_OUT)
        self._client = None
        self._key_pool: Optional[KeyPool] = None
        if api_keys:
            keys_iter = [api_keys] if isinstance(api_keys, str) else list(api_keys)
            keys_iter = [k for k in keys_iter if k]
            if keys_iter:
                self._key_pool = KeyPool(keys_iter, provider_name=provider_name or "unknown")

    @property
    def api_key(self) -> Optional[str]:
        """The current 'primary' API key (first non-throttled if a pool is used).

        Kept for backwards compatibility with code that reads the key directly
        (e.g. listing models, context detection). Translation paths should
        always use the pool's `acquire()` so rotation can happen.
        """
        return self._key_pool.peek() if self._key_pool else None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create a persistent HTTP client with connection pooling"""
        if self._client is None:
            # Add client identification headers to all requests
            telemetry_headers = get_telemetry_headers()
            self._client = httpx.AsyncClient(
                limits=httpx.Limits(max_keepalive_connections=5, max_connections=10),
                timeout=httpx.Timeout(REQUEST_TIMEOUT),
                headers=telemetry_headers
            )
        return self._client

    async def close(self):
        """Close the HTTP client"""
        if self._client:
            await self._client.aclose()
            self._client = None

    @abstractmethod
    async def generate(self, prompt: str, timeout: int = REQUEST_TIMEOUT,
                      system_prompt: Optional[str] = None) -> Optional["LLMResponse"]:
        """
        Generate text from prompt.

        Args:
            prompt: The user prompt (content to process)
            timeout: Request timeout in seconds
            system_prompt: Optional system prompt (role/instructions)

        Returns:
            LLMResponse object with content and token usage info, or None if failed
        """
        pass

    def extract_translation(self, response: str) -> Optional[str]:
        """
        Extract translation from response using configured tags with strict validation.

        Returns the content between TRANSLATE_TAG_IN and TRANSLATE_TAG_OUT.
        Prefers responses where tags are at exact boundaries for better reliability.

        NOTE: This method completely ignores content within <think></think> tags,
        as these are used by certain LLMs for internal reasoning and should not
        be searched for translation tags.

        Args:
            response: Raw text response from the LLM

        Returns:
            Extracted translation text, or None if extraction fails
        """
        return self._extractor.extract(response)

    async def translate_text(self, prompt: str) -> Optional[str]:
        """Complete translation workflow: request + extraction"""
        response = await self.generate(prompt)
        if response:
            return self.extract_translation(response.content)
        return None
