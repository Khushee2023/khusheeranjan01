"""
Runtime projection layer: reshapes a CanonicalCandidate into whatever output
shape a runtime config requests, WITHOUT touching the canonical record itself.

This is the "same engine, no code changes" requirement from the assignment.
Config drives:
  - which fields to include
  - renaming/remapping via dotted "from" paths into the canonical record
  - per-field normalization hints (mostly informational here, since actual
    normalization already happened upstream â€” but re-validated here)
  - provenance/confidence inclusion toggle
  - missing-value policy: "null" | "omit" | "error"

The canonical record (CanonicalCandidate) and the projected output are kept
as two distinct types on purpose â€” the projector never mutates the canonical
record, it only reads from it.
"""

from __future__ import annotations

import re
from typing import Any, List, Literal, Optional

from pydantic import BaseModel, Field, ValidationError

from src.models import CanonicalCandidate


# ---------------------------------------------------------------------------
# Config schema
# ---------------------------------------------------------------------------

OnMissingPolicy = Literal["null", "omit", "error"]


class FieldSpec(BaseModel):
    path: str                          # output field name, e.g. "primary_email"
    type: str                          # "string" | "string[]" | "number" | etc â€” advisory + validated
    from_: Optional[str] = Field(default=None, alias="from")  # dotted canonical path, defaults to `path`
    normalize: Optional[str] = None    # "E164" | "canonical" | None
    required: bool = False

    class Config:
        populate_by_name = True


class ProjectionConfig(BaseModel):
    fields: List[FieldSpec]
    include_confidence: bool = False
    include_provenance: bool = False
    on_missing: OnMissingPolicy = "null"


class MissingRequiredFieldError(Exception):
    """Raised when on_missing == 'error' and a required field resolves to None."""


# ---------------------------------------------------------------------------
# Path resolution against the canonical record
# ---------------------------------------------------------------------------

_INDEX_PATTERN = re.compile(r"^(\w+)\[(\d*)\]$")          # e.g. emails[0] or emails[]
_NESTED_PATTERN = re.compile(r"^(\w+)\[\]\s+(\w+)$")      # e.g. "skills[] name"


def _resolve_path(record: CanonicalCandidate, path: str) -> Any:
    """
    Resolve a dotted/bracketed canonical path against a CanonicalCandidate.
    Supports:
      "full_name"            -> scalar attribute
      "location.country"     -> nested attribute
      "emails[0]"             -> indexed list element
      "emails[]"               -> full list
      "skills[] name"          -> list of a sub-attribute across all items
    Returns None (never raises) if any segment is missing/out of range â€”
    missing data is expected and handled by on_missing, not by exceptions.
    """
    nested_list_match = _NESTED_PATTERN.match(path)
    if nested_list_match:
        list_attr, sub_attr = nested_list_match.groups()
        container = getattr(record, list_attr, None)
        if not container:
            return None
        return [getattr(item, sub_attr, None) for item in container]

    current: Any = record
    for segment in path.split("."):
        index_match = _INDEX_PATTERN.match(segment)
        if index_match:
            attr_name, index_str = index_match.groups()
            current = getattr(current, attr_name, None)
            if current is None:
                return None
            if index_str == "":
                return current  # full list requested
            index = int(index_str)
            if not isinstance(current, list) or index >= len(current):
                return None
            current = current[index]
        else:
            current = getattr(current, segment, None)
            if current is None:
                return None

    return current


# ---------------------------------------------------------------------------
# Normalization re-application (defensive; values should already be
# normalized upstream, but the projector validates the contract holds)
# ---------------------------------------------------------------------------

def _apply_normalize_hint(value: Any, normalize: Optional[str]) -> Any:
    """
    Values entering the projector should already be normalized by the
    pipeline's normalize stage. This is a thin pass-through + sanity check,
    not a second normalization pass â€” re-normalizing here would risk
    diverging from the canonical record's provenance.
    """
    if normalize == "E164" and isinstance(value, str) and not value.startswith("+"):
        # Canonical record promised E.164; if it isn't, treat as malformed
        # rather than silently passing through a non-conformant value.
        return None
    return value


# ---------------------------------------------------------------------------
# Confidence/provenance lookup helpers
# ---------------------------------------------------------------------------

def _confidence_for_path(record: CanonicalCandidate, canonical_path: str) -> Optional[float]:
    """Find a matching provenance entry's confidence for a given canonical path, if any."""
    base_field = canonical_path.split("[")[0].split(".")[0]
    matches = [p.confidence for p in record.provenance if p.field.startswith(base_field)]
    if not matches:
        return None
    return round(sum(matches) / len(matches), 4)


def _provenance_for_path(record: CanonicalCandidate, canonical_path: str) -> list[dict]:
    base_field = canonical_path.split("[")[0].split(".")[0]
    return [
        {"source": p.source, "method": p.method, "confidence": p.confidence}
        for p in record.provenance
        if p.field.startswith(base_field)
    ]


# ---------------------------------------------------------------------------
# Main projection entrypoint
# ---------------------------------------------------------------------------

def project(record: CanonicalCandidate, config: ProjectionConfig) -> dict:
    """
    Apply a ProjectionConfig to a CanonicalCandidate, returning a plain dict
    ready for JSON serialization. Raises MissingRequiredFieldError only when
    on_missing == "error" AND a required field is actually missing â€”
    everything else degrades per on_missing policy.
    """
    output: dict[str, Any] = {}

    for field_spec in config.fields:
        canonical_path = field_spec.from_ or field_spec.path
        raw_value = _resolve_path(record, canonical_path)
        value = _apply_normalize_hint(raw_value, field_spec.normalize)

        is_missing = value is None or value == [] or value == ""

        if is_missing:
            if field_spec.required and config.on_missing == "error":
                raise MissingRequiredFieldError(
                    f"Required field '{field_spec.path}' (from '{canonical_path}') is missing."
                )
            if config.on_missing == "omit":
                continue
            output[field_spec.path] = None  # "null" policy (also the default for non-required gaps)
            value = None
        else:
            output[field_spec.path] = value

        if value is not None and config.include_confidence:
            output[f"{field_spec.path}_confidence"] = _confidence_for_path(record, canonical_path)

        if value is not None and config.include_provenance:
            output[f"{field_spec.path}_provenance"] = _provenance_for_path(record, canonical_path)

    return output


def project_default(record: CanonicalCandidate) -> dict:
    """
    The "no config supplied" path: dump the full canonical schema as-is,
    including provenance and overall_confidence. This satisfies the
    assignment's requirement to emit schema-valid JSON for the DEFAULT
    schema even when no custom config is given.
    """
    return record.model_dump(mode="json")