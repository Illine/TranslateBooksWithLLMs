"""Detector for Gemini thinking-capable model families."""

import pytest

from src.core.llm.providers.gemini import GeminiProvider


def _provider(model: str) -> GeminiProvider:
    # __init__ pulls in config + KeyPool; we only need .model on the instance.
    provider = GeminiProvider.__new__(GeminiProvider)
    provider.model = model
    return provider


@pytest.mark.parametrize(
    "model,expected",
    [
        ("gemini-1.0-pro", False),
        ("gemini-1.5-flash", False),
        ("gemini-1.5-pro", False),
        ("gemini-2.0-flash", False),
        ("gemini-2.0-flash-exp", False),
        ("gemini-2.5-flash", True),
        ("gemini-2.5-pro", True),
        ("gemini-2.5-flash-lite", True),
        ("gemini-3-flash-preview", True),
        ("gemini-3.0-flash", True),
        ("gemini-3.1-flash-lite", True),
        ("gemini-3.5-flash", True),
        ("gemini-4-pro", True),
        ("gemini-9-flash", True),
        ("gemini-10-flash", True),
    ],
)
def test_is_thinking_model(model, expected):
    assert _provider(model)._is_thinking_model() is expected


def test_get_thinking_config_disables_for_thinking_models():
    assert _provider("gemini-3.5-flash")._get_thinking_config() == {
        "thinkingConfig": {"thinkingBudget": 0}
    }


def test_get_thinking_config_empty_for_legacy_models():
    assert _provider("gemini-2.0-flash")._get_thinking_config() == {}
