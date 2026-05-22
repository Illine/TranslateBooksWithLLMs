"""
Anthropic (Claude) LLM Provider.

Native client for the Anthropic Messages API, used as an alternative to
accessing Claude through Poe or OpenRouter.

Features:
    - Claude Sonnet, Opus, Haiku families (Claude 4.x)
    - Prompt caching on the system block (``cache_control: ephemeral``)
      gives a ~10x discount on cached input tokens, which is a big win for
      long-book translation where the system prompt and glossary stay
      stable across chunks
    - 200K context window (1M for Sonnet via beta header, not enabled here)
    - Rate-limit handling via the shared ``rate_limit_handler``
"""

from typing import List, Optional, Union
import httpx
import asyncio
import json

from src.config import REQUEST_TIMEOUT, MAX_TRANSLATION_ATTEMPTS, TEMPERATURE
from ..base import LLMProvider, LLMResponse
from ..exceptions import ContextOverflowError
from ..rate_limit_handler import handle_rate_limit


class AnthropicProvider(LLMProvider):
    """
    Provider for the Anthropic Messages API.

    Configuration:
        endpoint: https://api.anthropic.com/v1/messages
        model: Model identifier (e.g. ``claude-sonnet-4-6``)
        api_key: Anthropic API key

    Prompt caching:
        The ``system_prompt`` passed to :meth:`generate` is wrapped in a
        cache-control block. Anthropic charges 1.25x base input for the
        first request that writes the cache and 0.1x for subsequent reads,
        which on a long book amortises to a 2-3x net saving versus baseline.
    """

    API_URL = "https://api.anthropic.com/v1/messages"
    API_VERSION = "2023-06-01"

    # 1M is available for Sonnet with a beta header but disabled here.
    MODEL_CONTEXT_SIZES = {
        "claude-opus-4-7":     200000,
        "claude-opus-4":       200000,
        "claude-sonnet-4-6":   200000,
        "claude-sonnet-4":     200000,
        "claude-haiku-4-5":    200000,
        "claude-haiku-4":      200000,
        "claude-3-5-sonnet":   200000,
        "claude-3-5-haiku":    200000,
        "claude-3-opus":       200000,
    }

    FALLBACK_MODELS = [
        "claude-sonnet-4-6",
        "claude-opus-4-7",
        "claude-haiku-4-5",
    ]

    DEFAULT_MAX_TOKENS = 8192

    def __init__(
        self,
        api_key: Union[str, List[str]],
        model: str = "claude-sonnet-4-6",
        api_endpoint: Optional[str] = None,
        enable_prompt_caching: bool = True,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ):
        """
        Initialize the Anthropic provider.

        Args:
            api_key: Anthropic API key (or comma-separated list for rotation).
            model: Model identifier (default ``claude-sonnet-4-6``).
            api_endpoint: Optional custom endpoint (proxy/relay).
            enable_prompt_caching: Wrap system prompt in a cache-control block.
                Disable only for debugging; the saving on a long book is large.
            max_tokens: Upper bound for the response. Must be >= expected chunk.
        """
        super().__init__(model, api_keys=api_key, provider_name="anthropic")
        self.api_endpoint = api_endpoint or self.API_URL
        self.enable_prompt_caching = enable_prompt_caching
        self.max_tokens = max_tokens

    def _get_context_limit(self, model_name: Optional[str] = None) -> int:
        """Resolve context limit by matching the model name prefix."""
        model_lower = (model_name or self.model).lower()
        for prefix, limit in self.MODEL_CONTEXT_SIZES.items():
            if prefix in model_lower:
                return limit
        return 200000

    async def get_available_models(self) -> list:
        """
        Fetch models from the Anthropic API.

        Returns the fallback list if the API call fails or the key is missing.
        """
        if not self.api_key:
            return self._get_fallback_models()

        try:
            headers = {
                "x-api-key": self.api_key,
                "anthropic-version": self.API_VERSION,
                "Accept": "application/json",
            }
            client = await self._get_client()
            response = await client.get(
                "https://api.anthropic.com/v1/models",
                headers=headers,
                timeout=15,
            )
            response.raise_for_status()

            models_data = response.json().get("data", [])
            filtered_models = []
            for model in models_data:
                model_id = model.get("id", "")
                if not model_id:
                    continue
                filtered_models.append({
                    "id": model_id,
                    "name": model.get("display_name") or model_id,
                    "context_length": self._get_context_limit(model_id),
                })

            filtered_models.sort(key=lambda x: x["name"], reverse=True)

            if not filtered_models:
                return self._get_fallback_models()
            return filtered_models

        except Exception as e:
            print(f"⚠️ Failed to fetch Anthropic models: {e}")
            return self._get_fallback_models()

    def _get_fallback_models(self) -> list:
        return [
            {
                "id": m,
                "name": m,
                "context_length": self._get_context_limit(m),
            }
            for m in self.FALLBACK_MODELS
        ]

    def _build_system(self, system_prompt: Optional[str]):
        """
        Build the ``system`` field with optional cache_control.

        Anthropic accepts either a plain string or a list of content blocks.
        We use the block form so we can attach ``cache_control: ephemeral``
        and trigger prompt caching for the stable part of the prompt.
        """
        if not system_prompt:
            return None
        if not self.enable_prompt_caching:
            return system_prompt
        return [
            {
                "type": "text",
                "text": system_prompt,
                "cache_control": {"type": "ephemeral"},
            }
        ]

    async def generate(
        self,
        prompt: str,
        timeout: int = REQUEST_TIMEOUT,
        system_prompt: Optional[str] = None,
    ) -> Optional[LLMResponse]:
        """
        Generate a response from the Anthropic Messages API.

        Args:
            prompt: User content to translate.
            timeout: Request timeout in seconds.
            system_prompt: System instructions (cached when enabled).

        Returns:
            ``LLMResponse`` with content and token usage, or ``None`` on
            unrecoverable failure.

        Raises:
            ContextOverflowError: If the input exceeds the model's context.
        """
        payload = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "temperature": TEMPERATURE,
            "messages": [{"role": "user", "content": prompt}],
        }
        system_field = self._build_system(system_prompt)
        if system_field is not None:
            payload["system"] = system_field

        client = await self._get_client()
        base_headers = {
            "anthropic-version": self.API_VERSION,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        for attempt in range(MAX_TRANSLATION_ATTEMPTS):
            current_key = await self._key_pool.acquire()
            headers = {**base_headers, "x-api-key": current_key}
            try:
                response = await client.post(
                    self.api_endpoint,
                    headers=headers,
                    json=payload,
                    timeout=timeout,
                )

                if response.status_code == 401:
                    raise ValueError("Invalid Anthropic API key")

                if response.status_code == 429 or response.status_code == 529:
                    # 529 = overloaded; treat as rate-limit for backoff purposes.
                    await handle_rate_limit(
                        self._key_pool, current_key, response.headers,
                        attempt, MAX_TRANSLATION_ATTEMPTS,
                    )
                    continue

                response.raise_for_status()
                result = response.json()

                content_blocks = result.get("content", [])
                if not content_blocks:
                    print(f"⚠️ Anthropic: Empty content in response: {result}")
                    return None

                # Extended-thinking responses interleave ``thinking`` blocks; skip them.
                response_text = "".join(
                    block.get("text", "")
                    for block in content_blocks
                    if block.get("type") == "text"
                )

                usage = result.get("usage", {})
                input_tokens = usage.get("input_tokens", 0)
                output_tokens = usage.get("output_tokens", 0)
                cache_read = usage.get("cache_read_input_tokens", 0)
                cache_creation = usage.get("cache_creation_input_tokens", 0)

                cache_note = ""
                if cache_read or cache_creation:
                    cache_note = f" (cache_read={cache_read}, cache_write={cache_creation})"
                print(f"💬 Anthropic: {input_tokens}+{output_tokens} tokens{cache_note}")

                return LLMResponse(
                    content=response_text,
                    prompt_tokens=input_tokens,
                    completion_tokens=output_tokens,
                    context_used=input_tokens + cache_read + cache_creation + output_tokens,
                    context_limit=self._get_context_limit(),
                    was_truncated=result.get("stop_reason") == "max_tokens",
                )

            except httpx.TimeoutException as e:
                print(f"Anthropic API Timeout (attempt {attempt + 1}/{MAX_TRANSLATION_ATTEMPTS}): {e}")
                if attempt < MAX_TRANSLATION_ATTEMPTS - 1:
                    await asyncio.sleep(2)
                    continue
                return None

            except httpx.HTTPStatusError as e:
                error_body = ""
                error_message = str(e)
                if hasattr(e, "response") and hasattr(e.response, "text"):
                    error_body = e.response.text[:500]
                    error_message = f"{e} - {error_body}"

                status = e.response.status_code
                if status == 404:
                    print(f"❌ Anthropic: Model '{self.model}' not found!")
                    print("   Check available models at https://docs.anthropic.com/en/docs/about-claude/models")
                elif status == 403:
                    print("❌ Anthropic: Forbidden (region/permissions)!")
                elif status == 400:
                    print(f"❌ Anthropic: Bad request: {error_body}")
                else:
                    print(f"Anthropic API HTTP Error (attempt {attempt + 1}/{MAX_TRANSLATION_ATTEMPTS}): {e}")
                    print(f"Response details: Status {status}, Body: {error_body}...")

                context_overflow_keywords = [
                    "context_length", "maximum context", "token limit",
                    "too many tokens", "reduce the length", "max_tokens",
                    "context window", "exceeds", "prompt is too long",
                ]
                if any(kw in error_message.lower() for kw in context_overflow_keywords):
                    raise ContextOverflowError(f"Anthropic context overflow: {error_message}")

                if attempt < MAX_TRANSLATION_ATTEMPTS - 1:
                    await asyncio.sleep(2)
                    continue
                return None

            except json.JSONDecodeError as e:
                print(f"Anthropic API JSON Decode Error (attempt {attempt + 1}/{MAX_TRANSLATION_ATTEMPTS}): {e}")
                if attempt < MAX_TRANSLATION_ATTEMPTS - 1:
                    await asyncio.sleep(2)
                    continue
                return None

            except Exception as e:
                print(f"Anthropic API Unknown Error (attempt {attempt + 1}/{MAX_TRANSLATION_ATTEMPTS}): {e}")
                if attempt < MAX_TRANSLATION_ATTEMPTS - 1:
                    await asyncio.sleep(2)
                    continue
                return None

        return None
