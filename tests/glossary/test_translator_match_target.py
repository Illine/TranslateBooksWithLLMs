"""
Unit tests for `_build_chunk_glossary_block(match_target=...)`.

Validates the match-target routing for the refine pass and the diagnostic
WARN that fires when the source-side filter would have matched but the
target-side filter did not.
"""
from src.core.translator import _build_chunk_glossary_block
from src.core.glossary.models import GlossaryConfig


def _options(terms, config=None):
    opts = {"glossary_terms": terms}
    if config is not None:
        opts["glossary_config"] = config
    return opts


class TestMatchTargetRouting:
    def test_default_uses_source_filter(self):
        """Without `match_target`, the source-side filter is used. On a target-
        language chunk it should produce no glossary block."""
        opts = _options({"Voldemort": "Волдеморт"})

        block = _build_chunk_glossary_block("Гарри увидел Волдеморта.", opts)

        assert block == ""

    def test_match_target_renders_block_on_target_chunk(self):
        opts = _options({"Voldemort": "Волдеморт|Волдеморта"})

        block = _build_chunk_glossary_block(
            "Гарри увидел Волдеморта.", opts, match_target=True
        )

        assert "Voldemort" in block
        assert "Волдеморт" in block

    def test_match_target_skips_terms_absent_from_draft(self):
        """Only terms whose target form is present in the draft should make it
        into the rendered block - the refine pass does not need every term."""
        opts = _options({
            "Voldemort": "Волдеморт",
            "Dumbledore": "Дамблдор",
        })

        block = _build_chunk_glossary_block(
            "Гарри встретил Волдеморт.", opts, match_target=True
        )

        assert "Voldemort" in block
        assert "Dumbledore" not in block


class TestTargetMatchEmptyWarning:
    def test_warning_fires_when_source_would_match_but_target_does_not(self):
        """The canonical INFRA-11 regression: target lacks inflected `|`-alts,
        target-side filter returns empty, source-side filter would have caught
        the term -> WARN."""
        captured = []

        def callback(event, message, **kwargs):
            captured.append((event, message))

        opts = _options({"Voldemort": "Волдеморт"})
        runtime_state: dict = {}

        block = _build_chunk_glossary_block(
            "Voldemort entered the hall.",
            opts,
            log_callback=callback,
            runtime_state=runtime_state,
            match_target=True,
        )

        assert block == ""
        assert any(event == "glossary_target_match_empty" for event, _ in captured)
        assert runtime_state.get("glossary_target_warned") is True

    def test_warning_deduped_within_job(self):
        captured = []

        def callback(event, message, **kwargs):
            captured.append(event)

        opts = _options({"Voldemort": "Волдеморт"})
        runtime_state: dict = {}

        for _ in range(3):
            _build_chunk_glossary_block(
                "Voldemort entered the hall.",
                opts,
                log_callback=callback,
                runtime_state=runtime_state,
                match_target=True,
            )

        warns = [e for e in captured if e == "glossary_target_match_empty"]
        assert len(warns) == 1

    def test_no_warning_when_both_sides_empty(self):
        captured = []

        def callback(event, message, **kwargs):
            captured.append(event)

        opts = _options({"Voldemort": "Волдеморт"})

        _build_chunk_glossary_block(
            "The hall was quiet that evening.",
            opts,
            log_callback=callback,
            runtime_state={},
            match_target=True,
        )

        assert "glossary_target_match_empty" not in captured

    def test_no_warning_when_target_matches(self):
        captured = []

        def callback(event, message, **kwargs):
            captured.append(event)

        opts = _options({"Voldemort": "Волдеморт"})

        _build_chunk_glossary_block(
            "Гарри увидел Волдеморт.",
            opts,
            log_callback=callback,
            runtime_state={},
            match_target=True,
        )

        assert "glossary_target_match_empty" not in captured

    def test_no_warning_when_log_callback_is_none(self):
        """Batch scripts without a log callback should not crash and not emit
        any side effect - documented behavior."""
        opts = _options({"Voldemort": "Волдеморт"})
        runtime_state: dict = {}

        block = _build_chunk_glossary_block(
            "Voldemort entered the hall.",
            opts,
            log_callback=None,
            runtime_state=runtime_state,
            match_target=True,
        )

        assert block == ""
        assert "glossary_target_warned" not in runtime_state

    def test_no_warning_in_source_mode_even_if_target_would_miss(self):
        """Translate-pass uses match_target=False and must not emit the refine
        diagnostic regardless of what target-side filter would say."""
        captured = []

        def callback(event, message, **kwargs):
            captured.append(event)

        opts = _options({"Voldemort": "Волдеморт"})

        _build_chunk_glossary_block(
            "Voldemort entered the hall.",
            opts,
            log_callback=callback,
            runtime_state={},
            match_target=False,
        )

        assert "glossary_target_match_empty" not in captured
