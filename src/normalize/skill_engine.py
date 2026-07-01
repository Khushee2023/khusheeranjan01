"""
Skill Engine — Deterministic Normalization Layer (Layer 2).

Canonicalizes raw skill strings from any source into the pipeline's
canonical skill name set. Two-step process:

  Step 1 — Exact alias lookup (O(1)):
    Check the FlashText alias reverse-dict. "js" → "JavaScript",
    "k8s" → "Kubernetes", etc. Returns immediately on a hit.

  Step 2 — RapidFuzz fuzzy match (O(k) where k = canonical skill count):
    If exact lookup fails, try a fuzzy match against the canonical name list.
    Threshold: 80 (WRatio score, 0–100). Catches spelling variants like
    "Postgre SQL", "Kuberneties", "Javascirpt".
    Returns None if the score is below threshold — unknown/garbage skills
    are never invented, per the assignment's robustness constraint.

Design note: fuzzy matching is applied to the CANONICAL NAMES list, not the
full alias list — we normalize the input first (strip, lowercase, remove
punctuation noise), then score it against the clean canonical names. This
avoids false positives from noisy alias strings.

Graceful degradation: if rapidfuzz is not installed, only exact alias lookup
is available. The function still returns None (not a crash) for unrecognized
skills.
"""

from __future__ import annotations

import logging
import re
from typing import List, Optional

logger = logging.getLogger(__name__)

# Import the alias map from flashtext_skills as the authoritative source.
from src.extraction_engine.flashtext_skills import _SKILL_ALIASES, _ALIAS_REVERSE

# ---- RapidFuzz with graceful degradation --------------------------------

try:
    from rapidfuzz import process as _rf_process, fuzz as _rf_fuzz  # type: ignore
    _RAPIDFUZZ_OK = True
    logger.debug("[skill_engine] rapidfuzz loaded.")
except ImportError:
    logger.warning(
        "[skill_engine] rapidfuzz not installed — fuzzy skill canonicalization disabled. "
        "Only exact alias lookup will be used. Install with: pip install rapidfuzz"
    )
    _RAPIDFUZZ_OK = False

# ---- Build canonical names list (for fuzzy scoring target) --------------

_CANONICAL_NAMES: List[str] = list(_SKILL_ALIASES.keys())

# Fuzzy match threshold (0–100 WRatio score). Set conservatively to avoid
# false positives: "Go" should NOT match "Groovy" or "Gopher".
_FUZZY_THRESHOLD = 80

# Pre-compile noise-stripping pattern for input normalization.
_NOISE_PATTERN = re.compile(r"[^a-zA-Z0-9\s\+\#\./]")


def _normalize_for_fuzzy(raw: str) -> str:
    """
    Light normalization before fuzzy scoring:
      - strip whitespace
      - lowercase
      - collapse repeated spaces
      - keep alphanumeric + common skill punctuation (+ # . /)
    """
    cleaned = _NOISE_PATTERN.sub(" ", raw.strip().lower())
    return " ".join(cleaned.split())


# ---- Public API ---------------------------------------------------------

def canonicalize_skill(raw: Optional[str]) -> Optional[str]:
    """
    Canonicalize a raw skill string.

    Returns the canonical name (e.g. "JavaScript") or None if the input
    cannot be confidently matched to any known skill. Never raises.

    Examples:
        canonicalize_skill("js")            → "JavaScript"
        canonicalize_skill("k8s")           → "Kubernetes"
        canonicalize_skill("Javascirpt")    → "JavaScript"   (fuzzy)
        canonicalize_skill("PySpark")       → "Spark"        (alias)
        canonicalize_skill("zk-snark")      → None           (unknown)
        canonicalize_skill("")              → None
    """
    if not raw or not raw.strip():
        return None

    # Step 1: exact alias lookup (O(1))
    exact = _ALIAS_REVERSE.get(raw.strip().lower())
    if exact:
        return exact

    # Also try the raw form as a canonical name directly
    for canonical in _CANONICAL_NAMES:
        if raw.strip().lower() == canonical.lower():
            return canonical

    # Step 2: RapidFuzz fuzzy match
    if not _RAPIDFUZZ_OK:
        return None

    normalized = _normalize_for_fuzzy(raw)
    if len(normalized) < 2:
        return None  # too short to fuzzy-match reliably

    try:
        result = _rf_process.extractOne(
            normalized,
            _CANONICAL_NAMES,
            scorer=_rf_fuzz.WRatio,
            score_cutoff=_FUZZY_THRESHOLD,
        )
        if result is not None:
            return result[0]  # (match, score, index) → take the match
        return None
    except Exception as exc:
        logger.debug(f"[skill_engine] fuzzy match error for {raw!r}: {exc}")
        return None


def canonicalize_skills(raw_skills: List[str]) -> List[str]:
    """
    Canonicalize a list of raw skill strings.

    Returns a deduplicated list of canonical names. Skills that cannot be
    matched are silently dropped (they are logged at DEBUG level if needed).
    Order: first-occurrence order of the canonical names.
    """
    seen: set = set()
    result = []
    for raw in raw_skills:
        canonical = canonicalize_skill(raw)
        if canonical and canonical not in seen:
            seen.add(canonical)
            result.append(canonical)
        elif not canonical and raw.strip():
            logger.debug(f"[skill_engine] unrecognized skill dropped: {raw!r}")
    return result


def fuzzy_score(raw: str, canonical: str) -> float:
    """
    Return the RapidFuzz WRatio similarity score (0–100) between a raw
    skill string and a canonical name. Returns 0.0 if rapidfuzz unavailable.
    """
    if not _RAPIDFUZZ_OK:
        return 0.0
    try:
        return _rf_fuzz.WRatio(_normalize_for_fuzzy(raw), canonical.lower())
    except Exception:
        return 0.0
