"""
Pre-flight Layout Parser — Layer 0 of the pipeline.

Two responsibilities:
1. **Indent analysis** for plain-text inputs (.txt notes): classifies every
   line as HEADING, BULLET, BODY, or BLANK based on leading whitespace and
   punctuation patterns. Consumed by notes_extractor to detect section
   boundaries and parse indented bullet-point blocks correctly.

2. **Column layout detection** for PDF blocks (factored out from
   resume_extractor so it's reusable): determines whether a page is
   single- or two-column and returns blocks in the correct reading order.

Design rules:
- Deterministic: no randomness, no model weights.
- Never raises: all errors return a safe default (BODY / single-column).
- Input-agnostic: works on raw strings (for .txt) or fitz block lists (for PDF).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional, Tuple


# ---------------------------------------------------------------------------
# Line classification
# ---------------------------------------------------------------------------

class LineTag(str, Enum):
    HEADING = "heading"    # Section title line  (e.g. "Skills:", "Experience")
    BULLET  = "bullet"     # Indented or bulleted list item
    BODY    = "body"       # Regular prose line
    BLANK   = "blank"      # Empty / whitespace-only


@dataclass
class TaggedLine:
    raw: str                   # Original line content (unchanged)
    tag: LineTag
    indent_level: int          # 0 = no indent, 1 = ≥2 spaces / 1 tab, 2 = ≥4 spaces / 2 tabs
    section: Optional[str]     # Nearest heading text above this line (or None)


# Patterns for heading detection
_HEADING_PATTERN = re.compile(
    r"""
    ^                          # start of line (after stripping indent)
    (?:
        [A-Z][A-Z\s&/\-]{2,}  # ALL CAPS phrase (at least 3 chars)
      | [A-Z][a-z][\w\s]{1,30}  # Title Case phrase
    )
    \s*:?\s*$                  # optional trailing colon, then end
    """,
    re.VERBOSE,
)

# Common resume/notes section keywords (case-insensitive)
_SECTION_KEYWORDS = {
    "experience", "education", "skills", "summary", "profile", "objective",
    "employment", "work history", "certifications", "projects", "languages",
    "interests", "awards", "publications", "references", "contact",
    "technical skills", "professional experience", "career history",
}

# Bullet indicators at start of stripped line
_BULLET_PREFIXES = re.compile(r"^[\-\*\•\◦\▪\·\–\—]\s+")


def _normalize_indent(line: str) -> str:
    """
    Normalize indentation to a consistent space-only representation.

    Converts each leading tab to 4 equivalent spaces, then returns the
    resulting line. This makes mixed-indent lines (e.g. "\t  " = 1 tab +
    2 spaces) measurable on a single unified scale.

    Only the leading whitespace is affected — the rest of the line is
    returned unchanged. This function is used exclusively by _indent_level()
    and is not part of the public API.
    """
    # Walk character by character while we're still in the leading whitespace.
    normalized: list[str] = []
    in_leading = True
    for ch in line:
        if in_leading:
            if ch == "\t":
                normalized.append("    ")  # 1 tab → 4 spaces
            elif ch == " ":
                normalized.append(" ")
            else:
                in_leading = False
                normalized.append(ch)
        else:
            normalized.append(ch)
    return "".join(normalized)


def _indent_level(line: str) -> int:
    """
    Classify the indentation depth of a line on a 0–3 scale.

    Tabs are first converted to 4-space equivalents so that mixed
    tab+space indentation is measured consistently regardless of editor
    settings.

    Scale:
      0 → 0 leading spaces (no indent)
      1 → 1–3 leading spaces
      2 → 4–7 leading spaces (equivalent to 1 tab)
      3 → ≥ 8 leading spaces (equivalent to ≥ 2 tabs, deep nesting)

    Single-space indent (common in recruiter notes written in plain editors)
    is now level 1, not level 0 — previously it was silently discarded as
    "not indented", causing bullet points to be missed in skills sections.
    """
    normalized = _normalize_indent(line)
    stripped = normalized.lstrip(" ")
    n_spaces = len(normalized) - len(stripped)

    if n_spaces == 0:
        return 0
    if n_spaces <= 3:
        return 1
    if n_spaces <= 7:
        return 2
    return 3  # deep nesting: 8+ spaces / 2+ tabs


def _is_heading(stripped: str) -> bool:
    """Heuristic: is this line a section heading?"""
    if not stripped:
        return False
    lower = stripped.rstrip(":").strip().lower()
    if lower in _SECTION_KEYWORDS:
        return True
    # ALL-CAPS short line with optional trailing colon
    if stripped.isupper() and 2 <= len(stripped.rstrip(":")) <= 40:
        return True
    # Title Case line ending with colon
    if stripped.endswith(":") and stripped[:-1].istitle() and len(stripped) <= 50:
        return True
    return False


def tag_lines(text: str) -> List[TaggedLine]:
    """
    Tag every line in a plain-text document (notes .txt or extracted resume text).

    Returns a list of TaggedLine objects in document order. The `section`
    attribute of each TaggedLine is set to the nearest heading ABOVE it,
    making it trivial for extractors to slice out, say, all BULLET lines
    under the "Skills" heading.

    This is deterministic: same text → same output, always.
    """
    lines = text.splitlines()
    tagged: List[TaggedLine] = []
    current_section: Optional[str] = None

    for raw_line in lines:
        stripped = raw_line.strip()
        indent = _indent_level(raw_line)

        if not stripped:
            tagged.append(TaggedLine(raw=raw_line, tag=LineTag.BLANK, indent_level=0, section=current_section))
            continue

        if _is_heading(stripped):
            current_section = stripped.rstrip(":").strip()
            tagged.append(TaggedLine(raw=raw_line, tag=LineTag.HEADING, indent_level=indent, section=current_section))
            continue

        if _BULLET_PREFIXES.match(stripped) or indent >= 1:
            tagged.append(TaggedLine(raw=raw_line, tag=LineTag.BULLET, indent_level=indent, section=current_section))
            continue

        tagged.append(TaggedLine(raw=raw_line, tag=LineTag.BODY, indent_level=indent, section=current_section))

    return tagged


def lines_in_section(tagged: List[TaggedLine], section_name: str) -> List[TaggedLine]:
    """
    Return all non-BLANK, non-HEADING lines whose `section` matches
    `section_name` (case-insensitive). Useful for slicing a skill block or
    experience block out of the full tagged document.
    """
    target = section_name.strip().lower()
    return [
        tl for tl in tagged
        if tl.section and tl.section.lower() == target
        and tl.tag not in (LineTag.BLANK, LineTag.HEADING)
    ]


def extract_section_text(tagged: List[TaggedLine], section_name: str) -> str:
    """Return the raw text of all lines in a named section, joined by newlines."""
    return "\n".join(tl.raw for tl in lines_in_section(tagged, section_name))


# ---------------------------------------------------------------------------
# PDF column layout (factored out of resume_extractor)
# ---------------------------------------------------------------------------

@dataclass
class LayoutInfo:
    is_two_column: bool
    mid_x: float             # x-coordinate of the column split (0 if single-column)


def detect_pdf_layout(page_width: float, text_blocks: list) -> LayoutInfo:
    """
    Given a list of PyMuPDF text blocks (type 0 only, already filtered) and
    the page width, determine whether the page has a two-column layout.

    Returns a LayoutInfo. The mid_x can be used by the caller to sort blocks
    in correct reading order (left column top→bottom, then right column).

    `text_blocks` must be the raw fitz "blocks" list: each block is a tuple
    (x0, y0, x1, y1, text, block_no, block_type).
    """
    if not text_blocks or page_width == 0:
        return LayoutInfo(is_two_column=False, mid_x=0.0)

    mid_x = page_width / 2.0

    left_blocks  = [b for b in text_blocks if b[2] <= mid_x + 15]
    right_blocks = [b for b in text_blocks if b[0] >= mid_x - 15]

    is_two_column = len(left_blocks) > 2 and len(right_blocks) > 2

    return LayoutInfo(is_two_column=is_two_column, mid_x=mid_x if is_two_column else 0.0)


def sort_pdf_blocks(text_blocks: list, layout: LayoutInfo) -> list:
    """
    Sort text blocks into reading order according to the detected layout.

    Single-column: top-to-bottom, left-to-right (y quantized to 5pt buckets
    to handle slight baseline misalignments between adjacent blocks).
    Two-column:   left column (col=0) top-to-bottom, then right column (col=1).
    """
    if layout.is_two_column:
        def _block_key_two(b):
            col = 1 if b[0] >= layout.mid_x - 15 else 0
            y_bucket = round(b[1] / 5) * 5
            return (col, y_bucket, b[0])
        return sorted(text_blocks, key=_block_key_two)
    else:
        return sorted(text_blocks, key=lambda b: (round(b[1] / 5) * 5, b[0]))
