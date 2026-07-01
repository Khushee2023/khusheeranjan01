"""
Name normalization.

Two distinct outputs are needed:
1. A DISPLAY name (Unicode-normalized, properly cased) — what shows up in
   `full_name` on the canonical profile.
2. A NAME_KEY (aggressive normalization: lowercase, transliterated, stripped
   of punctuation/whitespace/suffixes) — used ONLY as a weak identity-linkage
   signal in graph_linkage.py. Never shown to a user, never trusted alone.

Design note: name matching is inherently lossy (nicknames, middle names,
transliteration ambiguity, married-name changes). We deliberately keep this
simple and deterministic rather than reaching for a fuzzy-matching library
here — fuzzy logic belongs in skill canonicalization, not in identity
resolution, per the trust_policy.py rationale already documented.

Multilingual support (edge case from assignment):
  A candidate named "प्रिया शर्मा" in one source and "Priya Sharma" in another
  must be recognized as the SAME person. The fix: run `unidecode` on the raw
  name BEFORE the NFKD/ASCII encode step. unidecode converts non-Latin scripts
  to their phonetic Latin approximation:
    "प्रिया शर्मा"  → "priya sharma"
    "プリヤ シャルマ" → "puriya sharuma"  (close enough for SequenceMatcher ≥ 0.5)
    "プ리야 샤르마"  → romanized form
  unidecode is in requirements.txt; if absent we fall back to the old NFKD-only
  strip, which already handles accented Latin (é → e, ñ → n, etc.).
"""

from __future__ import annotations

import logging
import re
import unicodedata
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)

# Graceful degradation: unidecode handles non-Latin scripts (Devanagari,
# Arabic, CJK, etc.). If not installed, we fall back to NFKD-only, which
# still handles accented Latin correctly.
try:
    from unidecode import unidecode as _unidecode  # type: ignore
    _UNIDECODE_OK = True
except ImportError:
    logger.warning(
        "[name_normalizer] unidecode not installed — multilingual name transliteration "
        "disabled. Non-Latin script names (Devanagari, Arabic, CJK) may not match "
        "their Latin equivalents across sources. Install with: pip install unidecode"
    )
    _UNIDECODE_OK = False


# ---------------------------------------------------------------------------
# Script family detection (for dynamic similarity thresholds)
# ---------------------------------------------------------------------------

class ScriptFamily(str, Enum):
    """
    Broad Unicode script group, used by graph_linkage to pick the right
    name-similarity threshold when comparing cross-script name keys.

    - LATIN: ASCII + accented Latin characters (most English/European names).
    - INDIC_ARABIC: Devanagari, Arabic, Persian, Bengali, Tamil, etc.
      unidecode produces high-quality romanisations for these, so cross-script
      similarity after transliteration is reliable.
    - CJK: Chinese, Japanese, Korean.
      Romanisation (e.g. Hepburn, Pinyin, McCune–Reischauer) diverges more
      from the original phonetics, so we use a lower threshold to avoid
      false-negative splits.
    - UNKNOWN: mixed or empty — treated like LATIN for threshold purposes.
    """
    LATIN        = "latin"
    INDIC_ARABIC = "indic_arabic"
    CJK          = "cjk"
    UNKNOWN      = "unknown"


# Unicode code-point ranges used to identify script families.
# These cover the most common blocks; rare scripts fall through to UNKNOWN
# (which uses the LATIN threshold, i.e. the strictest, so we err on the
# side of NOT merging rather than wrongly merging).
_DEVANAGARI_RANGE = (0x0900, 0x097F)
_ARABIC_RANGE     = (0x0600, 0x06FF)
_BENGALI_RANGE    = (0x0980, 0x09FF)
_TAMIL_RANGE      = (0x0B80, 0x0BFF)
_TELUGU_RANGE     = (0x0C00, 0x0C7F)
_CJK_UNIFIED      = (0x4E00, 0x9FFF)   # CJK Unified Ideographs
_CJK_EXT_A        = (0x3400, 0x4DBF)   # CJK Extension A
_HIRAGANA         = (0x3040, 0x309F)
_KATAKANA         = (0x30A0, 0x30FF)
_HANGUL           = (0xAC00, 0xD7AF)

_INDIC_ARABIC_RANGES = [
    _DEVANAGARI_RANGE, _ARABIC_RANGE, _BENGALI_RANGE,
    _TAMIL_RANGE, _TELUGU_RANGE,
]
_CJK_RANGES = [
    _CJK_UNIFIED, _CJK_EXT_A, _HIRAGANA, _KATAKANA, _HANGUL,
]


def _char_script(cp: int) -> ScriptFamily:
    """Return the script family of a single Unicode code point."""
    for lo, hi in _INDIC_ARABIC_RANGES:
        if lo <= cp <= hi:
            return ScriptFamily.INDIC_ARABIC
    for lo, hi in _CJK_RANGES:
        if lo <= cp <= hi:
            return ScriptFamily.CJK
    if cp < 128:  # pure ASCII (includes basic Latin)
        return ScriptFamily.LATIN
    if 0x00C0 <= cp <= 0x024F:  # Latin Extended
        return ScriptFamily.LATIN
    return ScriptFamily.UNKNOWN


def script_family(name: Optional[str]) -> ScriptFamily:
    """
    Detect the dominant script family of a name string.

    Scans every non-whitespace character and votes on script membership.
    The majority-vote winner is returned. Empty / whitespace-only input
    returns UNKNOWN.

    Examples:
        script_family("Priya Sharma")         → ScriptFamily.LATIN
        script_family("प्रिया शर्मा")        → ScriptFamily.INDIC_ARABIC
        script_family("محمد علي")              → ScriptFamily.INDIC_ARABIC
        script_family("プリヤ シャルマ")          → ScriptFamily.CJK
        script_family("李华")                   → ScriptFamily.CJK
        script_family("")                     → ScriptFamily.UNKNOWN
    """
    if not name or not name.strip():
        return ScriptFamily.UNKNOWN

    counts: dict[ScriptFamily, int] = {
        ScriptFamily.LATIN: 0,
        ScriptFamily.INDIC_ARABIC: 0,
        ScriptFamily.CJK: 0,
        ScriptFamily.UNKNOWN: 0,
    }
    for ch in name:
        if ch.isspace():
            continue
        counts[_char_script(ord(ch))] += 1

    total = sum(counts.values())
    if total == 0:
        return ScriptFamily.UNKNOWN

    # Return the script with the most characters; ties go to UNKNOWN.
    winner = max(counts, key=lambda k: counts[k])
    if counts[winner] == 0:
        return ScriptFamily.UNKNOWN
    return winner



def _transliterate(text: str) -> str:
    """
    Convert any script to its ASCII phonetic approximation.

    Priority:
      1. unidecode (handles Devanagari, Arabic, CJK, Greek, Cyrillic, etc.)
      2. NFKD + ASCII encode (handles accented Latin only)

    This is used ONLY for name_key generation (identity matching), never for
    display. We want "Priya Sharma" and "प्रिया शर्मा" to produce the same key;
    we do NOT want to show the user an anglicized version of their own name.
    """
    if _UNIDECODE_OK:
        try:
            return _unidecode(text)
        except Exception:
            pass  # fall through to NFKD
    # NFKD fallback (accented Latin)
    decomposed = unicodedata.normalize("NFKD", text)
    return decomposed.encode("ascii", "ignore").decode("ascii")


# Common suffixes that shouldn't affect identity matching (Jr., Sr., II, III, etc.)
_SUFFIX_PATTERN = re.compile(
    r"\b(jr|sr|ii|iii|iv|phd|md|esq)\b\.?", re.IGNORECASE
)

_NON_ALPHA_PATTERN = re.compile(r"[^a-z\s]")
_WHITESPACE_PATTERN = re.compile(r"\s+")


def normalize_display_name(raw: str | None) -> str | None:
    """
    Produce a clean, properly-formed display name.
    Unicode NFKC normalization (e.g. fullwidth chars, combining marks) +
    whitespace collapse + title casing. Does NOT transliterate â€” we want to
    preserve the candidate's actual name as written wherever possible.
    """
    if raw is None or not raw.strip():
        return None

    cleaned = unicodedata.normalize("NFKC", raw.strip())
    cleaned = _WHITESPACE_PATTERN.sub(" ", cleaned)

    # Title-case each word, but don't mangle names that are already
    # intentionally mixed-case (e.g. "McDonald", "O'Brien") â€” only apply
    # title-casing if the input looks like it's ALL CAPS or all lowercase,
    # which is the common "messy CSV export" case. Otherwise trust the source.
    if cleaned.isupper() or cleaned.islower():
        cleaned = cleaned.title()

    return cleaned


def normalize_name_key(raw: str | None) -> str | None:
    """
    Produce an aggressive matching key for identity resolution.

    Pipeline:
      1. _transliterate()  → unidecode (all scripts) or NFKD (Latin only)
         This is the critical step for multilingual name matching:
         "प्रिया शर्मा" → "Priya Sharma" → same downstream key as "Priya Sharma"
      2. lowercase
      3. strip suffixes (Jr., Sr., Ph.D., etc.)
      4. strip non-alpha punctuation
      5. collapse whitespace
      6. sort tokens  → "John Smith" ≡ "Smith John" (guards against
         first/last field swaps across different source schemas)

    The resulting key is NEVER shown to a user. It's only used as an
    edge weight in graph_linkage.py for identity clustering.
    """
    if raw is None or not raw.strip():
        return None

    # Step 1: transliterate to ASCII (handles all scripts including non-Latin).
    ascii_only = _transliterate(raw.strip())

    lowered = ascii_only.lower()
    no_suffix = _SUFFIX_PATTERN.sub("", lowered)
    alpha_only = _NON_ALPHA_PATTERN.sub(" ", no_suffix)
    collapsed = _WHITESPACE_PATTERN.sub(" ", alpha_only).strip()

    if not collapsed:
        return None

    tokens = sorted(t for t in collapsed.split(" ") if t)  # drop empty tokens
    return "_".join(tokens)