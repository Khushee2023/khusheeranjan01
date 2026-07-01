"""
Canonical Profile Store — Stage 5 of the pipeline.

Writes an IMMUTABLE per-run snapshot of the fully-merged canonical candidates
to disk BEFORE the runtime projection gate applies any config-driven reshaping.

Design principles:
  - Immutable: a snapshot is written once per run and never mutated. If you
    re-run with the same run_id and different inputs, you get a new file
    with a new run_id (run_id includes a hash of the source fingerprint).
  - Deterministic: same candidates → same JSON bytes (sorted keys, no random
    ordering, no timestamp-derived values in the body).
  - Separation of concerns: the canonical record (what we know about a
    candidate) is stored independently of the projected output (how a consumer
    wants to see it). Downstream config changes never affect past snapshots.
  - Non-blocking: snapshot write failures are caught and logged; they never
    crash the pipeline or corrupt the projection stage.

Snapshot file layout:
    <snapshot_dir>/canonical_<run_id>.json

Where run_id is derived from:
    SHA-256( sorted(source_paths) + ISO-8601 run timestamp )[:12]

This makes it stable for the same source set while being unique per-run.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from src.models import CanonicalCandidate

logger = logging.getLogger(__name__)

# Default directory for snapshots (relative to CWD). Callers may override.
_DEFAULT_SNAPSHOT_DIR = Path("output")


def make_run_id(source_paths: List[str], timestamp: Optional[str] = None) -> str:
    """
    Produce a deterministic, collision-resistant run identifier.

    Inputs:
      source_paths  — list of source file paths/identifiers processed this run
                      (e.g. ["sample_inputs/ats.json", "sample_inputs/recruiter.csv"])
      timestamp     — ISO-8601 string (defaults to now in UTC). Injecting this
                      parameter makes the function fully testable without
                      time-dependent outputs.

    Returns a 12-char hex prefix of the SHA-256 digest — short enough to be
    human-readable in filenames, long enough to avoid collisions in practice.
    """
    if timestamp is None:
        timestamp = datetime.now(tz=timezone.utc).isoformat()

    # Sort paths for stability — order the caller passes shouldn't matter.
    fingerprint = json.dumps(
        {"sources": sorted(source_paths), "ts": timestamp},
        sort_keys=True,
    )
    digest = hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()
    return digest[:12]


class CanonicalStore:
    """
    Manages immutable per-run snapshots of merged CanonicalCandidate records.

    Usage:
        store = CanonicalStore(snapshot_dir=Path("output"))
        path = store.write_snapshot(candidates, run_id)
        # → writes output/canonical_<run_id>.json
    """

    def __init__(self, snapshot_dir: Path | str = _DEFAULT_SNAPSHOT_DIR) -> None:
        self._dir = Path(snapshot_dir)

    def snapshot_path(self, run_id: str) -> Path:
        """Return the expected path for a given run_id (whether or not it exists)."""
        return self._dir / f"canonical_{run_id}.json"

    def write_snapshot(
        self, candidates: List[CanonicalCandidate], run_id: str
    ) -> Optional[Path]:
        """
        Serialise `candidates` to an immutable JSON snapshot file.

        Returns the Path written on success, or None on failure.
        Never raises — write errors are caught and logged.

        The snapshot is the raw canonical model dump (same as project_default
        output), NOT any projected/config-filtered view. This ensures it is
        independent of any runtime config and can be re-projected later.

        JSON is written with:
          - indent=2 for readability
          - sort_keys=True for determinism (same candidates → same bytes)
          - default=str to handle datetime / enum values
        """
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            path = self.snapshot_path(run_id)

            payload = {
                "run_id": run_id,
                "written_at": datetime.now(tz=timezone.utc).isoformat(),
                "candidate_count": len(candidates),
                "candidates": [c.model_dump(mode="json") for c in candidates],
            }

            path.write_text(
                json.dumps(payload, indent=2, sort_keys=True, default=str),
                encoding="utf-8",
            )
            logger.info(
                f"[store] Canonical snapshot written: {path} "
                f"({len(candidates)} candidates)"
            )
            return path

        except Exception as exc:
            logger.error(
                f"[store] Failed to write canonical snapshot (run_id={run_id}): {exc}. "
                "Pipeline will continue — snapshot is advisory, not blocking."
            )
            return None

    def read_snapshot(self, run_id: str) -> Optional[dict]:
        """
        Read back a stored snapshot as a raw dict. Useful for audit and replay.

        Returns None if the snapshot does not exist or cannot be parsed.
        Never raises.
        """
        path = self.snapshot_path(run_id)
        if not path.exists():
            logger.warning(f"[store] Snapshot not found: {path}")
            return None

        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.error(f"[store] Failed to read snapshot {path}: {exc}")
            return None

    def list_snapshots(self) -> List[Path]:
        """
        Return all snapshot files in the snapshot directory, sorted by name
        (lexicographic = chronological when run_ids are timestamp-derived).
        """
        if not self._dir.exists():
            return []
        return sorted(self._dir.glob("canonical_*.json"))
