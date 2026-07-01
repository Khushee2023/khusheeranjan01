"""
Deterministic phone number normalization to E.164.

Design constraints from the assignment:
- Deterministic: same input -> same output, always.
- Robust: malformed input never crashes the pipeline; it becomes None plus a
  provenance note, never an invented value.
- Explainable: caller gets back not just the normalized number but the method
  and confidence used to produce it.

Uses `phonenumbers` (Python port of Google's libphonenumber). Falls back to a
best-effort default region when no country code is present, since recruiter
data frequently omits the '+'.
"""

from __future__ import annotations

from typing import NamedTuple, Optional

import phonenumbers
from phonenumbers import NumberParseException, PhoneNumberFormat


class PhoneNormalizationResult(NamedTuple):
    e164: Optional[str]        # e.g. "+14155552671", or None if unparseable
    confidence: float          # 1.0 = had explicit country code; 0.6 = guessed region
    note: Optional[str]        # explanation, useful for provenance/debugging


# Default region used ONLY when the input has no country code at all.
# Set per-deployment; for this assignment we default to US but this should be
# treated as a config value in a real system, not a hardcoded constant.
DEFAULT_REGION = "US"


def normalize_phone(
    raw: Optional[str],
    default_region: str = DEFAULT_REGION,
) -> PhoneNormalizationResult:
    """
    Normalize a raw phone string to E.164. Never raises; always returns a
    PhoneNormalizationResult, with e164=None on failure.
    """
    if raw is None or not raw.strip():
        return PhoneNormalizationResult(
            e164=None, confidence=0.0, note="empty_input"
        )

    cleaned = raw.strip()
    has_explicit_country_code = cleaned.startswith("+")

    try:
        parsed = phonenumbers.parse(
            cleaned,
            None if has_explicit_country_code else default_region,
        )
    except NumberParseException as exc:
        return PhoneNormalizationResult(
            e164=None,
            confidence=0.0,
            note=f"parse_failed:{exc.error_type.name}",
        )

    if not phonenumbers.is_valid_number(parsed):
        return PhoneNormalizationResult(
            e164=None,
            confidence=0.0,
            note="parsed_but_invalid",
        )

    e164 = phonenumbers.format_number(parsed, PhoneNumberFormat.E164)

    confidence = 1.0 if has_explicit_country_code else 0.6
    note = "explicit_country_code" if has_explicit_country_code else f"assumed_region:{default_region}"

    return PhoneNormalizationResult(e164=e164, confidence=confidence, note=note)


def dedupe_phones(numbers: list[str]) -> list[str]:
    """
    Dedupe a list of already-normalized E.164 numbers while preserving first-seen
    order (order matters for determinism downstream, e.g. emails[0]-style configs).
    """
    seen: set[str] = set()
    result: list[str] = []
    for n in numbers:
        if n not in seen:
            seen.add(n)
            result.append(n)
    return result