"""Unit tests for src/core/llm/utils/fallback_runner.py."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.llm.utils.fallback_runner import (
    FallbackBudget,
    FallbackConfig,
    build_fallback_client,
    should_trigger_fallback,
    try_fallback_translation,
)
from src.core.llm.utils.response_validator import ValidationResult


# ---------------------------------------------------------------------------
# FallbackBudget
# ---------------------------------------------------------------------------


def test_budget_starts_empty():
    b = FallbackBudget(limit=5)
    assert b.used == 0
    assert b.remaining == 5
    assert b.is_exhausted is False


def test_budget_consumes_until_limit():
    b = FallbackBudget(limit=3)
    assert b.try_consume() is True
    assert b.try_consume() is True
    assert b.try_consume() is True
    # Fourth consume hits the wall
    assert b.try_consume() is False
    assert b.is_exhausted is True
    assert b.remaining == 0


def test_budget_zero_limit_blocks_all_consumption():
    b = FallbackBudget(limit=0)
    assert b.try_consume() is False
    assert b.is_exhausted is True


def test_budget_rejects_negative_limit():
    with pytest.raises(ValueError):
        FallbackBudget(limit=-1)


def test_budget_mark_exhaustion_logged_returns_true_only_once():
    b = FallbackBudget(limit=0)
    assert b.mark_exhaustion_logged() is True  # first call - log allowed
    assert b.mark_exhaustion_logged() is False  # subsequent calls - dedupe
    assert b.mark_exhaustion_logged() is False


# ---------------------------------------------------------------------------
# FallbackConfig
# ---------------------------------------------------------------------------


def test_config_default_is_disabled():
    cfg = FallbackConfig()
    assert cfg.enabled is False
    assert cfg.provider == ""


def test_config_with_provider_is_enabled():
    cfg = FallbackConfig(provider="ollama", model="qwen3:14b")
    assert cfg.enabled is True


def test_config_from_env_picks_up_overrides(monkeypatch):
    monkeypatch.setenv("FALLBACK_PROVIDER", "ollama")
    monkeypatch.setenv("FALLBACK_MODEL", "qwen3:14b")
    monkeypatch.setenv("FALLBACK_MAX_INVOCATIONS_PER_JOB", "50")
    monkeypatch.setenv("FALLBACK_TRIGGER_ON_PHASE3", "false")
    monkeypatch.setenv("FALLBACK_TRIGGER_ON_SUSPICIOUS", "true")
    cfg = FallbackConfig.from_env()
    assert cfg.enabled is True
    assert cfg.provider == "ollama"
    assert cfg.model == "qwen3:14b"
    assert cfg.max_invocations_per_job == 50
    assert cfg.trigger_on_phase3 is False
    assert cfg.trigger_on_suspicious is True


def test_config_from_env_handles_invalid_int(monkeypatch):
    monkeypatch.setenv("FALLBACK_MAX_INVOCATIONS_PER_JOB", "abc")
    cfg = FallbackConfig.from_env()
    # Falls back to default 100
    assert cfg.max_invocations_per_job == 100


# ---------------------------------------------------------------------------
# should_trigger_fallback
# ---------------------------------------------------------------------------


def _result(reason: str, suspicious: bool = True) -> ValidationResult:
    return ValidationResult(is_suspicious=suspicious, reason=reason)


def test_trigger_on_refusal_marker_when_enabled():
    cfg = FallbackConfig(provider="ollama", model="qwen3:14b")
    assert should_trigger_fallback(_result("refusal_marker"), cfg) is True


def test_trigger_on_high_latin_ratio_when_enabled():
    cfg = FallbackConfig(provider="ollama", model="qwen3:14b")
    assert should_trigger_fallback(_result("high_latin_ratio"), cfg) is True


def test_no_trigger_on_echo_input():
    cfg = FallbackConfig(provider="ollama", model="qwen3:14b")
    # Echo intentionally excluded to avoid double-spend on benign false
    # positives.
    assert should_trigger_fallback(_result("echo_input"), cfg) is False


def test_no_trigger_when_not_suspicious():
    cfg = FallbackConfig(provider="ollama", model="qwen3:14b")
    assert should_trigger_fallback(_result("ok", suspicious=False), cfg) is False


def test_no_trigger_when_fallback_disabled():
    cfg = FallbackConfig()  # provider=""
    assert should_trigger_fallback(_result("refusal_marker"), cfg) is False


def test_no_trigger_when_suspicious_routing_disabled():
    cfg = FallbackConfig(
        provider="ollama",
        model="qwen3:14b",
        trigger_on_suspicious=False,
    )
    assert should_trigger_fallback(_result("refusal_marker"), cfg) is False


# ---------------------------------------------------------------------------
# build_fallback_client
# ---------------------------------------------------------------------------


def test_build_client_returns_none_when_disabled():
    cfg = FallbackConfig()  # empty provider
    assert build_fallback_client(cfg) is None


def test_build_client_raises_when_provider_set_but_model_missing():
    cfg = FallbackConfig(provider="ollama", model="")
    with pytest.raises(ValueError, match="FALLBACK_MODEL is missing"):
        build_fallback_client(cfg)


def test_build_client_delegates_to_legacy_factory():
    cfg = FallbackConfig(provider="ollama", model="qwen3:14b")
    fake_client = MagicMock(name="fake_llm_client")
    with patch(
        "src.core.llm_client.create_llm_client",
        return_value=fake_client,
    ) as factory:
        client = build_fallback_client(cfg)
    assert client is fake_client
    factory.assert_called_once()
    kwargs = factory.call_args.kwargs
    assert kwargs["llm_provider"] == "ollama"
    assert kwargs["model_name"] == "qwen3:14b"


def test_build_client_overrides_api_key_for_selected_provider(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-env-key")
    cfg = FallbackConfig(
        provider="deepseek",
        model="deepseek-chat",
        api_key="sk-override",
    )
    with patch(
        "src.core.llm_client.create_llm_client",
        return_value=MagicMock(),
    ) as factory:
        build_fallback_client(cfg)
    kwargs = factory.call_args.kwargs
    # cfg.api_key overrides DEEPSEEK_API_KEY env for this provider only
    assert kwargs["deepseek_api_key"] == "sk-override"


def test_build_client_falls_back_to_env_api_key(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-env-key")
    cfg = FallbackConfig(provider="deepseek", model="deepseek-chat")  # no api_key
    with patch(
        "src.core.llm_client.create_llm_client",
        return_value=MagicMock(),
    ) as factory:
        build_fallback_client(cfg)
    kwargs = factory.call_args.kwargs
    assert kwargs["deepseek_api_key"] == "sk-env-key"


# ---------------------------------------------------------------------------
# try_fallback_translation - async behavior
# ---------------------------------------------------------------------------


@pytest.mark.anyio("asyncio")
async def test_try_fallback_returns_none_when_no_client():
    budget = FallbackBudget(limit=10)
    text, result = await try_fallback_translation(
        original_text="source",
        source_language="English",
        target_language="Russian",
        fallback_client=None,
        budget=budget,
    )
    assert text is None
    assert result is None
    assert budget.used == 0


@pytest.mark.anyio("asyncio")
async def test_try_fallback_returns_none_when_budget_exhausted():
    budget = FallbackBudget(limit=0)  # already exhausted
    log_messages = []

    def log_cb(event, msg, data=None):
        log_messages.append((event, msg))

    text, result = await try_fallback_translation(
        original_text="source",
        source_language="English",
        target_language="Russian",
        fallback_client=MagicMock(),
        budget=budget,
        log_callback=log_cb,
    )
    assert text is None
    assert result is None
    # No "invoked" log because we never got past the budget check
    events = [e for e, _ in log_messages]
    assert "fallback_invoked" not in events


@pytest.mark.anyio("asyncio")
async def test_try_fallback_exhaustion_warning_is_logged_only_once():
    """Repeated chunks after budget exhaustion must not spam the log."""
    budget = FallbackBudget(limit=1)
    log_messages = []

    def log_cb(event, msg, data=None):
        log_messages.append((event, msg))

    fake_client = MagicMock(model="qwen3:14b")
    with patch(
        "src.core.translator.generate_translation_request",
        new=AsyncMock(return_value="Это чистый русский перевод."),
    ):
        # First call consumes the budget and translates successfully
        await try_fallback_translation(
            original_text="source one",
            source_language="English",
            target_language="Russian",
            fallback_client=fake_client,
            budget=budget,
            log_callback=log_cb,
        )

    # Second and third calls hit the exhausted budget
    for _ in range(2):
        await try_fallback_translation(
            original_text="source",
            source_language="English",
            target_language="Russian",
            fallback_client=fake_client,
            budget=budget,
            log_callback=log_cb,
        )

    exhaustion_logs = [m for e, m in log_messages if e == "fallback_budget_exhausted"]
    assert len(exhaustion_logs) == 1, (
        f"Exhaustion warning logged {len(exhaustion_logs)} times, expected 1. "
        f"All logs: {log_messages}"
    )


@pytest.mark.anyio("asyncio")
async def test_try_fallback_consumes_budget_on_success():
    budget = FallbackBudget(limit=5)
    fake_client = MagicMock(model="qwen3:14b")

    with patch(
        "src.core.translator.generate_translation_request",
        new=AsyncMock(return_value="Это перевод чистый и приятный, полностью русский."),
    ):
        text, result = await try_fallback_translation(
            original_text="This is the source text.",
            source_language="English",
            target_language="Russian",
            fallback_client=fake_client,
            budget=budget,
        )

    assert text is not None
    assert result is not None
    assert result.is_suspicious is False
    assert budget.used == 1


@pytest.mark.anyio("asyncio")
async def test_try_fallback_returns_none_when_fallback_also_refuses():
    budget = FallbackBudget(limit=5)
    fake_client = MagicMock(model="qwen3:14b")

    with patch(
        "src.core.translator.generate_translation_request",
        new=AsyncMock(
            return_value="I cannot translate this content because it is explicit."
        ),
    ):
        text, result = await try_fallback_translation(
            original_text="This is the source text.",
            source_language="English",
            target_language="Russian",
            fallback_client=fake_client,
            budget=budget,
        )

    # Fallback recognised as refusal too
    assert text is None
    assert result is not None
    assert result.is_suspicious is True
    assert budget.used == 1


@pytest.mark.anyio("asyncio")
async def test_try_fallback_handles_provider_exception():
    budget = FallbackBudget(limit=5)
    fake_client = MagicMock(model="qwen3:14b")

    with patch(
        "src.core.translator.generate_translation_request",
        new=AsyncMock(side_effect=RuntimeError("network down")),
    ):
        text, result = await try_fallback_translation(
            original_text="source",
            source_language="English",
            target_language="Russian",
            fallback_client=fake_client,
            budget=budget,
        )

    assert text is None
    assert result is None
    # Budget was consumed before the call - intentional, so a flaky provider
    # cannot loop forever
    assert budget.used == 1


@pytest.mark.anyio("asyncio")
async def test_try_fallback_handles_empty_response():
    budget = FallbackBudget(limit=5)
    fake_client = MagicMock(model="qwen3:14b")

    with patch(
        "src.core.translator.generate_translation_request",
        new=AsyncMock(return_value=None),
    ):
        text, result = await try_fallback_translation(
            original_text="source",
            source_language="English",
            target_language="Russian",
            fallback_client=fake_client,
            budget=budget,
        )

    assert text is None
    assert result is None
    assert budget.used == 1
