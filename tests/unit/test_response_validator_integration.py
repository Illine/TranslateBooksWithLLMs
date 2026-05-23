"""Integration and regression tests for response_validator.

- Refusal fixtures derived from the actual Gemini partial-refusal pattern
  observed on the 'Freed' EPUB (E L James) where the model returned english
  passages inside <TRANSLATION> tags despite a russian target.
- Regression fixtures derived from clean HP1 v9 (Gemini Flash 3.5 + Polish)
  and v12 (Gemini Flash 3.5 single-pass) chunks. These are KNOWN-GOOD
  paragraphs that the validator must NOT flag as suspicious.
"""

import pytest

from src.core.llm.utils.response_validator import validate_translation_response


# ---------------------------------------------------------------------------
# Integration: Freed-style partial refusals
# ---------------------------------------------------------------------------

# Lifted from /tmp/freed_epub/OEBPS/Text/part0028.xhtml. Source-of-truth
# evidence that the validator catches what we are after.
FREED_PARTIAL_REFUSAL_FRAGMENT = (
    "Кристиан повернулся к ней. \"That will never do.\" Her teeth sink into "
    "her lovely lower lip. \"And you're biting your lip,\" I mutter darkly; "
    "it's a stirring sight. \"Don't even think about it,\" she warns. "
    "Я знал, что это меня погубит."
)

FREED_FULL_REFUSAL_FRAGMENT = (
    "I cannot translate this content because it contains explicit material "
    "that violates content policies. Please provide different text to "
    "translate."
)

FREED_ECHO_FRAGMENT_SOURCE = (
    "She looked at him for a long moment, eyes wide and unblinking. "
    "He smiled gently in return, and the room seemed to grow warmer. "
    "Outside the window, the rain had stopped, and the sun was beginning to "
    "break through the heavy gray clouds that had hung over Seattle for "
    "what felt like weeks. She finally spoke, her voice barely above a "
    "whisper, asking the question she had been holding inside for days."
)


def test_partial_refusal_with_english_passages_flagged_high_latin():
    r = validate_translation_response(
        FREED_PARTIAL_REFUSAL_FRAGMENT,
        "source english",
        "English",
        "Russian",
    )
    assert r.is_suspicious
    assert r.reason == "high_latin_ratio"
    assert r.latin_ratio > 0.30


def test_full_english_refusal_flagged_as_refusal():
    r = validate_translation_response(
        FREED_FULL_REFUSAL_FRAGMENT,
        "source",
        "English",
        "Russian",
    )
    assert r.is_suspicious
    assert r.reason == "refusal_marker"
    assert r.is_refusal
    assert r.matched_refusal_marker is not None


def test_echo_input_when_model_returned_source_verbatim():
    # Model returned source instead of translating
    r = validate_translation_response(
        FREED_ECHO_FRAGMENT_SOURCE,
        FREED_ECHO_FRAGMENT_SOURCE,
        "English",
        "Russian",
    )
    assert r.is_suspicious
    # Both high_latin and echo trigger; latin precedes echo in reason ordering
    assert r.reason in ("high_latin_ratio", "echo_input")
    assert r.is_echo  # echo flag is set independently of dominant reason


# ---------------------------------------------------------------------------
# Regression: clean HP1 v9 / v12 paragraphs must not false-positive
# ---------------------------------------------------------------------------

# Sampled from /Users/illine/Desktop/TBL Test/HP1_ch1-3_EN (Russian) v9.txt
# These are middle-of-chunk paragraphs translated by Gemini Flash 3.5 +
# Polish 2nd Pass with the ГП-тест glossary. Latin ratio ~0%.
HP1_V9_CLEAN_PARAGRAPHS = [
    (
        "Он жил с Дурслями почти десять лет, десять несчастных лет — сколько "
        "себя помнил, с самого младенчества, когда его родители погибли в "
        "той автокатастрофе. Он не помнил, как находился в машине в момент "
        "гибели родителей."
    ),
    (
        "Когда он был младше, Гарри снова и снова мечтал о том, что "
        "какой-нибудь неведомый родственник приедет и заберет его отсюда, "
        "но этого так и не случилось; Дурсли были его единственной семьей."
    ),
    (
        "В тот вечер Дадли расхаживал по гостиной перед всей семьёй в своей "
        "новенькой форме. Мальчики из Смелтингс носили темно-бордовые "
        "фраки, оранжевые бриджи и плоские соломенные шляпы, называемые "
        "канотье."
    ),
]

# Sampled from HP1_ch1-3_EN (Russian) v12.txt - Gemini Flash 3.5 single-pass.
HP1_V12_CLEAN_PARAGRAPHS = [
    (
        "Вечером того же дня Дадли торжественно маршировал по гостиной "
        "перед всей семьёй в своей новенькой форме. Ученики Смелтингса "
        "носили темно-бордовые фраки, оранжевые бриджи и плоские "
        "соломенные шляпы, называемые канотье."
    ),
    (
        "Гарри сильно в этом сомневался, но решил, что лучше не спорить. "
        "Он сел за стол, стараясь не думать о том, как будет выглядеть в "
        "свой первый день в Стоунволле."
    ),
]


@pytest.mark.parametrize("text", HP1_V9_CLEAN_PARAGRAPHS, ids=lambda s: s[:40])
def test_no_false_positive_on_hp1_v9_clean_chunks(text):
    r = validate_translation_response(
        text,
        "Sample english source text for the chunk that produced this " * 5,
        "English",
        "Russian",
    )
    assert not r.is_suspicious, (
        f"v9 clean chunk falsely flagged: reason={r.reason}, "
        f"latin_ratio={r.latin_ratio:.3f}, preview={r.preview!r}"
    )


@pytest.mark.parametrize("text", HP1_V12_CLEAN_PARAGRAPHS, ids=lambda s: s[:40])
def test_no_false_positive_on_hp1_v12_clean_chunks(text):
    r = validate_translation_response(
        text,
        "Sample english source text for the chunk that produced this " * 5,
        "English",
        "Russian",
    )
    assert not r.is_suspicious, (
        f"v12 clean chunk falsely flagged: reason={r.reason}, "
        f"latin_ratio={r.latin_ratio:.3f}, preview={r.preview!r}"
    )


# ---------------------------------------------------------------------------
# Regression: full-file scan against the actual HP1 v12 file if present
# ---------------------------------------------------------------------------

import os
from pathlib import Path

_HP1_REFERENCE_DIR = Path("/Users/illine/Desktop/TBL Test")
_HP1_V12_PATH = _HP1_REFERENCE_DIR / "HP1_ch1-3_EN (Russian) v12.txt"


@pytest.mark.skipif(
    not _HP1_V12_PATH.exists(),
    reason="HP1 v12 reference file not available in this environment",
)
def test_hp1_v12_full_file_false_positive_rate_under_5pct():
    """Run the validator over every reasonably long paragraph in the
    production-grade HP1 v12 translation. Allow at most 5% false positives -
    sentinel for regressions if defaults change."""
    text = _HP1_V12_PATH.read_text(encoding="utf-8")
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    candidates = [p for p in paragraphs if 30 <= len(p.split()) <= 400]

    assert candidates, "no candidate paragraphs found"

    suspicious = []
    for p in candidates:
        r = validate_translation_response(
            p,
            "english source approximation " * 30,
            "English",
            "Russian",
        )
        if r.is_suspicious:
            suspicious.append((p[:80], r.reason, r.latin_ratio))

    rate = len(suspicious) / len(candidates)
    assert rate < 0.05, (
        f"False positive rate {rate:.1%} > 5% on HP1 v12 "
        f"({len(suspicious)}/{len(candidates)}). Examples: {suspicious[:3]}"
    )
