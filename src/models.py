"""
Canonical data models for the Multi-Source Candidate Data Transformer.

This is the single source of truth for what a "candidate profile" looks like
internally, before any runtime projection/config is applied. Every extractor
normalizes into these shapes; every merge/reduction step operates on these
shapes; the projection layer reads from these shapes.

Design rules:
- Every field that can be "unknown" is Optional and defaults to None/[] â€” never
  invented, never guessed.
- provenance is tracked per-field so every value is traceable to (source, method).
- confidence lives at two levels: per-field (inside provenance) and overall
  (rolled up at the end of the reduction stage).
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class SourceType(str, Enum):
    ATS_JSON = "ats_json"
    RECRUITER_CSV = "recruiter_csv"
    RECRUITER_NOTES = "recruiter_notes"
    RESUME = "resume"
    GITHUB = "github"
    LINKEDIN = "linkedin"


class ExtractionMethod(str, Enum):
    """How a given field's value was obtained. Used in provenance + confidence scoring."""
    DIRECT_FIELD = "direct_field"          # structured source, field mapped 1:1
    REGEX = "regex"                        # pattern match (email, phone, dates)
    NER_GLINER = "ner_gliner"              # GLiNER zero-shot entity extraction
    NER_SPACY = "ner_spacy"                # spaCy secondary signal (lower trust)
    SKILL_TRIE = "skill_trie"              # FlashText / alias lookup
    FUZZY_MATCH = "fuzzy_match"            # RapidFuzz canonicalization
    OCR = "ocr"                            # Tesseract fallback extraction
    MERGED = "merged"                      # value chosen during reduction across sources


# ---------------------------------------------------------------------------
# Provenance & confidence
# ---------------------------------------------------------------------------

class ProvenanceEntry(BaseModel):
    field: str                       # dotted path, e.g. "phones[0]" or "experience[1].title"
    source: SourceType
    method: ExtractionMethod
    raw_value: Optional[str] = None  # value before normalization, for auditability
    confidence: float = Field(ge=0.0, le=1.0)


# ---------------------------------------------------------------------------
# Sub-objects
# ---------------------------------------------------------------------------

class Links(BaseModel):
    linkedin: Optional[str] = None
    github: Optional[str] = None
    portfolio: Optional[str] = None
    other: List[str] = Field(default_factory=list)


class Location(BaseModel):
    city: Optional[str] = None
    region: Optional[str] = None
    country: Optional[str] = None  # ISO-3166 alpha-2, e.g. "US", "IN"


class Skill(BaseModel):
    name: str                              # canonical skill name
    confidence: float = Field(ge=0.0, le=1.0)
    sources: List[SourceType] = Field(default_factory=list)


class Experience(BaseModel):
    company: Optional[str] = None
    title: Optional[str] = None
    start: Optional[str] = None    # YYYY-MM
    end: Optional[str] = None      # YYYY-MM or "present"
    summary: Optional[str] = None


class Education(BaseModel):
    institution: Optional[str] = None
    degree: Optional[str] = None
    field: Optional[str] = None
    end_year: Optional[int] = None


# ---------------------------------------------------------------------------
# Canonical candidate profile (internal record, pre-projection)
# ---------------------------------------------------------------------------

class CanonicalCandidate(BaseModel):
    candidate_id: str
    full_name: Optional[str] = None
    emails: List[str] = Field(default_factory=list)
    phones: List[str] = Field(default_factory=list)   # normalized E.164
    location: Optional[Location] = None
    links: Links = Field(default_factory=Links)
    skills: List[Skill] = Field(default_factory=list)
    headline: Optional[str] = None
    years_experience: Optional[float] = None
    experience: List[Experience] = Field(default_factory=list)
    education: List[Education] = Field(default_factory=list)

    provenance: List[ProvenanceEntry] = Field(default_factory=list)
    overall_confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    # bookkeeping, not part of the published schema but useful internally
    source_records_merged: List[SourceType] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        use_enum_values = True


# ---------------------------------------------------------------------------
# Raw per-source extraction result (before merge)
# ---------------------------------------------------------------------------

class RawFieldValue(BaseModel):
    """A single extracted value plus where/how it was found, before merge."""
    value: Optional[str] = None
    method: ExtractionMethod
    confidence: float = Field(ge=0.0, le=1.0)


class SourceRecord(BaseModel):
    """
    Output of a single extractor for a single source file/blob, BEFORE identity
    resolution and merging. One candidate may have multiple SourceRecords
    (one per source they appear in).
    """
    source_type: SourceType
    source_id: str                 # e.g. filename or row index, for traceability
    full_name: Optional[RawFieldValue] = None
    emails: List[RawFieldValue] = Field(default_factory=list)
    phones: List[RawFieldValue] = Field(default_factory=list)
    location_raw: Optional[RawFieldValue] = None
    links: Links = Field(default_factory=Links)
    skills_raw: List[RawFieldValue] = Field(default_factory=list)
    headline: Optional[RawFieldValue] = None
    experience_raw: List[Experience] = Field(default_factory=list)
    education_raw: List[Education] = Field(default_factory=list)
    parse_errors: List[str] = Field(default_factory=list)  # never crash; log instead

    class Config:
        use_enum_values = True