"""
Unit tests for src/core/glossary/filter.py.

Covers the source-side `filter_glossary` (regression checks) and the new
target-side `filter_glossary_by_target` used by the refine pass.
"""
from src.core.glossary.filter import filter_glossary, filter_glossary_by_target
from src.core.glossary.models import GlossaryConfig


class TestFilterGlossaryByTarget:
    """Refine pass: scan the target draft, not the English source."""

    def test_matches_single_target_form(self):
        terms = {"Voldemort": "Волдеморт"}
        chunk = "Гарри встретил Волдеморт лицом к лицу."

        filtered, capped = filter_glossary_by_target(chunk, terms)

        assert filtered == {"Voldemort": "Волдеморт"}
        assert capped is False

    def test_matches_pipe_alternatives_in_target(self):
        terms = {"Voldemort": "Волдеморт|Волдеморта|Волдеморту|Волдемортом"}
        chunk = "Гарри увидел Волдеморта в коридоре."

        filtered, _ = filter_glossary_by_target(chunk, terms)

        assert filtered == {"Voldemort": "Волдеморт|Волдеморта|Волдеморту|Волдемортом"}

    def test_root_bug_source_form_in_target_chunk_misses(self):
        """The original INFRA-11 bug: source-side filter returns nothing on a
        target-language chunk, so refine sees an empty glossary block. Target-
        side filter catches the term as long as the draft uses the canonical
        nominative (matching the dictionary value)."""
        terms = {"Voldemort": "Волдеморт"}
        chunk = "Гарри встретил Волдеморт в коридоре."

        source_filtered, _ = filter_glossary(chunk, terms)
        target_filtered, _ = filter_glossary_by_target(chunk, terms)

        assert source_filtered == {}, "source-side filter must miss latin term in cyrillic chunk"
        assert target_filtered == {"Voldemort": "Волдеморт"}, "target-side filter must catch it"

    def test_inflected_target_without_alternatives_misses(self):
        """Without `|`-alternatives the target filter inherits the same
        word-boundary rule and will miss inflected forms. This is documented
        behavior - the diagnostic WARN in `_build_chunk_glossary_block`
        nudges users to add the alternatives."""
        terms = {"Voldemort": "Волдеморт"}
        chunk = "Гарри встретил Волдеморта в коридоре."

        filtered, _ = filter_glossary_by_target(chunk, terms)

        assert filtered == {}

    def test_longest_target_first_for_overlap(self):
        """When two target terms overlap, the longer one should sort first so
        the rendered block is predictable for the LLM."""
        terms = {
            "Harry": "Гарри",
            "Harry Potter": "Гарри Поттер",
        }
        chunk = "Гарри Поттер открыл дверь, а позади стоял Гарри."

        filtered, _ = filter_glossary_by_target(chunk, terms)

        assert list(filtered.keys()) == ["Harry Potter", "Harry"]

    def test_cap_keeps_most_frequent(self):
        terms = {
            "Alice": "Алиса",
            "Bob": "Боб",
            "Carol": "Кэрол",
        }
        chunk = "Алиса Алиса Алиса Боб Кэрол"
        config = GlossaryConfig(max_entries=2)

        filtered, capped = filter_glossary_by_target(chunk, terms, config)

        assert capped is True
        assert "Alice" in filtered
        assert len(filtered) == 2

    def test_cjk_substring_match_on_target(self):
        terms = {"Dragon": "龙王"}
        chunk = "勇者击败了龙王。"

        filtered, _ = filter_glossary_by_target(chunk, terms)

        assert filtered == {"Dragon": "龙王"}

    def test_case_insensitive_target_match(self):
        terms = {"Voldemort": "Волдеморт"}
        chunk = "волдеморт пришёл"
        config = GlossaryConfig(case_sensitive=False)

        filtered, _ = filter_glossary_by_target(chunk, terms, config)

        assert filtered == {"Voldemort": "Волдеморт"}

    def test_empty_chunk_returns_empty(self):
        filtered, capped = filter_glossary_by_target("", {"Voldemort": "Волдеморт"})

        assert filtered == {}
        assert capped is False

    def test_empty_terms_returns_empty(self):
        filtered, capped = filter_glossary_by_target("Гарри", {})

        assert filtered == {}
        assert capped is False

    def test_no_match_returns_empty(self):
        terms = {"Voldemort": "Волдеморт"}
        chunk = "Гарри потёр шрам на лбу."

        filtered, _ = filter_glossary_by_target(chunk, terms)

        assert filtered == {}

    def test_word_boundary_on_latin_target(self):
        """Latin target inside cyrillic chunk should still respect word
        boundaries (so `Fan` does not match `Fantasy`)."""
        terms = {"Fan": "Fan"}
        chunk = "Это слово Fantasy ничего общего не имеет."

        filtered, _ = filter_glossary_by_target(chunk, terms)

        assert filtered == {}


class TestFilterGlossarySourceBackwardCompat:
    """Existing source-side filter must keep working unchanged."""

    def test_matches_source_on_english_chunk(self):
        terms = {"Voldemort": "Волдеморт"}
        chunk = "Voldemort entered the hall."

        filtered, _ = filter_glossary(chunk, terms)

        assert filtered == {"Voldemort": "Волдеморт"}

    def test_pipe_alternatives_on_source_still_work(self):
        terms = {"Москва|Москве|Москвы|Москвой": "Moscow"}
        chunk = "Поезд прибыл в Москве вечером."

        filtered, _ = filter_glossary(chunk, terms)

        assert filtered == {"Москва|Москве|Москвы|Москвой": "Moscow"}

    def test_target_pipe_does_not_affect_source_filter(self):
        """Source-side filter must not parse `|` in the target value — that's a
        target-only convention for the refine pass."""
        terms = {"Voldemort": "Волдеморт|Волдеморта"}
        chunk = "Voldemort entered the hall."

        filtered, _ = filter_glossary(chunk, terms)

        assert filtered == {"Voldemort": "Волдеморт|Волдеморта"}
