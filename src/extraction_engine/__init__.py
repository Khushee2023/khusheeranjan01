"""
Extraction engine package exports.
"""

from src.extraction_engine.gliner_extractor import (
    extract_entities,
    extract_person,
    extract_skills as gliner_extract_skills,
    extract_orgs,
    is_available as gliner_available,
)
from src.extraction_engine.flashtext_skills import (
    extract_skills as flashtext_extract_skills,
    canonical_name as flashtext_canonical_name,
)
from src.extraction_engine.spacy_extractor import (
    extract_noun_chunks,
    is_available as spacy_available,
)

__all__ = [
    # GLiNER
    "extract_entities",
    "extract_person",
    "gliner_extract_skills",
    "extract_orgs",
    "gliner_available",
    # FlashText
    "flashtext_extract_skills",
    "flashtext_canonical_name",
    # spaCy
    "extract_noun_chunks",
    "spacy_available",
]
