"""
Date Engine — Deterministic Normalization Layer (Layer 2).

Normalizes raw date strings to ISO-8601 YYYY-MM format (or "present" for
open-ended roles). Used in the reduction phase to normalize experience
start/end dates BEFORE they are stored in the canonical profile.

Design constraints:
  DETERMINISM: python-dateutil's parse() can be ambiguous (is "01/02/2023"
    Jan 2 or Feb 1?). We set dayfirst=False (US convention) and yearfirst=False
    consistently, and always pass a default date of the FIRST of the month
    so partial dates ("January 2018") always produce "2018-01" not a random day.

  ROBUSTNESS: Returns None on any unparseable input. Never raises.

  CHRONOLOGICAL CHECK: If both start and end dates are known ISO-8601 dates
    and start > end, the pair is flagged. We log a warning and swap them
    rather than silently emitting an inverted range — inverted ranges corrupt
    years_experience calculations downstream.

  "PRESENT": The strings "present", "current", "now", "ongoing" (case-insensitive)
    are normalized to the literal string "present" rather than today's date,
    so the output is reproducible across run dates.
"""

from __future__ import annotations

import logging
import re
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

# ---- Imports with graceful degradation ----------------------------------

try:
    from dateutil import parser as _dateutil_parser
    from dateutil.parser import ParserError as _ParserError
    _DATEUTIL_OK = True
except ImportError:
    logger.warning(
        "[date_engine] python-dateutil not installed — date normalization disabled. "
        "Install with: pip install python-dateutil"
    )
    _DATEUTIL_OK = False

# ---- Constants ----------------------------------------------------------

# Strings that mean "still working here"
_PRESENT_SYNONYMS = re.compile(
    r"^\s*(present|current|now|ongoing|till\s+date|to\s+date|today)\s*$",
    re.IGNORECASE,
)

# Fast path: already in YYYY-MM format
_ISO_YYYYMM = re.compile(r"^\d{4}-(?:0[1-9]|1[0-2])$")

# YYYY only — treat as YYYY-01 (start of year)
_YEAR_ONLY = re.compile(r"^\d{4}$")

# Used as the default day for partial dates so dateutil always produces
# a deterministic result. Day=1 means "January 2018" → 2018-01-01 → "2018-01".
from datetime import date as _date
_DEFAULT_DATE = _date(1900, 1, 1)


# ---- Public API ---------------------------------------------------------

def normalize_date(raw: Optional[str]) -> Optional[str]:
    """
    Normalize a raw date string to "YYYY-MM" or "present".

    Supported input formats (non-exhaustive):
        "January 2018" → "2018-01"
        "Jan 2018"     → "2018-01"
        "01/2018"      → "2018-01"
        "2018-01"      → "2018-01"   (already canonical, pass-through)
        "2018"         → "2018-01"   (year-only → treated as January)
        "Present"      → "present"
        "current"      → "present"
        ""             → None
        "garbage"      → None

    Returns None on failure. Never raises.
    """
    if raw is None:
        return None

    text = raw.strip()
    if not text:
        return None

    # Fast path: already canonical
    if _ISO_YYYYMM.match(text):
        return text

    # "present" synonyms
    if _PRESENT_SYNONYMS.match(text):
        return "present"

    # Year-only: "2018" → "2018-01"
    if _YEAR_ONLY.match(text):
        return f"{text}-01"

    if not _DATEUTIL_OK:
        return None

    try:
        parsed = _dateutil_parser.parse(
            text,
            default=_DEFAULT_DATE,
            dayfirst=False,
            yearfirst=False,
        )
        return parsed.strftime("%Y-%m")
    except (_ParserError, ValueError, OverflowError):
        logger.debug(f"[date_engine] Could not parse date: {raw!r}")
        return None
    except Exception as exc:
        logger.debug(f"[date_engine] Unexpected error parsing {raw!r}: {exc}")
        return None


def normalize_date_pair(
    start_raw: Optional[str],
    end_raw: Optional[str],
) -> Tuple[Optional[str], Optional[str]]:
    """
    Normalize a (start, end) date pair and enforce chronological order.

    If both are parseable ISO-8601 dates and start > end, the values are
    SWAPPED and a warning is logged. This handles the common data entry
    error where start/end fields are reversed.

    "present" as end is always valid (open-ended role, always ≥ start).

    Returns (normalized_start, normalized_end).
    """
    start = normalize_date(start_raw)
    end   = normalize_date(end_raw)

    # Chronological check (only possible when both are YYYY-MM)
    if (
        start is not None
        and end is not None
        and end != "present"
        and _ISO_YYYYMM.match(start)
        and _ISO_YYYYMM.match(end)
        and start > end
    ):
        logger.warning(
            f"[date_engine] Chronological inversion detected: "
            f"start={start!r} > end={end!r} — swapping."
        )
        start, end = end, start

    return start, end


def parse_years_experience(
    start_raw: Optional[str],
    end_raw: Optional[str],
) -> Optional[float]:
    """
    Compute the number of years in a role from its start and end dates.

    Returns a float rounded to 1 decimal place, or None if either date is
    unparseable. If end is "present", uses today's date.

    Useful for summing across all experiences to estimate total
    years_experience.
    """
    if not _DATEUTIL_OK:
        return None

    start = normalize_date(start_raw)
    if start is None or not _ISO_YYYYMM.match(start):
        return None

    if end_raw and _PRESENT_SYNONYMS.match(end_raw.strip()):
        import datetime
        end_date = datetime.date.today()
    else:
        end = normalize_date(end_raw)
        if end is None or not _ISO_YYYYMM.match(end):
            return None
        try:
            end_date = _dateutil_parser.parse(end + "-01").date()
        except Exception:
            return None

    try:
        start_date = _dateutil_parser.parse(start + "-01").date()
        delta_years = (end_date - start_date).days / 365.25
        return round(max(delta_years, 0.0), 1)
    except Exception:
        return None
