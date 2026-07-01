"""
GLiNER Zero-Shot NER Extractor — Layer 1 of the pipeline.

GLiNER performs zero-shot named entity recognition: given a list of entity
labels, it finds spans in text that match those labels WITHOUT needing a
task-specific fine-tuned model. This makes it ideal for the "no training
data" constraint here.

Labels used:
  - PERSON      → full_name candidates
  - ORG         → company names (experience)
  - LOCATION    → city/region/country hints
  - SKILL       → technical skills (complementary to FlashText trie)
  - EMAIL       → email addresses (cross-check with regex)
  - PHONE       → phone numbers (cross-check with regex)

GRACEFUL DEGRADATION (critical requirement):
  If GLiNER is not installed, the model download fails, or the model file
  is absent, every function in this module returns [] / None. The pipeline
  continues with regex/FlashText/spaCy as the fallback chain. A single
  WARNING is logged at import time so the operator knows GLiNER is offline.

Model: "urchade/gliner_medium-v2.1" (~300 MB, downloaded once to HuggingFace
cache). Override via GLINER_MODEL_ID env var.

Performance: GLiNER is O(n·labels) per inference. For notes files (< 2 KB)
this is fast enough. For large resumes we process the first N chars only.
"""

from __future__ import annotations

import logging
import os
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

# --- Model configuration -------------------------------------------------

_DEFAULT_MODEL_ID = "urchade/gliner_medium-v2.1"
_MODEL_ID = os.environ.get("GLINER_MODEL_ID", _DEFAULT_MODEL_ID)

# Max characters fed to GLiNER per call — keeps latency bounded.
_MAX_CHARS = 4000

# Entity labels we ask GLiNER to find.
_LABELS = ["PERSON", "ORG", "LOCATION", "SKILL", "EMAIL", "PHONE"]

# Confidence threshold — spans below this are dropped.
_MIN_SCORE = 0.4

# --- Lazy model singleton ------------------------------------------------

_model = None          # GLiNER model instance (loaded on first call)
_load_attempted = False  # True after first load attempt (success or failure)
_gliner_available = False  # True only if import + load succeeded


def _ensure_model() -> bool:
    """
    Lazy-load the GLiNER model. Returns True if the model is ready, False if
    anything went wrong. Safe to call multiple times — loads only once.
    """
    global _model, _load_attempted, _gliner_available

    if _load_attempted:
        return _gliner_available

    _load_attempted = True
    try:
        from gliner import GLiNER  # type: ignore
        logger.info(f"[gliner_extractor] Loading model {_MODEL_ID!r} …")
        _model = GLiNER.from_pretrained(_MODEL_ID)
        _gliner_available = True
        logger.info("[gliner_extractor] Model loaded successfully.")
    except ImportError:
        logger.warning(
            "[gliner_extractor] gliner package not installed — NER disabled. "
            "Install with: pip install gliner"
        )
    except Exception as exc:
        logger.warning(
            f"[gliner_extractor] Failed to load model {_MODEL_ID!r}: {exc}. "
            "NER disabled; pipeline will use regex/FlashText fallbacks."
        )

    return _gliner_available


# --- Public API ----------------------------------------------------------

def extract_entities(text: str) -> List[dict]:
    """
    Run GLiNER over `text` and return a list of entity dicts:
        {"label": str, "text": str, "score": float}

    Returns [] if GLiNER is unavailable or inference fails. Never raises.
    """
    if not text or not text.strip():
        return []

    if not _ensure_model():
        return []

    try:
        truncated = text[:_MAX_CHARS]
        entities = _model.predict_entities(truncated, _LABELS, threshold=_MIN_SCORE)
        return [e for e in entities if e.get("score", 0) >= _MIN_SCORE]
    except Exception as exc:
        logger.debug(f"[gliner_extractor] inference error: {exc}")
        return []


def extract_person(text: str) -> Optional[Tuple[str, float]]:
    """
    Find the highest-confidence PERSON entity in text.

    Returns (name_string, confidence) or None if nothing found.
    Confidence is the raw GLiNER score (0–1).
    """
    entities = extract_entities(text)
    persons = [e for e in entities if e.get("label") == "PERSON"]
    if not persons:
        return None
    best = max(persons, key=lambda e: e.get("score", 0))
    return (best["text"].strip(), round(best["score"], 4))


def extract_skills(text: str) -> List[Tuple[str, float]]:
    """
    Find all SKILL entities in text.

    Returns list of (skill_name, confidence). Order is document order.
    """
    entities = extract_entities(text)
    return [
        (e["text"].strip(), round(e.get("score", 0), 4))
        for e in entities
        if e.get("label") == "SKILL" and e.get("text", "").strip()
    ]


def extract_orgs(text: str) -> List[Tuple[str, float]]:
    """Find all ORG entities — useful for company name extraction."""
    entities = extract_entities(text)
    return [
        (e["text"].strip(), round(e.get("score", 0), 4))
        for e in entities
        if e.get("label") == "ORG" and e.get("text", "").strip()
    ]


def is_available() -> bool:
    """Return True if GLiNER is loaded and ready. Triggers a load attempt."""
    return _ensure_model()
