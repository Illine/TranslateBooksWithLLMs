"""
Fallback provider runner.

Lets a translation job route suspicious chunks through a second LLM
provider configured via env. Designed so that an NSFW book primary
translated with Gemini Flash 3.5 can fall back to a local Ollama uncensored
model (e.g. qwen3:14b on a workstation) for the 5-10 percent of chunks that
the primary refuses, without paying a second round on every chunk.

Trigger contract (only these conditions invoke the fallback):
    1. Post-validation flagged the chunk with reason "refusal_marker" or
       "high_latin_ratio". Echo is intentionally excluded - echo is often a
       benign false positive on short structural snippets.
    2. Phase 3 entry in xhtml_translator (primary completely failed to
       return usable text after retries and token-alignment fallback).

A hard per-job budget prevents runaway cost when the primary refuses
chunk after chunk. Once the budget is exhausted, the runner stops issuing
fallback calls and only emits warnings, so the job still finishes.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional, Tuple

from .response_validator import (
    ValidationConfig,
    ValidationResult,
    format_validation_warning,
    validate_translation_response,
)


@dataclass(frozen=True)
class FallbackConfig:
    """Tunable fallback settings. Loaded from env when not constructed
    explicitly. If `provider` is empty, the fallback is disabled and
    `build_fallback_client` returns None."""

    provider: str = ""
    model: str = ""
    api_key: Optional[str] = None
    max_invocations_per_job: int = 100
    trigger_on_phase3: bool = True
    trigger_on_suspicious: bool = True

    @classmethod
    def from_env(cls) -> "FallbackConfig":
        return cls(
            provider=os.getenv("FALLBACK_PROVIDER", "").strip(),
            model=os.getenv("FALLBACK_MODEL", "").strip(),
            api_key=os.getenv("FALLBACK_API_KEY") or None,
            max_invocations_per_job=_env_int(
                "FALLBACK_MAX_INVOCATIONS_PER_JOB", 100
            ),
            trigger_on_phase3=_env_bool("FALLBACK_TRIGGER_ON_PHASE3", True),
            trigger_on_suspicious=_env_bool(
                "FALLBACK_TRIGGER_ON_SUSPICIOUS", True
            ),
        )

    @property
    def enabled(self) -> bool:
        return bool(self.provider)


class FallbackBudget:
    """Tracks fallback invocations within a single translation job.

    `try_consume` returns True and increments the counter when capacity is
    available. After the limit is reached, returns False and the runner
    declines further calls (advisory mode only).
    """

    def __init__(self, limit: int):
        if limit < 0:
            raise ValueError(f"limit must be non-negative, got {limit}")
        self._limit = limit
        self._used = 0
        self._exhausted_logged = False

    @property
    def used(self) -> int:
        return self._used

    @property
    def limit(self) -> int:
        return self._limit

    @property
    def remaining(self) -> int:
        return max(0, self._limit - self._used)

    @property
    def is_exhausted(self) -> bool:
        return self._used >= self._limit

    def try_consume(self) -> bool:
        if self.is_exhausted:
            return False
        self._used += 1
        return True

    def mark_exhaustion_logged(self) -> bool:
        """One-shot guard so the exhaustion warning isn't repeated per
        chunk. Returns True only on the first call (warning should be
        emitted), False on subsequent calls."""
        if self._exhausted_logged:
            return False
        self._exhausted_logged = True
        return True


def build_fallback_client(config: Optional[FallbackConfig] = None):
    """Instantiate the fallback LLM client once per job, or None.

    Uses the same `create_llm_client` factory that builds the primary client
    in `translate_epub_file`. This guarantees the fallback object exposes the
    identical interface and config surface that `generate_translation_request`
    expects, avoiding subtle behavioural drift between the two paths.

    Per-provider API keys come from the standard env vars (GEMINI_API_KEY,
    DEEPSEEK_API_KEY, ...). FALLBACK_API_KEY overrides the one for the
    selected fallback provider only.

    Raises ValueError early when the config is half-set (provider without
    model).

    Returns:
        An LLMClient instance, or None if `FALLBACK_PROVIDER` is empty.
    """
    cfg = config or FallbackConfig.from_env()
    if not cfg.enabled:
        return None

    if not cfg.model:
        raise ValueError(
            "FALLBACK_PROVIDER is set to "
            f"{cfg.provider!r} but FALLBACK_MODEL is missing. Set FALLBACK_MODEL "
            "in .env or unset FALLBACK_PROVIDER to disable the fallback."
        )

    # Imports are lazy to keep this module independent of the legacy client
    # at import time (avoids circular deps with translator.py).
    from ...llm_client import create_llm_client
    from src import config as app_config

    provider = cfg.provider.lower()
    provider_keys = {
        "gemini": os.getenv("GEMINI_API_KEY"),
        "openai": os.getenv("OPENAI_API_KEY"),
        "openrouter": os.getenv("OPENROUTER_API_KEY") or getattr(app_config, "OPENROUTER_API_KEY", None),
        "mistral": os.getenv("MISTRAL_API_KEY") or getattr(app_config, "MISTRAL_API_KEY", None),
        "deepseek": os.getenv("DEEPSEEK_API_KEY") or getattr(app_config, "DEEPSEEK_API_KEY", None),
        "anthropic": os.getenv("ANTHROPIC_API_KEY") or getattr(app_config, "ANTHROPIC_API_KEY", None),
        "poe": os.getenv("POE_API_KEY") or getattr(app_config, "POE_API_KEY", None),
        "nim": os.getenv("NIM_API_KEY") or getattr(app_config, "NIM_API_KEY", None),
    }
    if cfg.api_key and provider in provider_keys:
        provider_keys[provider] = cfg.api_key

    # Mirror the same env precedence the primary client uses (see src/config.py
    # API_ENDPOINT alias). Some setups only set the legacy API_ENDPOINT (or
    # configure the endpoint through the UI which writes OLLAMA_API_ENDPOINT);
    # honour both so the fallback never ends up pointing at localhost when the
    # primary clearly uses a different host (e.g. host.docker.internal from
    # within a container reaching the host workstation).
    api_endpoint = (
        os.getenv("OLLAMA_API_ENDPOINT")
        or os.getenv("API_ENDPOINT")
        or "http://localhost:11434/api/generate"
    )

    return create_llm_client(
        llm_provider=provider,
        gemini_api_key=provider_keys["gemini"],
        api_endpoint=api_endpoint,
        model_name=cfg.model,
        openai_api_key=provider_keys["openai"],
        openrouter_api_key=provider_keys["openrouter"],
        mistral_api_key=provider_keys["mistral"],
        deepseek_api_key=provider_keys["deepseek"],
        anthropic_api_key=provider_keys["anthropic"],
        poe_api_key=provider_keys["poe"],
        nim_api_key=provider_keys["nim"],
    )


def should_trigger_fallback(
    result: ValidationResult,
    config: FallbackConfig,
) -> bool:
    """Decide whether a ValidationResult deserves a fallback call.

    Only refusal_marker and high_latin_ratio are routed through fallback.
    Echo is excluded to avoid double-spend on benign short-content false
    positives.
    """
    if not config.enabled or not config.trigger_on_suspicious:
        return False
    if not result.is_suspicious:
        return False
    return result.reason in ("refusal_marker", "high_latin_ratio")


async def try_fallback_translation(
    *,
    original_text: str,
    source_language: str,
    target_language: str,
    fallback_client,
    budget: FallbackBudget,
    log_callback=None,
    chunk_label: str = "chunk",
    has_placeholders: bool = False,
    prompt_options: Optional[dict] = None,
    placeholder_format: Optional[Tuple[str, str]] = None,
    validation_config: Optional[ValidationConfig] = None,
) -> Tuple[Optional[str], Optional[ValidationResult]]:
    """Run the fallback provider against `original_text`.

    Mirrors the primary path: builds the translation prompt, sends it
    through the fallback LLM, extracts the result, post-validates it. Does
    NOT do Phase-2 token alignment; placeholder failures fall back to None
    so callers can decide what to do (keep primary's draft, or accept
    Phase 3 with source text).

    Args:
        original_text: Source chunk to translate. May still contain
            placeholders if `has_placeholders=True`.
        source_language: Human-readable source language.
        target_language: Human-readable target language.
        fallback_client: LLMProvider instance returned by
            `build_fallback_client`. Must not be None.
        budget: Per-job FallbackBudget. Consumed on entry.
        log_callback: Optional logger.
        chunk_label: Short identifier for log messages.
        has_placeholders: Whether the source chunk contains placeholders
            that the prompt must preserve.
        prompt_options: Forwarded to `generate_translation_request`.
        placeholder_format: Same.
        validation_config: Forwarded to `validate_translation_response`.

    Returns:
        Tuple (translated_text, validation_result). Either may be None:
            - (None, None) when budget is exhausted or fallback raised.
            - (None, result) when fallback returned text but
              post-validation still flagged it (caller decides whether to
              keep or discard).
            - (text, result) on success.
    """
    if fallback_client is None:
        return None, None

    if not budget.try_consume():
        # Emit the exhaustion warning at most once per job. Subsequent
        # suspicious chunks are silently skipped to avoid log spam.
        if log_callback and budget.limit > 0 and budget.mark_exhaustion_logged():
            log_callback(
                "fallback_budget_exhausted",
                (
                    f"⚠️ Fallback budget exhausted "
                    f"({budget.used}/{budget.limit} invocations used). "
                    "Further suspicious chunks will be logged only."
                ),
            )
        return None, None

    if log_callback:
        log_callback(
            "fallback_invoked",
            (
                f"🔁 Fallback provider invoked for {chunk_label} "
                f"(used {budget.used}/{budget.limit})"
            ),
        )

    # Import inside the function to avoid a circular dependency at module
    # import time: translator -> fallback_runner -> translator.
    from ...translator import generate_translation_request

    try:
        translated = await generate_translation_request(
            original_text,
            context_before="",
            context_after="",
            previous_translation_context="",
            source_language=source_language,
            target_language=target_language,
            model=getattr(fallback_client, "model", ""),
            llm_client=fallback_client,
            log_callback=log_callback,
            has_placeholders=has_placeholders,
            placeholder_format=placeholder_format,
            prompt_options=prompt_options,
        )
    except Exception as exc:
        if log_callback:
            log_callback(
                "fallback_error",
                f"❌ Fallback provider raised for {chunk_label}: {exc!r}",
            )
        return None, None

    if not translated:
        if log_callback:
            log_callback(
                "fallback_empty",
                f"❌ Fallback provider returned empty content for {chunk_label}",
            )
        return None, None

    result = validate_translation_response(
        translated,
        original_text,
        source_language,
        target_language,
        validation_config,
    )

    if result.is_suspicious:
        if log_callback:
            log_callback(
                "fallback_suspicious",
                (
                    "⚠️ Fallback provider also flagged for "
                    f"{chunk_label}: "
                    + format_validation_warning(result, chunk_label)
                ),
            )
        return None, result

    if log_callback:
        log_callback(
            "fallback_success",
            f"✓ Fallback provider produced clean translation for {chunk_label}",
        )
    return translated, result


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default
