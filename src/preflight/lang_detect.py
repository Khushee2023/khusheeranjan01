"""
Pre-flight Language Detection — Layer 0.

Uses `langdetect` to identify the primary language of a text block.
The result is consumed by:
  - notes_extractor: to choose the right transliteration path before
    name_key comparison.
  - resume_extractor: to log a provenance note when non-English content
    is detected (useful for debugging cross-language merges).
  - name_normalizer (indirectly): unidecode handles the actual
    transliteration; this module just labels the language.

Design constraints:
  DETERMINISM: langdetect is non-deterministic by default (it uses a
  probabilistic model with random seeding). We fix the seed to 42 so
  the same input ALWAYS produces the same language code.

  ROBUSTNESS: Falls back to "en" if:
    - langdetect is not installed
    - Text is too short (< 20 chars) — detection is unreliable
    - Any exception is raised by the library
    This ensures the pipeline never crashes on this step.
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Minimum character count for reliable language detection.
# Below this threshold we return "en" as the safe default.
MIN_DETECT_CHARS = 20

# Fixed seed for langdetect determinism (MUST be set before any detect() call).
_LANGDETECT_SEED = 42

_LANGDETECT_OK = False
try:
    from langdetect import detect, DetectorFactory
    DetectorFactory.seed = _LANGDETECT_SEED
    _LANGDETECT_OK = True
except ImportError:
    logger.warning(
        "[lang_detect] langdetect not installed — language detection disabled, "
        "defaulting to 'en' for all inputs."
    )


def detect_language(text: str, default: str = "en") -> str:
    """
    Detect the primary language of `text`. Returns an ISO 639-1 code.

    Args:
        text:    Raw input text (can be messy, mixed).
        default: Returned when detection is unavailable or inconclusive.

    Returns:
        ISO 639-1 language code, e.g. "en", "hi", "ar", "zh-cn", "de".
        Always returns `default` (never raises).

    Examples:
        >>> detect_language("My name is Priya Sharma and I work in Bangalore")
        'en'
        >>> detect_language("मेरा नाम प्रिया शर्मा है")
        'hi'
        >>> detect_language("اسمي علي محمد")
        'ar'
    """
    if not _LANGDETECT_OK:
        return default

    # Strip to just the first 500 chars — detection is fast and doesn't need
    # the full document; short sample reduces noise from code/URLs.
    sample = text.strip()[:500]

    if len(sample) < MIN_DETECT_CHARS:
        return default

    try:
        from langdetect import detect as _detect
        result = _detect(sample)
        return result if result else default
    except Exception as exc:
        logger.debug(f"[lang_detect] detection failed: {exc}")
        return default


def is_latin_script(text: str) -> bool:
    """
    Quick heuristic: True if the majority of non-whitespace chars in `text`
    are ASCII (i.e., Latin-script or ASCII-heavy content).

    Used to decide whether we need unidecode transliteration before
    name_key comparison — if the text is already Latin-ASCII, no conversion
    is needed, which is the fast path for the vast majority of inputs.
    """
    if not text:
        return True
    non_ws = [c for c in text if not c.isspace()]
    if not non_ws:
        return True
    ascii_count = sum(1 for c in non_ws if ord(c) < 128)
    return ascii_count / len(non_ws) >= 0.7
