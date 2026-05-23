"""
LLM Utility Modules

Shared utilities used across multiple providers.

Components:
    - extraction: Translation extraction from LLM responses
    - context_detection: Model context size detection
    - response_validator: Post-validation of translated responses
"""

from .context_detection import ContextDetector
from .response_validator import (
    ValidationConfig,
    ValidationResult,
    format_validation_warning,
    validate_translation_response,
)
from .fallback_runner import (
    FallbackBudget,
    FallbackConfig,
    build_fallback_client,
    should_trigger_fallback,
    try_fallback_translation,
)

__all__ = [
    'ContextDetector',
    'ValidationConfig',
    'ValidationResult',
    'format_validation_warning',
    'validate_translation_response',
    'FallbackBudget',
    'FallbackConfig',
    'build_fallback_client',
    'should_trigger_fallback',
    'try_fallback_translation',
]
