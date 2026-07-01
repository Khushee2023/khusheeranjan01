"""
Resume PDF data extractor using PyMuPDF (fitz).

UPGRADED from the original version. Now wires in:

  Layer 0 Pre-flight:
    - layout_parser.detect_pdf_layout() + sort_pdf_blocks()
      Column-aware reading order (factored into reusable module)
    - ocr_engine.ocr_page_if_needed()
      Tesseract OCR conditional fallback when page text is empty/garbled
    - lang_detect.detect_language()
      Logs non-English content; used to inform transliteration path

  Layer 1 Extraction Engine:
    - gliner_extractor.extract_person()  → primary NER name extraction
    - flashtext_skills.extract_skills()  → Aho-Corasick canonical skill trie

All new imports degrade gracefully: if a library is missing, extraction
falls back to the original heuristic approach.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import List, Optional, Tuple
import fitz  # PyMuPDF

from src.models import (
    Education,
    Experience,
    ExtractionMethod,
    Links,
    RawFieldValue,
    SourceRecord,
    SourceType,
)

# ---- Pre-flight imports -------------------------------------------------
from src.preflight.layout_parser import detect_pdf_layout, sort_pdf_blocks
from src.preflight.ocr_engine import ocr_page_if_needed
from src.preflight.lang_detect import detect_language

# ---- Extraction engine imports ------------------------------------------
from src.extraction_engine.gliner_extractor import extract_person as gliner_extract_person
from src.extraction_engine.flashtext_skills import extract_skills as flashtext_extract_skills


# ---- Common regex patterns ----------------------------------------------

_EMAIL_PATTERN = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
_PHONE_PATTERN = re.compile(r"(\+?\d[\d\-\s().]{7,}\d)")

_NAME_LABEL_PATTERN = re.compile(
    r"^\s*(?:name|candidate|fullname)\s*[:\-]\s*(.+)$", re.IGNORECASE | re.MULTILINE
)


# ---- Public entry point -------------------------------------------------

def extract_resume(path: str | Path) -> List[SourceRecord]:
    """
    Extract structured candidate data from a resume PDF using PyMuPDF.
    Returns a List[SourceRecord] containing the extracted candidate profile.
    """
    path = Path(path)
    if not path.exists() or path.stat().st_size == 0:
        return []

    try:
        doc = fitz.open(path)
    except Exception as exc:
        print(f"[resume_extractor] failed to open PDF {path}: {exc}")
        return []

    full_text_parts = []
    ocr_used = False

    for page_idx, page in enumerate(doc):
        try:
            blocks = page.get_text("blocks")
        except Exception as exc:
            print(f"[resume_extractor] failed to extract blocks from page {page_idx}: {exc}")
            continue

        # Filter for text blocks (type 0)
        text_blocks = [b for b in blocks if b[6] == 0]

        # Use layout_parser for column-aware reading order
        layout = detect_pdf_layout(page.rect.width, text_blocks)
        sorted_blocks = sort_pdf_blocks(text_blocks, layout)

        native_text = "\n".join(b[4] for b in sorted_blocks)

        # OCR conditional fallback (Layer 0 Pre-flight)
        page_text, ocr_note = ocr_page_if_needed(page, native_text)
        if ocr_note == "ocr_success":
            ocr_used = True

        full_text_parts.append(page_text)

    raw_content = "\n\n".join(full_text_parts)

    if not raw_content.strip():
        record = SourceRecord(
            source_type=SourceType.RESUME,
            source_id=path.name,
            parse_errors=["empty_resume_text"]
        )
        return [record]

    # Initialize SourceRecord
    record = SourceRecord(source_type=SourceType.RESUME, source_id=path.name)

    if ocr_used:
        record.parse_errors.append("ocr_fallback_used")

    # Language detection
    lang = detect_language(raw_content)
    if lang != "en":
        record.parse_errors.append(f"non_english_detected:{lang}")

    # 1. Extract Emails
    for email in sorted(set(_EMAIL_PATTERN.findall(raw_content))):
        record.emails.append(
            RawFieldValue(value=email, method=ExtractionMethod.REGEX, confidence=0.95)
        )

    # 2. Extract Phones
    for phone in sorted(set(_PHONE_PATTERN.findall(raw_content))):
        cleaned = phone.strip()
        if len(re.sub(r"\D", "", cleaned)) >= 7:
            record.phones.append(
                RawFieldValue(value=cleaned, method=ExtractionMethod.REGEX, confidence=0.9)
            )

    # 3. Extract Name — GLiNER first, then heuristics
    name, name_conf, name_method = _extract_name(raw_content, path.stem)
    if name:
        record.full_name = RawFieldValue(value=name, method=name_method, confidence=name_conf)

    # 4. Extract Links
    record.links = _extract_links(raw_content)

    # 5. Extract Location
    loc = _extract_location(raw_content)
    if loc:
        record.location_raw = RawFieldValue(value=loc, method=ExtractionMethod.REGEX, confidence=0.8)

    # 6. Extract Skills — FlashText trie (primary)
    for skill in flashtext_extract_skills(raw_content):
        record.skills_raw.append(
            RawFieldValue(value=skill, method=ExtractionMethod.SKILL_TRIE, confidence=0.85)
        )

    # 7. Extract Experience
    record.experience_raw = _extract_experience(raw_content)

    # 8. Extract Education
    record.education_raw = _extract_education(raw_content)

    # 9. Extract Headline
    headline = _extract_headline(raw_content, record.experience_raw)
    if headline:
        record.headline = RawFieldValue(
            value=headline, method=ExtractionMethod.DIRECT_FIELD, confidence=0.8
        )

    return [record]


# ---- Name extraction ----------------------------------------------------

def _extract_name(
    text: str, filename_stem: str
) -> Tuple[Optional[str], float, ExtractionMethod]:
    """
    Extract candidate name. Priority:
      1. Explicit "Name:" label (REGEX, 0.95)
      2. GLiNER PERSON entity (NER_GLINER, GLiNER score)
      3. First capitalized line heuristic (REGEX, 0.85)
      4. Filename fallback (REGEX, 0.70)
    """
    # 1. Name label
    label_match = _NAME_LABEL_PATTERN.search(text)
    if label_match:
        name = label_match.group(1).strip()
        if name and len(name.split()) <= 4:
            return name, 0.95, ExtractionMethod.REGEX

    # 2. GLiNER
    gliner_result = gliner_extract_person(text[:2000])  # first page is enough
    if gliner_result is not None:
        name, score = gliner_result
        if name and score >= 0.4:
            return name, round(score, 4), ExtractionMethod.NER_GLINER

    # 3. First capitalized line heuristic
    blacklist_words = {
        "resume", "curriculum", "vitae", "cv", "portfolio", "contact",
        "email", "phone", "address", "page", "profile", "summary",
        "experience", "education", "skills", "about", "me"
    }
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for line in lines[:5]:
        cleaned_line = re.sub(r"[^\w\s-]", "", line).strip()
        words = cleaned_line.split()
        if 2 <= len(words) <= 4:
            is_valid_name = all(
                w[0].isupper() and w.lower() not in blacklist_words
                for w in words if w
            )
            if is_valid_name:
                return cleaned_line, 0.85, ExtractionMethod.REGEX

    # 4. Filename fallback
    clean_stem = filename_stem.replace("_", " ").replace("-", " ").strip()
    words = clean_stem.split()
    filtered_words = [
        w for w in words
        if w.lower() not in {"resume", "cv", "pdf", "docx", "2026", "2025"}
    ]
    if 2 <= len(filtered_words) <= 4:
        title_cased = " ".join(w.capitalize() for w in filtered_words)
        return title_cased, 0.70, ExtractionMethod.REGEX

    return None, 0.0, ExtractionMethod.REGEX


# ---- Supporting extractors (unchanged from original) --------------------

def _extract_links(text: str) -> Links:
    links = Links()
    linkedin_match = re.search(
        r"(?:https?://)?(?:www\.)?linkedin\.com/in/([a-zA-Z0-9_-]+)", text, re.IGNORECASE
    )
    if linkedin_match:
        links.linkedin = f"https://linkedin.com/in/{linkedin_match.group(1)}"

    github_match = re.search(
        r"(?:https?://)?(?:www\.)?github\.com/([a-zA-Z0-9_-]+)", text, re.IGNORECASE
    )
    if github_match:
        username = github_match.group(1)
        if username.lower() not in {"settings", "features", "about", "pricing", "explore"}:
            links.github = f"https://github.com/{username}"

    url_pattern = re.compile(r"https?://(?:www\.)?([a-zA-Z0-9.-]+\.[a-zA-Z]{2,})(/[^\s]*)?")
    for match in url_pattern.finditer(text):
        url = match.group(0).rstrip(".,)>;")
        if "linkedin.com" not in url and "github.com" not in url:
            if url not in links.other and len(links.other) < 5:
                if any(x in url.lower() for x in ["portfolio", "personal", "me.", "blog", "github.io"]):
                    links.portfolio = url
                else:
                    links.other.append(url)
    return links


def _extract_location(text: str) -> Optional[str]:
    loc_pattern = re.compile(r"\b([A-Z][a-zA-Z\s]{1,20}),\s?([A-Z]{2}|[A-Z][a-zA-Z\s]{1,15})\b")
    lines = text.splitlines()[:15]
    for line in lines:
        match = loc_pattern.search(line)
        if match:
            matched_text = match.group(0).strip()
            if not any(
                x in matched_text.lower()
                for x in ["present", "jan", "feb", "mar", "apr", "may", "jun",
                           "jul", "aug", "sep", "oct", "nov", "dec"]
            ):
                return matched_text
    return None


def _extract_experience(text: str) -> List[Experience]:
    experiences: List[Experience] = []

    section_patterns = [
        r"\b(?:work|professional|employment|career)\s+experience\b",
        r"\bwork\s+history\b",
        r"\bexperience\b",
    ]
    start_idx = -1
    for p in section_patterns:
        match = re.search(p, text, re.IGNORECASE)
        if match:
            start_idx = match.end()
            break

    if start_idx == -1:
        return experiences

    end_patterns = [
        r"\b(?:education|academic|studies|certifications|projects|skills|summary|interests)\b"
    ]
    end_idx = len(text)
    for p in end_patterns:
        match = re.search(p, text[start_idx:], re.IGNORECASE)
        if match:
            end_idx = start_idx + match.start()
            break

    section_text = text[start_idx:end_idx].strip()
    if not section_text:
        return experiences

    date_regex = re.compile(
        r"((?:\d{1,2}/)?(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{4}|\d{4})"
        r"\s*(?:-|to)\s*"
        r"(Present|\d{1,2}/\d{4}|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{4}|\d{4})",
        re.IGNORECASE,
    )

    lines = section_text.splitlines()
    job_blocks = []
    current_block: List[str] = []

    for line in lines:
        if date_regex.search(line):
            if current_block:
                job_blocks.append(current_block)
            current_block = [line]
        elif current_block:
            current_block.append(line)

    if current_block:
        job_blocks.append(current_block)

    for block in job_blocks:
        first_line = block[0]
        date_match = date_regex.search(first_line)
        if not date_match:
            continue

        start_date = date_match.group(1).strip()
        end_date   = date_match.group(2).strip()
        leftover   = date_regex.sub("", first_line).strip()
        leftover   = re.sub(r"[|\-•,;]+", " ", leftover).strip()

        title   = None
        company = None

        if " at " in leftover:
            parts = leftover.split(" at ", 1)
            title, company = parts[0].strip(), parts[1].strip()
        elif " - " in leftover:
            parts = leftover.split(" - ", 1)
            title, company = parts[0].strip(), parts[1].strip()
        else:
            words = leftover.split()
            if len(words) > 2:
                title   = " ".join(words[:2])
                company = " ".join(words[2:])
            else:
                title = leftover

        summary_lines = [l.strip() for l in block[1:] if l.strip()]
        summary = " ".join(summary_lines) if summary_lines else None
        if summary and len(summary) > 500:
            summary = summary[:497] + "..."

        experiences.append(
            Experience(
                company=company,
                title=title,
                start=start_date,
                end=end_date,
                summary=summary,
            )
        )

    return experiences


def _extract_education(text: str) -> List[Education]:
    educations: List[Education] = []

    section_patterns = [r"\beducation\b", r"\bacademic\b"]
    start_idx = -1
    for p in section_patterns:
        match = re.search(p, text, re.IGNORECASE)
        if match:
            start_idx = match.end()
            break

    if start_idx == -1:
        return educations

    end_patterns = [
        r"\b(?:experience|work|professional|projects|skills|certifications|interests)\b"
    ]
    end_idx = len(text)
    for p in end_patterns:
        match = re.search(p, text[start_idx:], re.IGNORECASE)
        if match:
            end_idx = start_idx + match.start()
            break

    section_text = text[start_idx:end_idx].strip()
    if not section_text:
        return educations

    degree_patterns = [
        (r"\bb\.?\s*s\.?\b|\bbachelor\b", "Bachelor of Science"),
        (r"\bm\.?\s*s\.?\b|\bmaster\b",   "Master of Science"),
        (r"\bph\.?\s*d\.?\b",             "Ph.D."),
        (r"\bb\.?\s*tech\b",              "Bachelor of Technology"),
        (r"\bm\.?\s*tech\b",              "Master of Technology"),
        (r"\bb\.?\s*a\.?\b",              "Bachelor of Arts"),
        (r"\bm\.?\s*a\.?\b",              "Master of Arts"),
    ]

    for line in [l.strip() for l in section_text.splitlines() if l.strip()]:
        degree_found = None
        degree_name  = None
        for pattern, d_name in degree_patterns:
            if re.search(pattern, line, re.IGNORECASE):
                degree_found = True
                degree_name  = d_name
                break

        if degree_found:
            year_match   = re.search(r"\b(19\d{2}|20\d{2})\b", line)
            end_year     = int(year_match.group(1)) if year_match else None
            institution  = None
            field_study  = None

            inst_match = re.search(
                r"\b([A-Za-z\s]+(?:University|College|Institute|School))", line, re.IGNORECASE
            )
            if inst_match:
                institution = inst_match.group(1).strip()

            field_match = re.search(
                r"\bin\s+([A-Za-z\s]+?)(?:,|$|\b(19|20)\d{2}\b)", line, re.IGNORECASE
            )
            if field_match:
                field_study = field_match.group(1).strip()

            if not institution:
                parts = line.split(",")
                institution = parts[1].strip() if len(parts) > 1 else line

            educations.append(
                Education(
                    institution=institution,
                    degree=degree_name,
                    field=field_study,
                    end_year=end_year,
                )
            )

    return educations


def _extract_headline(text: str, experience: List[Experience]) -> Optional[str]:
    if experience:
        first_job = experience[0]
        if first_job.title:
            if first_job.company:
                return f"{first_job.title} at {first_job.company}"
            return first_job.title

    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if len(lines) > 1:
        headline_candidate = lines[1]
        if len(headline_candidate) < 60 and not any(
            x in headline_candidate.lower() for x in ["email", "@", "phone", "http"]
        ):
            return headline_candidate

    return None
