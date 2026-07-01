"""
Source trust policy + confidence scoring for the reduction (merge) phase.

Policy (deliberately simple and explicit, per assignment's "deterministic &
explainable" constraint â€” no ML-based conflict resolution, no "last write
wins"):

  1. Structured sources outrank unstructured sources for FACTUAL fields
     (name, email, phone, company, title) because they're operator-entered,
     not inferred from prose.
  2. Within structured sources: ATS > Recruiter CSV (ATS is typically the
     system of record once a candidate is in-process; CSV exports can be stale).
  3. Within unstructured sources: LinkedIn > Resume > GitHub > Recruiter Notes
     for profile fields (LinkedIn is self-reported and structured-ish;
     recruiter notes are the least reliable â€” paraphrased secondhand info).
  4. GitHub is authoritative for `skills` extracted from repo languages
     (overrides the general ranking for that one field, since it's the most
     objective signal of skill for that field) but not for anything else.

This file exposes a pure ranking function; the actual merge/tie-breaking
logic lives in reduction/merge.py and just calls into this.
"""

from __future__ import annotations

from src.models import SourceType

# Lower number = higher trust = wins on conflict.
_DEFAULT_RANK: dict[SourceType, int] = {
    SourceType.ATS_JSON: 0,
    SourceType.RECRUITER_CSV: 1,
    SourceType.LINKEDIN: 2,
    SourceType.RESUME: 3,
    SourceType.GITHUB: 4,
    SourceType.RECRUITER_NOTES: 5,
}

# Field-specific overrides. Field name -> ranking dict (same lower-wins convention).
# Only diverges from _DEFAULT_RANK where there's a real reason to (see docstring).
_FIELD_OVERRIDES: dict[str, dict[SourceType, int]] = {
    "skills": {
        SourceType.GITHUB: 0,
        SourceType.ATS_JSON: 1,
        SourceType.RECRUITER_CSV: 2,
        SourceType.LINKEDIN: 3,
        SourceType.RESUME: 4,
        SourceType.RECRUITER_NOTES: 5,
    },
}

# Base confidence contribution per source type, BEFORE extraction-method
# confidence is factored in (extraction confidence comes from RawFieldValue;
# this is the source-level prior).
_SOURCE_BASE_CONFIDENCE: dict[SourceType, float] = {
    SourceType.ATS_JSON: 0.95,
    SourceType.RECRUITER_CSV: 0.9,
    SourceType.LINKEDIN: 0.85,
    SourceType.RESUME: 0.75,
    SourceType.GITHUB: 0.8,
    SourceType.RECRUITER_NOTES: 0.5,
}


def rank_for_field(source_type: SourceType, field_name: str) -> int:
    """Lower = wins. Falls back to _DEFAULT_RANK if no field-specific override exists."""
    overrides = _FIELD_OVERRIDES.get(field_name)
    if overrides and source_type in overrides:
        return overrides[source_type]
    return _DEFAULT_RANK.get(source_type, len(_DEFAULT_RANK))  # unknown source -> least trusted


def base_confidence(source_type: SourceType) -> float:
    return _SOURCE_BASE_CONFIDENCE.get(source_type, 0.4)  # unknown source -> low default


def combined_confidence(source_type: SourceType, extraction_confidence: float) -> float:
    """
    Final per-field confidence = source prior * extraction-method confidence.
    Both are in [0,1], so the product is naturally bounded and penalizes
    BOTH a low-trust source AND a low-confidence extraction method â€”
    e.g. a name guessed via GLiNER from recruiter notes should score low,
    while a name read directly from an ATS JSON field should score high.
    """
    return round(base_confidence(source_type) * extraction_confidence, 4)