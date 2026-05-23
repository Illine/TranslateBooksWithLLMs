"""
Post-validation of LLM translation responses.

Detects three classes of silent translation failure that pass earlier checks
(non-empty content, extracted between TRANSLATE_TAG_IN/OUT, valid placeholders):

    1. High proportion of source-script text in the output. For latin-source
       to non-latin-target pairs, latin in the output beyond a small share of
       proper names is a strong signal of a partial refusal.
    2. Refusal markers in the output prefix ("I cannot", "I'm sorry", "as an
       AI", ...). Match only when the surrounding text is mostly latin to
       avoid false positives on legitimate quoted english speech.
    3. Echo of the input - the model returned the source text instead of a
       translation. Detected via 5-word shingles.

Designed to run on already-extracted translation text (without TRANSLATE
tags), called from translator/xhtml_translator/subtitle_translator call sites
which know source_language and target_language. The validator does not see
provider configuration and does not retry - it returns a ValidationResult
and lets callers decide what to do.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Optional

# Script classification by unicode block.
_SCRIPT_PATTERNS = {
    "latin": re.compile(r"[A-Za-z]"),
    "cyrillic": re.compile(r"[Ѐ-ӿԀ-ԯ]"),
    "cjk": re.compile(
        r"[一-鿿㐀-䶿぀-ゟ゠-ヿ가-힯]"
    ),
    "arabic": re.compile(r"[؀-ۿݐ-ݿ]"),
    "hebrew": re.compile(r"[֐-׿]"),
    "greek": re.compile(r"[Ͱ-Ͽ]"),
    "devanagari": re.compile(r"[ऀ-ॿ]"),
    "thai": re.compile(r"[฀-๿]"),
}

# Map human-readable language names (as passed through the pipeline) to a
# script tag. Names mirror what prompts.py uses by default. Unknown languages
# return None and skip latin-ratio checks.
_LANGUAGE_SCRIPT = {
    # Latin-script languages
    "english": "latin",
    "french": "latin",
    "spanish": "latin",
    "italian": "latin",
    "german": "latin",
    "portuguese": "latin",
    "dutch": "latin",
    "polish": "latin",
    "romanian": "latin",
    "czech": "latin",
    "slovak": "latin",
    "hungarian": "latin",
    "swedish": "latin",
    "norwegian": "latin",
    "danish": "latin",
    "finnish": "latin",
    "estonian": "latin",
    "latvian": "latin",
    "lithuanian": "latin",
    "croatian": "latin",
    "slovenian": "latin",
    "vietnamese": "latin",
    "turkish": "latin",
    "indonesian": "latin",
    "malay": "latin",
    "filipino": "latin",
    "tagalog": "latin",
    "swahili": "latin",
    # Cyrillic
    "russian": "cyrillic",
    "ukrainian": "cyrillic",
    "bulgarian": "cyrillic",
    "serbian": "cyrillic",
    "belarusian": "cyrillic",
    "macedonian": "cyrillic",
    "kazakh": "cyrillic",
    "kyrgyz": "cyrillic",
    "mongolian": "cyrillic",
    # CJK
    "chinese": "cjk",
    "japanese": "cjk",
    "korean": "cjk",
    # Other non-latin
    "arabic": "arabic",
    "hebrew": "hebrew",
    "greek": "greek",
    "hindi": "devanagari",
    "marathi": "devanagari",
    "sanskrit": "devanagari",
    "thai": "thai",
}

# Refusal markers - case-insensitive, matched only in the first chars of the
# response. Patterns are conservative: a generic "I cannot" alone would false-
# positive on quoted dialogue, so we require the phrase to start the response
# or follow whitespace.
_REFUSAL_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\bI cannot\b",
        r"\bI can'?t\b",
        r"\bI am not able\b",
        r"\bI'?m not able\b",
        r"\bI'?m unable\b",
        r"\bI won'?t\b",
        r"\bI will not\b",
        r"\bI'?m sorry,?\s+(but )?I\b",
        r"\bI apologi[sz]e,?\s+(but )?I\b",
        r"\bas an AI\b",
        r"\bI don'?t feel comfortable\b",
        r"\bcannot fulfill\b",
        r"\bunable to (help|assist|comply|translate)\b",
        r"\bI'?m programmed to\b",
        r"\bagainst my guidelines\b",
    )
]


@dataclass(frozen=True)
class ValidationConfig:
    """Tunable thresholds for the validator. Loaded from env on first use."""

    enabled: bool = True
    latin_ratio_threshold: float = 0.15
    echo_enabled: bool = True
    echo_ratio_threshold: float = 0.6
    refusal_first_chars: int = 500
    refusal_min_latin_ratio: float = 0.5
    min_words_for_echo: int = 50
    shingle_size: int = 5

    @classmethod
    def from_env(cls) -> "ValidationConfig":
        """Load from env. Only the three high-impact knobs are env-bound;
        the rest (echo threshold, refusal prefix window, shingle size) are
        intentionally hard-coded defaults that cover all observed cases.
        Tune them via the constructor in tests if needed."""
        return cls(
            enabled=_env_bool("RESPONSE_VALIDATION_ENABLED", True),
            latin_ratio_threshold=_env_float(
                "RESPONSE_VALIDATION_LATIN_THRESHOLD", 0.15
            ),
            echo_enabled=_env_bool("RESPONSE_VALIDATION_ECHO_ENABLED", True),
        )


@dataclass
class ValidationResult:
    """Outcome of a single post-validation pass.

    Attributes:
        is_suspicious: True if any rule flagged the response.
        reason: Short tag - "refusal_marker" | "high_latin_ratio" |
            "echo_input" | "ok" | "empty" | "disabled".
        latin_ratio: Share of latin letters among all script letters in the
            translated text. 0.0 if no script letters detected.
        target_script_ratio: Share of expected target-script letters among
            all script letters. 0.0 if target script unknown.
        is_refusal: True if a refusal marker matched.
        is_echo: True if shingle overlap with input crossed echo_threshold.
        matched_refusal_marker: The first refusal pattern that matched, or
            None.
        preview: First 200 characters of the translated text, for log lines.
    """

    is_suspicious: bool
    reason: str
    latin_ratio: float = 0.0
    target_script_ratio: float = 0.0
    is_refusal: bool = False
    is_echo: bool = False
    matched_refusal_marker: Optional[str] = None
    preview: str = ""


def validate_translation_response(
    translated_text: str,
    original_text: str,
    source_language: str,
    target_language: str,
    config: Optional[ValidationConfig] = None,
) -> ValidationResult:
    """Run all post-validation rules and return the worst-finding result.

    Args:
        translated_text: Text extracted from the LLM response (without
            TRANSLATE_TAG markers and without placeholders mattering).
        original_text: The source chunk that was sent for translation.
        source_language: Human-readable source language name (e.g. "English").
        target_language: Human-readable target language name (e.g. "Russian").
        config: Optional ValidationConfig. Defaults to ValidationConfig.from_env().

    Returns:
        ValidationResult describing what was found. Callers decide whether to
        warn, count, retry, or invoke a fallback provider.
    """
    cfg = config or ValidationConfig.from_env()

    if not cfg.enabled:
        return ValidationResult(is_suspicious=False, reason="disabled")

    if not translated_text or not translated_text.strip():
        return ValidationResult(is_suspicious=False, reason="empty")

    preview = translated_text[:200]
    src_script = _script_of(source_language)
    tgt_script = _script_of(target_language)

    latin_ratio, target_ratio = _script_ratios(translated_text, tgt_script)

    # Rule 1: latin in the output for latin-source -> non-latin-target pairs.
    latin_check_applies = (
        src_script == "latin"
        and tgt_script is not None
        and tgt_script != "latin"
    )
    high_latin = latin_check_applies and latin_ratio > cfg.latin_ratio_threshold

    # Rule 2: refusal marker. Only meaningful when the surrounding text is
    # predominantly latin AND the expected target is non-latin - a russian
    # translation that contains the word "cannot" inside a quoted english
    # phrase is not a refusal, but a russian response that is mostly latin
    # and contains "I cannot" is. This works for both first-pass (en->ru)
    # and refine (ru->ru) callers because the trigger depends on the target
    # script, not on the source.
    matched_marker = _find_refusal_marker(
        translated_text[: cfg.refusal_first_chars]
    )
    target_non_latin = tgt_script is not None and tgt_script != "latin"
    is_refusal = (
        matched_marker is not None
        and latin_ratio >= cfg.refusal_min_latin_ratio
        and target_non_latin
    )

    # Rule 3: echo - the response repeats input shingles.
    is_echo = False
    if cfg.echo_enabled:
        is_echo = _is_echo(
            translated_text,
            original_text,
            cfg.shingle_size,
            cfg.echo_ratio_threshold,
            cfg.min_words_for_echo,
        )

    # Resolve the dominant reason in order of severity.
    if is_refusal:
        reason = "refusal_marker"
        suspicious = True
    elif high_latin:
        reason = "high_latin_ratio"
        suspicious = True
    elif is_echo:
        reason = "echo_input"
        suspicious = True
    else:
        reason = "ok"
        suspicious = False

    return ValidationResult(
        is_suspicious=suspicious,
        reason=reason,
        latin_ratio=latin_ratio,
        target_script_ratio=target_ratio,
        is_refusal=is_refusal,
        is_echo=is_echo,
        matched_refusal_marker=matched_marker,
        preview=preview,
    )


def format_validation_warning(result: ValidationResult, chunk_label: str) -> str:
    """Render a uniform single-line warning for a suspicious result.

    Returns a stable string format so log greps work across call sites
    (xhtml_translator, translator, subtitle_translator). Returns an empty
    string for non-suspicious results.
    """
    if not result.is_suspicious:
        return ""
    marker = (
        f", marker=\"{result.matched_refusal_marker}\""
        if result.matched_refusal_marker else ""
    )
    # Use plain string interpolation for preview so cyrillic/CJK text
    # renders natively in logs instead of escape-encoded.
    preview = result.preview.replace("\n", " ").strip()
    return (
        f"⚠️ Post-validation flagged {chunk_label}: reason={result.reason}, "
        f"latin_ratio={result.latin_ratio:.2f}, "
        f"target_ratio={result.target_script_ratio:.2f}{marker}. "
        f"Preview: \"{preview}\""
    )


def _script_of(language: Optional[str]) -> Optional[str]:
    if not language:
        return None
    return _LANGUAGE_SCRIPT.get(language.strip().lower())


def _script_ratios(text: str, target_script: Optional[str]) -> tuple[float, float]:
    """Return (latin_ratio, target_script_ratio) over total script letters.

    Letters from any known script form the denominator. Digits and
    punctuation are ignored so a short caption like "1.2.3" does not skew
    the ratio.
    """
    counts = {name: len(pattern.findall(text)) for name, pattern in _SCRIPT_PATTERNS.items()}
    total = sum(counts.values())
    if total == 0:
        return 0.0, 0.0
    latin = counts.get("latin", 0) / total
    target = counts.get(target_script, 0) / total if target_script else 0.0
    return latin, target


def _find_refusal_marker(text_prefix: str) -> Optional[str]:
    for pattern in _REFUSAL_PATTERNS:
        match = pattern.search(text_prefix)
        if match:
            return match.group(0)
    return None


def _is_echo(
    translated: str,
    original: str,
    shingle_size: int,
    threshold: float,
    min_words: int,
) -> bool:
    """Check shingle overlap of original in translated."""
    orig_words = _normalize_words(original)
    if len(orig_words) < min_words:
        return False
    trans_words = _normalize_words(translated)
    if len(trans_words) < shingle_size:
        return False

    orig_shingles = _shingles(orig_words, shingle_size)
    if not orig_shingles:
        return False

    trans_shingle_set = set(_shingles(trans_words, shingle_size))
    matched = sum(1 for s in orig_shingles if s in trans_shingle_set)
    return matched / len(orig_shingles) > threshold


_WORD_RE = re.compile(r"[\w]+", re.UNICODE)


def _normalize_words(text: str) -> list[str]:
    return [w.lower() for w in _WORD_RE.findall(text)]


def _shingles(words: list[str], n: int) -> list[tuple[str, ...]]:
    if len(words) < n:
        return []
    return [tuple(words[i : i + n]) for i in range(len(words) - n + 1)]


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default
