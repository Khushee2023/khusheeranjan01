"""
Extractor for ATS JSON blobs.

Real shape discovered from sample_inputs/ats.json:
[
  {
    "candidate_ref": "...",            # internal scrape ref, NOT used for matching
                                        # (synthetic-dataset artifact, not realistic
                                        # for production identity resolution â€” kept
                                        # only as a debug/test field, see provenance note)
    "person": {
      "display_name": "...",
      "contact_email": "...",
      "contact_phone": "..."
    },
    "current_role": "...",
    "employer": "...",
    "city_state": "...",
    "tagged_skills": "comma, separated, string",
    "most_recent_start": "January 2018",
    "most_recent_end": "Present",
    "summary_text": "..."
  },
  ...
]

The assignment is explicit: ATS field names do NOT match our canonical names,
and this confirms it â€” person info is nested, skills are a flat comma string,
dates are human-readable month-year text. This extractor's job is purely
structural remapping; date parsing into YYYY-MM and skill canonicalization
happen downstream in normalize/.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, List

from src.models import (
    Experience,
    ExtractionMethod,
    RawFieldValue,
    SourceRecord,
    SourceType,
)


def extract_ats(path: str | Path) -> List[SourceRecord]:
    """
    Parse an ATS JSON export into a list of SourceRecord.
    Tolerates: missing file, empty file, malformed JSON, missing nested
    "person" object, missing individual fields.
    """
    path = Path(path)
    records: List[SourceRecord] = []

    if not path.exists() or path.stat().st_size == 0:
        return records

    try:
        raw_text = path.read_text(encoding="utf-8")
        data = json.loads(raw_text)
    except (json.JSONDecodeError, UnicodeDecodeError, OSError) as exc:
        print(f"[ats_extractor] failed to parse {path}: {exc}")
        return records

    if isinstance(data, list):
        blobs = [b for b in data if isinstance(b, dict)]
    elif isinstance(data, dict):
        blobs = [data]
    else:
        return records

    for idx, blob in enumerate(blobs):
        record = _blob_to_record(blob, source_id=f"{path.name}:item{idx}")
        if record is not None:
            records.append(record)

    return records


def _blob_to_record(blob: dict, source_id: str) -> SourceRecord | None:
    if not blob:
        return None

    person: dict = blob.get("person") or {}

    record = SourceRecord(source_type=SourceType.ATS_JSON, source_id=source_id)

    display_name = person.get("display_name")
    if display_name and str(display_name).strip():
        record.full_name = RawFieldValue(
            value=str(display_name).strip(),
            method=ExtractionMethod.DIRECT_FIELD,
            confidence=1.0,
        )

    contact_email = person.get("contact_email")
    if contact_email and str(contact_email).strip():
        record.emails.append(
            RawFieldValue(
                value=str(contact_email).strip(),
                method=ExtractionMethod.DIRECT_FIELD,
                confidence=1.0,
            )
        )

    contact_phone = person.get("contact_phone")
    if contact_phone and str(contact_phone).strip():
        record.phones.append(
            RawFieldValue(
                value=str(contact_phone).strip(),
                method=ExtractionMethod.DIRECT_FIELD,
                confidence=1.0,
            )
        )

    current_role = blob.get("current_role")
    employer = blob.get("employer")
    if current_role or employer:
        record.experience_raw.append(
            Experience(
                company=str(employer).strip() if employer else None,
                title=str(current_role).strip() if current_role else None,
                start=_clean_date_text(blob.get("most_recent_start")),
                end=_clean_date_text(blob.get("most_recent_end")),
                summary=str(blob.get("summary_text")).strip() if blob.get("summary_text") else None,
            )
        )

    tagged_skills = blob.get("tagged_skills")
    if tagged_skills and str(tagged_skills).strip():
        for raw_skill in str(tagged_skills).split(","):
            skill_text = raw_skill.strip()
            # Strip parenthetical experience annotations like "(Less than 1 year)"
            # â€” that's duration metadata, not part of the skill name itself.
            # Left as raw text here; skill_engine.py handles real canonicalization.
            if skill_text:
                record.skills_raw.append(
                    RawFieldValue(
                        value=skill_text,
                        method=ExtractionMethod.DIRECT_FIELD,
                        confidence=0.85,
                    )
                )

    if record.full_name is None and not record.emails and not record.phones:
        return None

    return record


def _clean_date_text(value: Any) -> str | None:
    """
    Pass through raw date text (e.g. "January 2018", "Present") for now â€”
    actual parsing into YYYY-MM happens in normalize/date_engine.py. Kept as
    a separate function here so the extractor stays a pure structural mapper.
    """
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None