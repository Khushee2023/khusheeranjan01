"""
Source trust policy + confidence scoring for the reduction (merge) phase.
"""

from __future__ import annotations

from src.models import SourceType

_DEFAULT_RANK: dict[SourceType, int] = {
    SourceType.ATS_JSON: 0,
    SourceType.RECRUITER_CSV: 1,
    SourceType.LINKEDIN: 2,
    SourceType.RESUME: 3,
    SourceType.GITHUB: 4,
    SourceType.RECRUITER_NOTES: 5,
}

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

_SOURCE_BASE_CONFIDENCE: dict[SourceType, float] = {
    SourceType.ATS_JSON: 0.95,
    SourceType.RECRUITER_CSV: 0.9,
    SourceType.LINKEDIN: 0.85,
    SourceType.RESUME: 0.75,
    SourceType.GITHUB: 0.8,
    SourceType.RECRUITER_NOTES: 0.5,
}


def rank_for_field(source_type: SourceType, field_name: str) -> int:
    overrides = _FIELD_OVERRIDES.get(field_name)
    if overrides and source_type in overrides:
        return overrides[source_type]
    return _DEFAULT_RANK.get(source_type, len(_DEFAULT_RANK))


def base_confidence(source_type: SourceType) -> float:
    return _SOURCE_BASE_CONFIDENCE.get(source_type, 0.4)


def combined_confidence(source_type: SourceType, extraction_confidence: float) -> float:
    return round(base_confidence(source_type) * extraction_confidence, 4)