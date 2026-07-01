"""
Runtime configuration model for the pipeline.

Injected at the canonical store step (Layer 5), before projection.
All values have deterministic defaults — no randomness, no env-var
surprises unless the caller explicitly overrides them.

Design rules:
- Every tunable parameter lives here, not scattered across modules.
- Modules import DEFAULT_CONFIG for their default behaviour; callers
  can override by constructing a RuntimeConfig and passing it in.
- No mutable global state: each pipeline run gets its own config reference.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class RuntimeConfig(BaseModel):
    # Phone normalization
    default_phone_region: str = "US"

    # NER engines (all optional — pipeline degrades gracefully if not installed)
    gliner_enabled: bool = True
    gliner_model: str = "urchade/gliner_multi-v2.1"
    spacy_enabled: bool = True
    spacy_model: str = "en_core_web_sm"

    # OCR fallback (requires Tesseract system install)
    ocr_enabled: bool = True

    # Language detection seed — MUST stay 0 for determinism
    langdetect_seed: int = Field(default=0, frozen=True)

    # Identity resolution tuning
    name_conflict_threshold: float = Field(default=0.5, ge=0.0, le=1.0)

    # Skill canonicalization
    skill_fuzzy_threshold: int = Field(default=85, ge=0, le=100)

    class Config:
        frozen = True  # Immutable after construction — config is a value, not state


# Module-level default used by all components unless overridden by the caller
DEFAULT_CONFIG = RuntimeConfig()
