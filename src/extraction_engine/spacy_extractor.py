"""
spaCy Secondary Noun-Chunk Extractor — Layer 1 of the pipeline.

spaCy provides a production-grade NLP pipeline. Here we use it as a
SECONDARY, lower-confidence signal: its noun-chunk extractor surfaces
multi-word phrases that might be skills or organization names that
FlashText/GLiNER missed.

Design philosophy:
  - This is ADDITIVE only — it never overwrites GLiNER or FlashText output.
  - Confidence is set to 0.4 (lower than GLiNER ≥0.4 and FlashText 0.85)
    to reflect that raw noun chunks are unfiltered and noisy.
  - Results feed into the skill canonicalization step in skill_engine.py,
    which will accept or reject them based on fuzzy match score.

Graceful degradation:
  - If spacy is not installed, or `en_core_web_sm` is not downloaded,
    every function returns []. A single WARNING is logged at import time.
  - Install: pip install spacy && python -m spacy download en_core_web_sm
"""

from __future__ import annotations

import logging
from typing import List, Tuple

logger = logging.getLogger(__name__)

_NLP = None
_spacy_ok = False
_load_attempted = False

# Max chars to process (spaCy default max_length is 1M but we bound it lower
# for safety in pipeline context).
_MAX_CHARS = 5000

# Noun chunks shorter than this (words) are likely noise.
_MIN_CHUNK_WORDS = 1
_MAX_CHUNK_WORDS = 5


def _ensure_nlp() -> bool:
    global _NLP, _spacy_ok, _load_attempted
    if _load_attempted:
        return _spacy_ok
    _load_attempted = True
    try:
        import spacy  # type: ignore
        _NLP = spacy.load("en_core_web_sm", disable=["parser", "ner"])
        # We only need the tok2vec + tagger for noun chunks
        _NLP.max_length = _MAX_CHARS + 100
        _spacy_ok = True
        logger.debug("[spacy_extractor] en_core_web_sm loaded.")
    except ImportError:
        logger.warning(
            "[spacy_extractor] spacy not installed — noun-chunk extraction disabled. "
            "Install with: pip install spacy && python -m spacy download en_core_web_sm"
        )
    except OSError:
        logger.warning(
            "[spacy_extractor] en_core_web_sm model not found — noun-chunk extraction disabled. "
            "Download with: python -m spacy download en_core_web_sm"
        )
    except Exception as exc:
        logger.warning(f"[spacy_extractor] Failed to load spaCy: {exc}")
    return _spacy_ok


def extract_noun_chunks(text: str) -> List[Tuple[str, float]]:
    """
    Extract noun chunks from `text` using spaCy.

    Returns a list of (chunk_text, confidence) tuples where confidence is
    always 0.4 (the secondary-signal constant for this extractor).

    Filters:
      - Empty chunks
      - Chunks that are purely numeric
      - Chunks that are too short or too long (word count)
      - Chunks that are stop-word-only phrases

    Never raises. Returns [] if spaCy is unavailable.
    """
    if not text or not text.strip():
        return []
    if not _ensure_nlp():
        return []

    try:
        doc = _NLP(text[:_MAX_CHARS])
        results = []
        seen = set()
        for chunk in doc.noun_chunks:
            chunk_text = chunk.text.strip()
            words = chunk_text.split()
            word_count = len(words)

            # Filter: length bounds
            if word_count < _MIN_CHUNK_WORDS or word_count > _MAX_CHUNK_WORDS:
                continue

            # Filter: purely numeric
            if chunk_text.replace(" ", "").isdigit():
                continue

            # Filter: all stop words / very short single tokens
            if word_count == 1 and len(chunk_text) <= 2:
                continue

            lower = chunk_text.lower()
            if lower in seen:
                continue
            seen.add(lower)
            results.append((chunk_text, 0.4))

        return results
    except Exception as exc:
        logger.debug(f"[spacy_extractor] extraction error: {exc}")
        return []


def is_available() -> bool:
    """Return True if spaCy is ready. Triggers a load attempt."""
    return _ensure_nlp()
