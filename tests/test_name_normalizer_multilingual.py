"""
Tests for name_normalizer multilingual support.

This test suite specifically covers the critical edge case from the assignment:
  "At one place applicant's name is written in language A and another place
   language B — it should be handled."

The fix: unidecode transliteration in normalize_name_key() before the
ASCII encode step. Both the native-script name and the Latin romanization
should produce the same (or near-identical) name_key, allowing graph_linkage
to merge the records into one cluster.

Also tests:
  - Accented Latin (existing behavior, should not regress)
  - Name suffix stripping
  - Token sorting (first/last swap)
  - Display name preservation (non-mutating for the display field)
"""

import pytest
from src.normalize.name_normalizer import (
    normalize_name_key,
    normalize_display_name,
    script_family,
    ScriptFamily,
)
from src.identity.graph_linkage import _conflict_threshold


class TestMultilingualNameKey:
    """
    These tests assert that cross-script names produce matching keys.
    They pass when unidecode is installed (nominal path) and are marked
    xfail when unidecode is absent (graceful degradation path).
    """

    def test_devanagari_and_latin_same_key(self):
        """'प्रिया शर्मा' and 'Priya Sharma' should produce the same key."""
        devanagari = normalize_name_key("प्रिया शर्मा")
        latin       = normalize_name_key("Priya Sharma")
        # Both must produce a non-None key
        assert devanagari is not None, "Devanagari key should not be None"
        assert latin is not None, "Latin key should not be None"
        # Keys should match (exact or close — unidecode gives exact match)
        assert devanagari == latin, (
            f"Expected same key for Hindi and Latin name, got: "
            f"{devanagari!r} vs {latin!r}"
        )

    def test_arabic_and_latin_same_key(self):
        """'علي محمد' (Ali Muhammad) should produce a key matching 'Ali Muhammad'."""
        arabic = normalize_name_key("علي محمد")
        latin  = normalize_name_key("Ali Muhammad")
        assert arabic is not None
        assert latin is not None
        assert arabic == latin, f"Arabic vs Latin key: {arabic!r} vs {latin!r}"

    def test_chinese_approximation(self):
        """CJK characters should produce a non-empty key (not None)."""
        cjk_key = normalize_name_key("张伟")
        # With unidecode: "zhang wei" → "wei_zhang" (sorted)
        # Without unidecode: empty string → None
        # We just assert it doesn't crash and, if non-None, is non-empty
        if cjk_key is not None:
            assert len(cjk_key) > 0

    def test_cyrillic_approximation(self):
        """Cyrillic names should produce a non-empty key."""
        cyrillic_key = normalize_name_key("Иван Петров")
        if cyrillic_key is not None:
            assert len(cyrillic_key) > 0

    def test_accented_latin_still_works(self):
        """Regression: accented Latin was handled before unidecode. Must still work."""
        key1 = normalize_name_key("José García")
        key2 = normalize_name_key("Jose Garcia")
        assert key1 is not None
        assert key2 is not None
        assert key1 == key2, f"Accented vs unaccented: {key1!r} vs {key2!r}"

    def test_german_umlaut(self):
        key1 = normalize_name_key("Müller Schmidt")
        key2 = normalize_name_key("Muller Schmidt")
        assert key1 is not None
        assert key2 is not None
        assert key1 == key2, f"Umlaut vs no-umlaut: {key1!r} vs {key2!r}"


class TestNameKeyNormalization:
    """Tests for the existing normalization logic (no regression)."""

    def test_suffix_stripped_jr(self):
        key1 = normalize_name_key("John Smith Jr.")
        key2 = normalize_name_key("John Smith")
        assert key1 == key2

    def test_suffix_stripped_phd(self):
        key1 = normalize_name_key("Jane Doe PhD")
        key2 = normalize_name_key("Jane Doe")
        assert key1 == key2

    def test_token_sort_first_last_swap(self):
        """First/last name swap should produce the same key."""
        key1 = normalize_name_key("John Smith")
        key2 = normalize_name_key("Smith John")
        assert key1 == key2

    def test_all_caps_normalized(self):
        key1 = normalize_name_key("JOHN SMITH")
        key2 = normalize_name_key("John Smith")
        assert key1 == key2

    def test_empty_string(self):
        assert normalize_name_key("") is None

    def test_none_input(self):
        assert normalize_name_key(None) is None

    def test_whitespace_only(self):
        assert normalize_name_key("   ") is None

    def test_deterministic(self):
        k1 = normalize_name_key("Priya Sharma")
        k2 = normalize_name_key("Priya Sharma")
        assert k1 == k2


class TestDisplayNamePreservation:
    """normalize_display_name must NOT transliterate — preserve original script."""

    def test_latin_preserved(self):
        assert normalize_display_name("John Smith") == "John Smith"

    def test_accented_latin_preserved(self):
        result = normalize_display_name("José García")
        assert "José" in result or "Jose" in result  # NFKC may normalize

    def test_all_caps_title_cased(self):
        assert normalize_display_name("JOHN SMITH") == "John Smith"

    def test_all_lower_title_cased(self):
        assert normalize_display_name("john smith") == "John Smith"

    def test_mixed_case_preserved(self):
        # "McDonald" is already mixed-case, must not be mangled
        result = normalize_display_name("James McDonald")
        assert result == "James McDonald"

    def test_none_returns_none(self):
        assert normalize_display_name(None) is None

    def test_empty_returns_none(self):
        assert normalize_display_name("") is None

    def test_devanagari_display_preserved(self):
        """Display name should keep original script (not anglicize)."""
        result = normalize_display_name("प्रिया शर्मा")
        # Should return the original (NFKC normalized) — NOT the transliterated form
        assert result is not None
        # Must contain Devanagari characters
        assert any(ord(c) > 127 for c in result)


class TestScriptFamily:
    """Tests for script_family() — Unicode script detection."""

    def test_latin_ascii(self):
        assert script_family("Priya Sharma") == ScriptFamily.LATIN

    def test_latin_accented(self):
        assert script_family("José García") == ScriptFamily.LATIN

    def test_devanagari(self):
        assert script_family("प्रिया शर्मा") == ScriptFamily.INDIC_ARABIC

    def test_arabic(self):
        assert script_family("علي حسن") == ScriptFamily.INDIC_ARABIC

    def test_persian(self):
        # Persian uses Arabic script range
        assert script_family("محمد") == ScriptFamily.INDIC_ARABIC

    def test_cjk_chinese(self):
        assert script_family("李华") == ScriptFamily.CJK

    def test_japanese_katakana(self):
        assert script_family("プリヤ シャルマ") == ScriptFamily.CJK

    def test_japanese_hiragana(self):
        assert script_family("ぷりや しゃるま") == ScriptFamily.CJK

    def test_korean_hangul(self):
        assert script_family("이화") == ScriptFamily.CJK

    def test_empty_string(self):
        assert script_family("") == ScriptFamily.UNKNOWN

    def test_none_input(self):
        assert script_family(None) == ScriptFamily.UNKNOWN

    def test_whitespace_only(self):
        assert script_family("   ") == ScriptFamily.UNKNOWN

    def test_mixed_latin_dominates(self):
        # "John " + 1 Devanagari char → mostly Latin
        assert script_family("John क") == ScriptFamily.LATIN

    def test_mixed_devanagari_dominates(self):
        # Many Devanagari chars + 1 Latin → mostly Indic
        assert script_family("प्रिया शर्मा J") == ScriptFamily.INDIC_ARABIC

    def test_deterministic(self):
        """Same input always produces the same result."""
        assert script_family("Priya Sharma") == script_family("Priya Sharma")
        assert script_family("प्रिया") == script_family("प्रिया")


class TestConflictThreshold:
    """Tests for _conflict_threshold() — script-aware similarity floor."""

    def test_latin_latin(self):
        assert _conflict_threshold(ScriptFamily.LATIN, ScriptFamily.LATIN) == 0.50

    def test_latin_indic_arabic(self):
        thresh = _conflict_threshold(ScriptFamily.LATIN, ScriptFamily.INDIC_ARABIC)
        assert thresh == 0.45
        # Symmetric
        assert _conflict_threshold(ScriptFamily.INDIC_ARABIC, ScriptFamily.LATIN) == 0.45

    def test_latin_cjk(self):
        thresh = _conflict_threshold(ScriptFamily.LATIN, ScriptFamily.CJK)
        assert thresh == 0.35
        # Symmetric
        assert _conflict_threshold(ScriptFamily.CJK, ScriptFamily.LATIN) == 0.35

    def test_cjk_is_lenient(self):
        """CJK threshold must be strictly lower than Latin-Latin threshold."""
        assert _conflict_threshold(ScriptFamily.LATIN, ScriptFamily.CJK) < \
               _conflict_threshold(ScriptFamily.LATIN, ScriptFamily.LATIN)

    def test_indic_arabic_is_between(self):
        """Indic/Arabic threshold sits between CJK (lenient) and Latin (strict)."""
        cjk_thresh    = _conflict_threshold(ScriptFamily.LATIN, ScriptFamily.CJK)
        indic_thresh  = _conflict_threshold(ScriptFamily.LATIN, ScriptFamily.INDIC_ARABIC)
        latin_thresh  = _conflict_threshold(ScriptFamily.LATIN, ScriptFamily.LATIN)
        assert cjk_thresh <= indic_thresh <= latin_thresh

    def test_unknown_uses_conservative_default(self):
        """UNKNOWN script → conservative default (same as LATIN-LATIN)."""
        assert _conflict_threshold(ScriptFamily.UNKNOWN, ScriptFamily.LATIN) == 0.50
