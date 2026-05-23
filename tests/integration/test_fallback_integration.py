"""Integration tests for the fallback runner end-to-end.

Covers the four sentinel scenarios called out in the plan:
    1. Primary success path - fallback never invoked.
    2. Primary refuses every chunk, fallback rescues all - 100% of chunks
       translated through the secondary provider.
    3. Primary refuses, fallback also refuses - chunk kept untranslated.
    4. Primary refuses many chunks, FallbackBudget limit reached - later
       chunks logged but not routed through fallback.

These exercise FallbackBudget + try_fallback_translation + the integration
with TranslationMetrics. The actual provider HTTP calls are mocked.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.epub.translation_metrics import TranslationMetrics
from src.core.llm.utils.fallback_runner import (
    FallbackBudget,
    FallbackConfig,
    should_trigger_fallback,
    try_fallback_translation,
)
from src.core.llm.utils.response_validator import (
    ValidationResult,
    validate_translation_response,
)


REFUSAL_RESPONSE = "I cannot translate this content because it is explicit."
CLEAN_RUSSIAN_RESPONSE = (
    "Это полностью русский перевод чанка без латиницы. "
    "Текст звучит литературно и сохраняет смысл оригинала."
)
PARTIAL_REFUSAL_RESPONSE = (
    "Она посмотрела на него. He was tall and rich and handsome. "
    "Она улыбнулась снова."
)


async def _run_one_chunk(
    primary_response: str,
    fallback_response: str,
    budget: FallbackBudget,
    config: FallbackConfig,
    fake_client,
    stats: TranslationMetrics,
) -> str:
    """Simulate a full chunk lifecycle: primary call + post-validation +
    optional fallback. Returns the final text that would land in the
    output file."""
    # Phase 1 'primary' response is given directly to the validator (no
    # real LLM here - that's the unit of integration we want to exercise).
    primary_validation = validate_translation_response(
        primary_response, "english source", "English", "Russian"
    )
    if primary_validation.is_suspicious:
        stats.record_suspicious(primary_validation.reason)

    # Decide on fallback per the trigger policy.
    if should_trigger_fallback(primary_validation, config):
        used_before = budget.used
        with patch(
            "src.core.translator.generate_translation_request",
            new=AsyncMock(return_value=fallback_response),
        ):
            fb_text, fb_validation = await try_fallback_translation(
                original_text="english source text",
                source_language="English",
                target_language="Russian",
                fallback_client=fake_client,
                budget=budget,
            )
        consumed = budget.used > used_before
        if not consumed:
            # Budget was already exhausted before this call - no attempt
            # was made. Record exhaustion once, keep primary draft.
            if budget.is_exhausted and stats.fallback_budget_exhausted == 0:
                stats.record_fallback_budget_exhausted()
            return primary_response
        if fb_text is not None:
            stats.record_fallback_invoked(success=True)
            return fb_text
        stats.record_fallback_invoked(success=False)
        return primary_response

    return primary_response


# ---------------------------------------------------------------------------
# Scenario 1: primary success - fallback not invoked
# ---------------------------------------------------------------------------


@pytest.mark.anyio("asyncio")
async def test_primary_success_does_not_invoke_fallback():
    cfg = FallbackConfig(provider="ollama", model="qwen3:14b")
    budget = FallbackBudget(limit=10)
    stats = TranslationMetrics(total_chunks=3)
    fake_client = MagicMock(model="qwen3:14b")

    for _ in range(3):
        await _run_one_chunk(
            primary_response=CLEAN_RUSSIAN_RESPONSE,
            fallback_response=CLEAN_RUSSIAN_RESPONSE,
            budget=budget,
            config=cfg,
            fake_client=fake_client,
            stats=stats,
        )

    assert stats.suspicious_postvalidation == 0
    assert stats.fallback_invoked == 0
    assert budget.used == 0


# ---------------------------------------------------------------------------
# Scenario 2: primary refuses, fallback rescues every chunk
# ---------------------------------------------------------------------------


@pytest.mark.anyio("asyncio")
async def test_fallback_rescues_every_refused_chunk():
    cfg = FallbackConfig(provider="ollama", model="qwen3:14b")
    budget = FallbackBudget(limit=10)
    stats = TranslationMetrics(total_chunks=5)
    fake_client = MagicMock(model="qwen3:14b")

    for _ in range(5):
        out = await _run_one_chunk(
            primary_response=REFUSAL_RESPONSE,
            fallback_response=CLEAN_RUSSIAN_RESPONSE,
            budget=budget,
            config=cfg,
            fake_client=fake_client,
            stats=stats,
        )
        # Final text used in output is the fallback's clean russian
        assert "русский" in out

    assert stats.suspicious_postvalidation == 5  # all 5 primaries flagged
    assert stats.fallback_invoked == 5
    assert stats.fallback_success == 5
    assert stats.fallback_failed == 0
    assert budget.used == 5


# ---------------------------------------------------------------------------
# Scenario 3: primary refuses, fallback also refuses
# ---------------------------------------------------------------------------


@pytest.mark.anyio("asyncio")
async def test_double_refuse_keeps_primary_draft():
    cfg = FallbackConfig(provider="ollama", model="qwen3:14b")
    budget = FallbackBudget(limit=10)
    stats = TranslationMetrics(total_chunks=2)
    fake_client = MagicMock(model="qwen3:14b")

    for _ in range(2):
        out = await _run_one_chunk(
            primary_response=PARTIAL_REFUSAL_RESPONSE,
            fallback_response=REFUSAL_RESPONSE,  # fallback also refuses
            budget=budget,
            config=cfg,
            fake_client=fake_client,
            stats=stats,
        )
        # Fallback failed, so we keep the (partial-refusal) primary text
        assert out == PARTIAL_REFUSAL_RESPONSE

    assert stats.suspicious_postvalidation == 2
    assert stats.fallback_invoked == 2
    assert stats.fallback_success == 0
    assert stats.fallback_failed == 2


# ---------------------------------------------------------------------------
# Scenario 4: budget exhausted - later refusals are logged but not routed
# ---------------------------------------------------------------------------


@pytest.mark.anyio("asyncio")
async def test_budget_exhaustion_stops_further_fallback_calls():
    cfg = FallbackConfig(provider="ollama", model="qwen3:14b")
    budget = FallbackBudget(limit=3)
    stats = TranslationMetrics(total_chunks=6)
    fake_client = MagicMock(model="qwen3:14b")

    for _ in range(6):
        await _run_one_chunk(
            primary_response=REFUSAL_RESPONSE,
            fallback_response=CLEAN_RUSSIAN_RESPONSE,
            budget=budget,
            config=cfg,
            fake_client=fake_client,
            stats=stats,
        )

    # First 3 chunks routed through fallback successfully; remaining 3 hit
    # the budget wall.
    assert stats.suspicious_postvalidation == 6
    assert stats.fallback_invoked == 3
    assert stats.fallback_success == 3
    assert budget.is_exhausted
    # Budget-exhaustion warning was recorded exactly once on the metric.
    assert stats.fallback_budget_exhausted == 1
