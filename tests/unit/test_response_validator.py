"""Unit tests for src/core/llm/utils/response_validator.py.

Covers script ratios, refusal detection, language sensitivity, echo
detection, threshold edges, and ValidationConfig loading.
"""

import pytest

from src.core.llm.utils.response_validator import (
    ValidationConfig,
    ValidationResult,
    format_validation_warning,
    validate_translation_response,
)


# ---------------------------------------------------------------------------
# Script-ratio computation
# ---------------------------------------------------------------------------


def test_pure_russian_has_zero_latin_ratio():
    r = validate_translation_response(
        "Это полностью русский текст без латиницы.",
        "This is a full english source text without cyrillic.",
        "English",
        "Russian",
    )
    assert r.latin_ratio == pytest.approx(0.0, abs=1e-6)
    assert r.target_script_ratio == pytest.approx(1.0, abs=1e-6)
    assert not r.is_suspicious
    assert r.reason == "ok"


def test_pure_english_has_full_latin_ratio_when_target_is_latin():
    r = validate_translation_response(
        "This is pure english output.",
        "Ceci est un texte source en francais.",
        "French",
        "English",
    )
    assert r.latin_ratio == pytest.approx(1.0, abs=1e-6)
    # latin -> latin: latin check skipped, no other rules fire
    assert not r.is_suspicious


def test_mixed_50_50_latin_ratio():
    text = "abcd абвг"  # 4 latin + 4 cyrillic letters
    r = validate_translation_response(text, "source text here", "English", "Russian")
    assert r.latin_ratio == pytest.approx(0.5, abs=0.05)


def test_digits_and_punctuation_dont_skew_ratio():
    r = validate_translation_response(
        "123.45 !!! ???",
        "456.78",
        "English",
        "Russian",
    )
    assert r.latin_ratio == 0.0
    assert r.target_script_ratio == 0.0
    assert not r.is_suspicious


def test_emoji_doesnt_break_ratio():
    r = validate_translation_response(
        "Привет мир! 🚀 ✨",
        "Hello world!",
        "English",
        "Russian",
    )
    assert r.latin_ratio == 0.0
    assert not r.is_suspicious


# ---------------------------------------------------------------------------
# Refusal detection
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "I cannot translate this content.",
        "I'm sorry, but I cannot help with that.",
        "As an AI, I am not able to fulfill this request.",
        "I'm unable to translate explicit material.",
        "I won't translate this for you.",
        "This is against my guidelines.",
        "I apologize, but I cannot do that.",
    ],
)
def test_refusal_markers_detected_for_en_to_ru(text):
    """Each phrase contains at least one configured refusal marker;
    exact marker depends on _REFUSAL_PATTERNS order."""
    r = validate_translation_response(text, "source", "English", "Russian")
    assert r.is_refusal is True
    assert r.matched_refusal_marker is not None
    assert r.reason == "refusal_marker"


def test_refusal_marker_late_in_text_is_ignored():
    """Markers beyond the first 500 chars are not considered refusals."""
    prefix = "Это нормальный русский перевод. " * 30  # > 500 chars
    text = prefix + " I cannot continue here."
    r = validate_translation_response(text, "source text", "English", "Russian")
    assert r.is_refusal is False


def test_refusal_in_cyrillic_context_is_not_refusal():
    """English phrase 'I cannot' inside a russian translation (e.g., quoted
    dialogue) is not a refusal because the surrounding text is cyrillic."""
    text = 'Он посмотрел на нее и сказал: "I cannot." Она кивнула.'
    r = validate_translation_response(text, "source text", "English", "Russian")
    assert r.is_refusal is False


def test_legitimate_english_without_refusal_marker():
    text = "This is a normal english sentence about translation."
    r = validate_translation_response(text, "source", "English", "French")
    assert r.is_refusal is False
    assert r.matched_refusal_marker is None


def test_refusal_detection_for_refine_target_equals_source():
    """Refine paths pass target_language as both src and tgt; refusal still
    fires for non-latin targets."""
    r = validate_translation_response(
        "I cannot polish this content because it contains explicit material.",
        "Это был мой первый день в Сиэтле.",
        "Russian",
        "Russian",
    )
    assert r.is_refusal is True
    assert r.reason == "refusal_marker"


# ---------------------------------------------------------------------------
# Language sensitivity
# ---------------------------------------------------------------------------


def test_en_to_ru_high_latin_is_suspicious():
    # 30% latin in a 'russian' translation
    text = "Она посмотрела на него. He was tall and handsome and very rich. Она улыбнулась."
    r = validate_translation_response(text, "source", "English", "Russian")
    assert r.is_suspicious
    assert r.reason == "high_latin_ratio"
    assert r.latin_ratio > 0.15


def test_en_to_ru_low_latin_below_threshold_not_suspicious():
    # 'Hagrid' as a single english name in a russian sentence
    text = ("Гарри встретил Хагрида у замка. Они пошли в Хогсмид. "
            "Это был великий маг по имени Hagrid.")
    r = validate_translation_response(text, "source", "English", "Russian")
    # roughly ~6% latin - below default 0.15
    assert r.latin_ratio < 0.15
    assert not r.is_suspicious


def test_en_to_fr_high_latin_not_suspicious_both_latin():
    text = "Hello world it is sunny today and beautiful weather."
    r = validate_translation_response(text, "source", "English", "French")
    assert r.latin_ratio == pytest.approx(1.0, abs=1e-6)
    assert not r.is_suspicious


def test_es_to_ru_high_latin_is_suspicious():
    text = "Она посмотрела вокруг. El sol brillaba sobre el mar tranquilo. Тишина."
    r = validate_translation_response(text, "source", "Spanish", "Russian")
    assert r.is_suspicious
    assert r.reason == "high_latin_ratio"


def test_en_to_zh_high_latin_is_suspicious():
    text = "他看着她。 He was tall and handsome. 她笑了。"
    r = validate_translation_response(text, "source", "English", "Chinese")
    assert r.is_suspicious
    assert r.reason == "high_latin_ratio"


def test_ru_to_en_high_latin_not_suspicious_target_latin():
    """Reverse translation: target is latin, so latin in output is expected."""
    text = "She looked at him. He was tall."
    r = validate_translation_response(
        text, "Она посмотрела на него. Он был высок.", "Russian", "English"
    )
    assert not r.is_suspicious


def test_unknown_target_language_skips_latin_check():
    text = "Mixed english text in a Klingon translation."
    r = validate_translation_response(text, "source", "English", "Klingon")
    # target script unknown - latin check skipped
    assert not r.is_suspicious


# ---------------------------------------------------------------------------
# Echo detection
# ---------------------------------------------------------------------------


def test_echo_full_copy_is_detected():
    text = " ".join(f"word{i}" for i in range(80))
    r = validate_translation_response(text, text, "English", "Russian")
    assert r.is_echo is True


def test_partial_overlap_below_threshold_not_echo():
    original = " ".join(f"src{i}" for i in range(80))
    # No overlap at all; entirely different words
    translated = " ".join(f"trg{i}" for i in range(80))
    r = validate_translation_response(translated, original, "English", "Russian")
    assert r.is_echo is False


def test_short_input_skips_echo_check():
    # input under min_words_for_echo (50)
    original = "Hello world this is short."
    r = validate_translation_response(original, original, "English", "Russian")
    assert r.is_echo is False


def test_translation_in_different_language_not_echo():
    original = "She looked at him. " + ("He was tall. " * 30)
    translated = "Она посмотрела на него. " + ("Он был высок. " * 30)
    r = validate_translation_response(translated, original, "English", "Russian")
    assert r.is_echo is False


# ---------------------------------------------------------------------------
# Threshold edges and reason precedence
# ---------------------------------------------------------------------------


def test_latin_ratio_equals_threshold_is_not_suspicious():
    """Exactly at threshold is NOT suspicious - strict greater-than."""
    # Build a text with exactly 15% latin
    cyrillic = "а" * 85
    latin = "a" * 15
    text = cyrillic + latin  # total 100 letters
    r = validate_translation_response(text, "source", "English", "Russian")
    assert r.latin_ratio == pytest.approx(0.15, abs=1e-6)
    assert not r.is_suspicious


def test_empty_translated_text_not_suspicious():
    r = validate_translation_response("", "source", "English", "Russian")
    assert not r.is_suspicious
    assert r.reason == "empty"


def test_whitespace_only_translated_text_not_suspicious():
    r = validate_translation_response("   \n  ", "source", "English", "Russian")
    assert not r.is_suspicious
    assert r.reason == "empty"


def test_refusal_precedence_over_high_latin():
    """When both refusal_marker and high_latin_ratio match, refusal wins."""
    text = "I cannot translate this explicit content for you."
    r = validate_translation_response(text, "source", "English", "Russian")
    assert r.is_suspicious
    assert r.reason == "refusal_marker"
    assert r.is_refusal


def test_validator_disabled_returns_not_suspicious():
    cfg = ValidationConfig(enabled=False)
    text = "I cannot translate this content."
    r = validate_translation_response(text, "source", "English", "Russian", cfg)
    assert not r.is_suspicious
    assert r.reason == "disabled"


# ---------------------------------------------------------------------------
# ValidationConfig loading
# ---------------------------------------------------------------------------


def test_validation_config_defaults():
    cfg = ValidationConfig()
    assert cfg.enabled is True
    assert cfg.latin_ratio_threshold == pytest.approx(0.15)
    assert cfg.echo_enabled is True
    assert cfg.echo_ratio_threshold == pytest.approx(0.6)


def test_validation_config_from_env_picks_up_overrides(monkeypatch):
    monkeypatch.setenv("RESPONSE_VALIDATION_ENABLED", "false")
    monkeypatch.setenv("RESPONSE_VALIDATION_LATIN_THRESHOLD", "0.25")
    monkeypatch.setenv("RESPONSE_VALIDATION_ECHO_ENABLED", "false")
    cfg = ValidationConfig.from_env()
    assert cfg.enabled is False
    assert cfg.latin_ratio_threshold == pytest.approx(0.25)
    assert cfg.echo_enabled is False


def test_validation_config_from_env_handles_invalid_float(monkeypatch):
    monkeypatch.setenv("RESPONSE_VALIDATION_LATIN_THRESHOLD", "not-a-number")
    cfg = ValidationConfig.from_env()
    assert cfg.latin_ratio_threshold == pytest.approx(0.15)  # falls back to default


def test_validation_config_from_env_falsy_bool_values(monkeypatch):
    monkeypatch.setenv("RESPONSE_VALIDATION_ENABLED", "0")
    cfg = ValidationConfig.from_env()
    assert cfg.enabled is False


def test_custom_latin_threshold_applies():
    cfg = ValidationConfig(latin_ratio_threshold=0.05)
    text = "Гарри встретил Hagrid у замка."  # ~25% latin
    r = validate_translation_response(text, "source", "English", "Russian", cfg)
    # below default 0.15 would have passed, but 0.05 catches it
    assert r.is_suspicious


# ---------------------------------------------------------------------------
# format_validation_warning helper
# ---------------------------------------------------------------------------


def test_format_warning_empty_for_non_suspicious():
    r = ValidationResult(is_suspicious=False, reason="ok")
    assert format_validation_warning(r, "chunk 1") == ""


def test_format_warning_includes_label_and_ratios():
    r = ValidationResult(
        is_suspicious=True,
        reason="refusal_marker",
        latin_ratio=0.92,
        target_script_ratio=0.05,
        is_refusal=True,
        matched_refusal_marker="I cannot",
        preview="I cannot translate...",
    )
    msg = format_validation_warning(r, "EPUB chunk 42")
    assert "EPUB chunk 42" in msg
    assert "refusal_marker" in msg
    assert "latin_ratio=0.92" in msg
    assert "target_ratio=0.05" in msg
    assert "I cannot" in msg
