"""
Extractor for Recruiter CSV exports.

Expected (but not guaranteed) columns: name, email, phone, current_company, title.
Real-world CSVs are messy: missing columns, extra columns, header casing
differences, empty rows, BOM characters, encoding issues. This extractor is
built to degrade gracefully rather than crash on any of that.

Output: a list of SourceRecord (one per row), fully RAW â€” no normalization
happens here. Normalization is a separate pipeline stage (normalize/) so this
file's only job is "get the data out of the CSV safely."
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import List

from src.models import (
    Experience,
    ExtractionMethod,
    Links,
    RawFieldValue,
    SourceRecord,
    SourceType,
)

# Map of expected logical fields -> acceptable header variants we'll match
# (lowercased, stripped). Keeps the extractor resilient to header drift
# without silently inventing data for unmapped columns.
HEADER_ALIASES = {
    "name": {"name", "full_name", "fullname", "candidate_name"},
    "email": {"email", "email_address", "e-mail"},
    "phone": {"phone", "phone_number", "mobile", "contact_number"},
    "current_company": {"current_company", "company", "employer"},
    "title": {"title", "job_title", "role", "position"},
}


def _build_header_map(fieldnames: list[str]) -> dict[str, str]:
    """
    Map actual CSV header strings -> logical field names, based on HEADER_ALIASES.
    Unrecognized headers are simply ignored (not an error â€” CSVs may carry
    extra columns we don't care about).
    """
    header_map: dict[str, str] = {}
    for raw_header in fieldnames or []:
        normalized = raw_header.strip().lower()
        for logical_field, aliases in HEADER_ALIASES.items():
            if normalized in aliases:
                header_map[raw_header] = logical_field
                break
    return header_map


def extract_csv(path: str | Path) -> List[SourceRecord]:
    """
    Parse a recruiter CSV export into a list of SourceRecord, one per row.
    Never raises on a malformed file â€” returns an empty list and the caller's
    pipeline logs the failure, per the "robust" constraint.
    """
    path = Path(path)
    records: List[SourceRecord] = []

    if not path.exists() or path.stat().st_size == 0:
        return records  # missing/empty source -> no records, not a crash

    try:
        with path.open(newline="", encoding="utf-8-sig") as f:  # utf-8-sig handles BOM
            reader = csv.DictReader(f)
            header_map = _build_header_map(reader.fieldnames or [])

            for row_index, row in enumerate(reader):
                record = _row_to_record(row, header_map, source_id=f"{path.name}:row{row_index}")
                if record is not None:
                    records.append(record)

    except (csv.Error, UnicodeDecodeError, OSError) as exc:
        # Malformed file: log and return whatever we managed to parse so far.
        # In the full pipeline this gets surfaced via a run-level error log,
        # not swallowed silently.
        print(f"[csv_extractor] failed to fully parse {path}: {exc}")

    return records


def _row_to_record(
    row: dict,
    header_map: dict[str, str],
    source_id: str,
) -> SourceRecord | None:
    """Convert one CSV row into a SourceRecord. Returns None for fully-empty rows."""

    # Normalize row using header_map; unmapped columns are dropped.
    logical_row: dict[str, str] = {}
    for raw_header, value in row.items():
        if raw_header in header_map and value is not None:
            cleaned = value.strip()
            if cleaned:
                logical_row[header_map[raw_header]] = cleaned

    if not logical_row:
        return None  # fully empty row, skip rather than emit a hollow record

    record = SourceRecord(source_type=SourceType.RECRUITER_CSV, source_id=source_id)

    if "name" in logical_row:
        record.full_name = RawFieldValue(
            value=logical_row["name"],
            method=ExtractionMethod.DIRECT_FIELD,
            confidence=1.0,
        )

    if "email" in logical_row:
        record.emails.append(
            RawFieldValue(
                value=logical_row["email"],
                method=ExtractionMethod.DIRECT_FIELD,
                confidence=1.0,
            )
        )

    if "phone" in logical_row:
        record.phones.append(
            RawFieldValue(
                value=logical_row["phone"],
                method=ExtractionMethod.DIRECT_FIELD,
                confidence=1.0,
            )
        )

    if "title" in logical_row or "current_company" in logical_row:
        record.experience_raw.append(
            Experience(
                company=logical_row.get("current_company"),
                title=logical_row.get("title"),
                start=None,
                end=None,
                summary=None,
            )
        )

    return record