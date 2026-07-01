"""
Extractor for free-text recruiter notes (.txt files).

UPGRADED from the original heuristic-only version. Now wires in:

  Layer 0 Pre-flight:
    - layout_parser.tag_lines()   → indent-aware section detection
      Lines under "Skills:" heading are parsed as bullet points even when
      they're not preceded by a bullet character (just indented).
    - lang_detect.detect_language() → logs non-English content for tracing

  Layer 1 Extraction Engine:
    - gliner_extractor.extract_person() → primary NER name extraction
      (graceful degradation: falls back to regex if GLiNER unavailable)
    - flashtext_skills.extract_skills() → FlashText Aho-Corasick trie
      (canonical skill names, fast O(n) scan)
    - spacy_extractor.extract_noun_chunks() → secondary lower-confidence
      noun phrases (additive only, confidence=0.4)

Extraction priority (name):
  1. Explicit "Name:" / "Candidate:" label   (confidence 0.9)
  2. GLiNER PERSON entity                   (confidence = GLiNER score)
  3. Recruiter phrasing ("Spoke with X")    (confidence 0.75)
  4. First name-like line                   (confidence 0.6)
  5. Capitalized bigram fallback            (confidence 0.35)

Extraction priority (skills):
  1. FlashText trie (canonical)             (confidence 0.85)
  2. GLiNER SKILL entity                    (confidence = GLiNER score, min 0.4)
  3. spaCy noun chunks → skill_engine filter (confidence 0.4)

Design rule: "wrong-but-confident is worse than honestly-empty."
Notes are the LOWEST-TRUST source. If nothing useful is extracted from a
file, we return [] rather than polluting the pipeline with noise.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import List, Optional, Tuple

from src.models import ExtractionMethod, RawFieldValue, SourceRecord, SourceType

# ---- Pre-flight imports -------------------------------------------------
from src.preflight.layout_parser import (
    LineTag,
    TaggedLine,
    tag_lines,
    lines_in_section,
)
from src.preflight.lang_detect import detect_language
from src.preflight.lang_detect import is_latin_script

# ---- Extraction engine imports (all graceful-degradation safe) ----------
from src.extraction_engine import (
    extract_person as gliner_extract_person,
    flashtext_extract_skills,
    extract_noun_chunks,
)

# ---- Normalization imports ----------------------------------------------
from src.normalize.skill_engine import canonicalize_skill


# ---- Regex patterns (kept for fallback name extraction) -----------------

_EMAIL_PATTERN = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")

# Loosely matches phone-ish sequences; validity check happens in phone_engine.
_PHONE_PATTERN = re.compile(r"(\+?\d[\d\-\s().]{7,}\d)")

# Lines like "Name: Priya Sharma" or "Candidate: John Doe"
_NAME_LABEL_PATTERN = re.compile(
    r"^\s*(?:name|candidate)\s*[:\-]\s*(.+)$", re.IGNORECASE | re.MULTILINE
)

# Recruiter phrasing: "Spoke with X re:", "Met with X on", etc.
_NAME_CONTEXT_PATTERNS = [
    re.compile(r"\bspoke with ([A-Z][a-zA-Z'\-]+(?:\s[A-Z][a-zA-Z'\-]+){0,2})\b"),
    re.compile(r"\bmet with ([A-Z][a-zA-Z'\-]+(?:\s[A-Z][a-zA-Z'\-]+){0,2})\b"),
    re.compile(r"\bcalled ([A-Z][a-zA-Z'\-]+(?:\s[A-Z][a-zA-Z'\-]+){0,2})\b"),
    re.compile(r"\bcandidate ([A-Z][a-zA-Z'\-]+(?:\s[A-Z][a-zA-Z'\-]+){0,2})\b", re.IGNORECASE),
    re.compile(r"\binterviewed ([A-Z][a-zA-Z'\-]+(?:\s[A-Z][a-zA-Z'\-]+){0,2})\b"),
]

_CAPITALIZED_BIGRAM_PATTERN = re.compile(r"\b([A-Z][a-z]+ [A-Z][a-z]+)\b")

_BIGRAM_STOPWORDS = {
    "full stack", "front end", "back end", "project manager", "team lead",
    "will follow", "don't rely", "heads up", "next week",
}


# ---- Public entry point -------------------------------------------------

def extract_notes(path: str | Path) -> List[SourceRecord]:
    """
    Parse a single recruiter notes .txt file into one SourceRecord.
    Returns [] for missing/empty/unreadable files.
    """
    path = Path(path)
    if not path.exists() or path.stat().st_size == 0:
        return []

    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        print(f"[notes_extractor] failed to read {path}: {exc}")
        return []

    if not text.strip():
        return []

    record = SourceRecord(source_type=SourceType.RECRUITER_NOTES, source_id=path.name)

    # ---- Pre-flight: language detection & layout tagging ----------------
    lang = detect_language(text)
    if lang != "en":
        record.parse_errors.append(f"non_english_detected:{lang}")

    tagged = tag_lines(text)

    # ---- Name extraction ------------------------------------------------
    name, name_confidence, name_method = _extract_name(text)
    if name:
        record.full_name = RawFieldValue(
            value=name, method=name_method, confidence=name_confidence
        )

    # ---- Email extraction -----------------------------------------------
    for email in sorted(set(_EMAIL_PATTERN.findall(text))):
        record.emails.append(
            RawFieldValue(value=email, method=ExtractionMethod.REGEX, confidence=0.9)
        )

    # ---- Phone extraction -----------------------------------------------
    for phone_match in sorted(set(_PHONE_PATTERN.findall(text))):
        cleaned = phone_match.strip()
        if len(re.sub(r"\D", "", cleaned)) >= 7:
            record.phones.append(
                RawFieldValue(value=cleaned, method=ExtractionMethod.REGEX, confidence=0.6)
            )

    # ---- Skill extraction: multi-layer approach -------------------------
    found_skills = _extract_skills(text, tagged)
    for skill_name, confidence, method in found_skills:
        record.skills_raw.append(
            RawFieldValue(value=skill_name, method=method, confidence=confidence)
        )

    # Notes with nothing useful extracted are discarded (not crashed).
    if (
        record.full_name is None
        and not record.emails
        and not record.phones
        and not record.skills_raw
    ):
        return []

    return [record]


# ---- Name extraction: layered priority ----------------------------------

def _extract_name(text: str) -> Tuple[Optional[str], float, ExtractionMethod]:
    """
    Try name extraction in priority order. Returns (name, confidence, method).

    Priority:
      1. Explicit "Name:" label     → 0.9, REGEX
      2. GLiNER PERSON entity       → GLiNER score (≥0.4), NER_GLINER
      3. Recruiter context phrases  → 0.75, REGEX
      4. First name-like line       → 0.6, REGEX
      5. Capitalized bigram         → 0.35, REGEX
      6. None                       → 0.0, REGEX
    """
    # 1. Explicit label
    label_match = _NAME_LABEL_PATTERN.search(text)
    if label_match:
        candidate = label_match.group(1).strip()
        if candidate:
            return candidate, 0.9, ExtractionMethod.REGEX

    # 2. GLiNER (primary NER)
    gliner_result = gliner_extract_person(text)
    if gliner_result is not None:
        name, score = gliner_result
        if name and score >= 0.4:
            return name, round(score, 4), ExtractionMethod.NER_GLINER

    # 3. Context phrases
    for pattern in _NAME_CONTEXT_PATTERNS:
        m = pattern.search(text)
        if m:
            return m.group(1).strip(), 0.75, ExtractionMethod.REGEX

    # 4. First name-like line
    first_line = next((line.strip() for line in text.splitlines() if line.strip()), "")
    words = first_line.split()
    looks_name_like = (
        1 <= len(words) <= 4
        and not any(char.isdigit() for char in first_line)
        and "@" not in first_line
        and not first_line.endswith((".", "?", "!"))
    )
    if looks_name_like:
        return first_line, 0.6, ExtractionMethod.REGEX

    # 5. Capitalized bigram fallback
    for bigram_match in _CAPITALIZED_BIGRAM_PATTERN.finditer(text):
        candidate = bigram_match.group(1)
        if candidate.lower() not in _BIGRAM_STOPWORDS:
            return candidate, 0.35, ExtractionMethod.REGEX

    # 6. Unicode non-Latin line fallback (handles non-English notes when GLiNER
    #    is unavailable). Scans lines for content that is predominantly non-ASCII
    #    (i.e., the note is in a non-Latin script like Devanagari, Arabic, CJK).
    #    Takes the shortest non-empty, non-punctuation-heavy line as the name
    #    candidate at low confidence (0.4). This is the last resort before giving
    #    up — it's better than silently losing a real name.
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or len(stripped) < 2 or len(stripped) > 60:
            continue
        if is_latin_script(stripped):
            continue  # skip Latin lines (already handled by earlier steps)
        # Skip lines that look like phone/email patterns
        if any(c.isdigit() for c in stripped) and len(
            [c for c in stripped if c.isdigit()]
        ) > len(stripped) * 0.4:
            continue
        if "@" in stripped or "http" in stripped.lower():
            continue
        # Limit to lines that look name-length (1–4 whitespace-separated tokens)
        tokens = stripped.split()
        if 1 <= len(tokens) <= 4:
            return stripped, 0.40, ExtractionMethod.REGEX

    return None, 0.0, ExtractionMethod.REGEX


# ---- Skill extraction: multi-layer approach -----------------------------

def _extract_skills(
    text: str, tagged: List[TaggedLine]
) -> List[Tuple[str, float, ExtractionMethod]]:
    """
    Extract skills using three complementary layers:

    Layer A — FlashText trie (canonical names, confidence 0.85):
      Fast Aho-Corasick scan of full text.

    Layer B — Indent-aware section parsing (confidence 0.85):
      Lines under a "Skills" section heading are parsed as bullet points.
      Each bullet line is scanned for skill terms. This catches skills listed
      in a structured block that FlashText might miss if the line has heavy
      formatting.

    Layer C — GLiNER SKILL entities (confidence = GLiNER score, ≥ 0.4):
      Additive only — adds skills FlashText missed.

    Layer D — spaCy noun chunks → skill_engine filter (confidence 0.4):
      Secondary signal. Only adds a noun chunk if skill_engine can canonicalize
      it (i.e., it fuzzy-matches a known skill), preventing raw noise phrases
      from entering the pipeline.

    Returns: List of (canonical_name, confidence, ExtractionMethod) tuples.
    Deduplication: each canonical name appears at most once (highest confidence
    source wins).
    """
    seen: dict[str, Tuple[float, ExtractionMethod]] = {}

    def _add(name: str, conf: float, method: ExtractionMethod):
        """Add a skill, keeping the highest-confidence source if duplicate."""
        if name not in seen or conf > seen[name][0]:
            seen[name] = (conf, method)

    # Layer A: FlashText full-text scan
    for canonical in flashtext_extract_skills(text):
        _add(canonical, 0.85, ExtractionMethod.SKILL_TRIE)

    # Layer B: Indent-aware skill section parsing
    # Find all section headings that look like "Skills" / "Technical Skills" etc.
    skill_section_lines = []
    for section_keyword in ("skills", "technical skills", "technologies", "tools"):
        skill_section_lines.extend(lines_in_section(tagged, section_keyword))

    for tl in skill_section_lines:
        # Each non-blank bullet/body line in a skills section is treated as
        # a potential skill item — run FlashText on it.
        line_text = tl.raw.strip().lstrip("-•*▪·–— \t")
        if not line_text:
            continue
        for canonical in flashtext_extract_skills(line_text):
            _add(canonical, 0.85, ExtractionMethod.SKILL_TRIE)
        # Also try direct canonicalization of the whole line as a skill phrase
        direct = canonicalize_skill(line_text)
        if direct:
            _add(direct, 0.8, ExtractionMethod.SKILL_TRIE)

    # Layer C: GLiNER SKILL entities (if available)
    from src.extraction_engine.gliner_extractor import extract_skills as _gliner_skills
    for skill_text, score in _gliner_skills(text):
        canonical = canonicalize_skill(skill_text) or skill_text
        _add(canonical, round(score, 4), ExtractionMethod.NER_GLINER)

    # Layer D: spaCy noun chunks filtered through skill_engine
    for chunk_text, _conf in extract_noun_chunks(text):
        canonical = canonicalize_skill(chunk_text)
        if canonical:  # only add if skill_engine recognizes it
            _add(canonical, 0.4, ExtractionMethod.NER_SPACY)

    return [(name, conf, method) for name, (conf, method) in seen.items()]