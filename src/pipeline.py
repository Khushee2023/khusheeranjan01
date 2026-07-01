"""
Pipeline orchestrator: wires every stage together end-to-end.

extract → identity resolution → reduction (merge) → canonical store
   → projection (default OR config-driven)

Stage ordering follows the architecture diagram exactly:
  0. Pre-flight   (layout parser, OCR, lang-detect)  ← inside each extractor
  1. Extraction   (GLiNER, FlashText, spaCy)          ← inside each extractor
  2. Normalization (phone, date, skill, name)          ← inside merge
  3. Graph Linkage (NetworkX identity resolution)      ← resolve_identities()
  4. Reduction    (weighted authority matrix merge)     ← merge_cluster()
  5. Canonical Store (immutable per-run snapshot)       ← CanonicalStore.write_snapshot()
  6. Runtime Projection Gate (Pydantic schema guard)   ← project() / project_default()

Each stage is wrapped so a failure in ONE source/record never crashes the
whole run — errors are collected and surfaced in run-level metadata instead,
per the assignment's "robust" constraint.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from src.extractors.ats_extractor import extract_ats
from src.extractors.csv_extractor import extract_csv
from src.extractors.notes_extractor import extract_notes
from src.extractors.resume_extractor import extract_resume
from src.identity.graph_linkage import resolve_identities
from src.models import CanonicalCandidate, SourceRecord
from src.projection.projector import ProjectionConfig, project, project_default
from src.reduction.merge import merge_cluster
from src.store import CanonicalStore, make_run_id


@dataclass
class PipelineRunResult:
    candidates: List[CanonicalCandidate] = field(default_factory=list)
    projected_output: List[dict] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    sources_processed: List[str] = field(default_factory=list)
    sources_skipped: List[str] = field(default_factory=list)
    # Stage 5: path to the immutable canonical snapshot written this run
    snapshot_path: Optional[Path] = None
    run_id: Optional[str] = None


def run_pipeline(
    input_dir: str | Path,
    projection_config: Optional[ProjectionConfig] = None,
    notes_dir: Optional[str | Path] = None,
    snapshot_dir: Optional[str | Path] = None,
) -> PipelineRunResult:
    """
    Run the full pipeline against an input directory containing the expected
    sample input files (recruiter.csv, ats.json, notes/*.txt, resumes/* if
    present). Missing files/dirs are skipped, not fatal.

    Args:
        input_dir:         Directory with source files.
        projection_config: Optional runtime config for output reshaping.
        notes_dir:         Override for the notes sub-directory location.
        snapshot_dir:      Where to write the canonical snapshot (Stage 5).
                           Defaults to <input_dir>/../output or "output/".
    """
    input_dir = Path(input_dir)
    notes_dir = Path(notes_dir) if notes_dir else input_dir / "notes"
    result = PipelineRunResult()

    all_records: List[SourceRecord] = []
    source_paths: List[str] = []  # collected for run_id fingerprint

    # ---- STAGE 0–1: extraction (pre-flight + hybrid engine inside each extractor) ----
    csv_path  = input_dir / "recruiter.csv"
    ats_path  = input_dir / "ats.json"

    records_csv = _safe_extract(result, "recruiter.csv", lambda: extract_csv(csv_path))
    if records_csv:
        source_paths.append(str(csv_path))
    all_records += records_csv

    records_ats = _safe_extract(result, "ats.json", lambda: extract_ats(ats_path))
    if records_ats:
        source_paths.append(str(ats_path))
    all_records += records_ats

    # ---- unstructured source: recruiter notes ----
    notes_records = _safe_extract_notes_dir(result, notes_dir)
    if notes_records:
        source_paths.append(str(notes_dir))
    all_records += notes_records

    # ---- unstructured source: resume PDFs ----
    resumes_dir = input_dir / "resumes"
    resume_records = _safe_extract_resumes_dir(result, resumes_dir)
    if resume_records:
        source_paths.append(str(resumes_dir))
    all_records += resume_records

    # NOTE: github/linkedin extractors plug in here the same way —
    # same contract: always return List[SourceRecord], never raise.

    if not all_records:
        result.errors.append("No usable records extracted from any source.")
        return result

    # ---- STAGE 3: identity resolution (NetworkX graph linkage) ----
    try:
        clusters = resolve_identities(all_records)
    except Exception as exc:  # identity resolution failing should not kill the run
        result.errors.append(f"identity_resolution_failed: {exc}")
        return result

    # ---- STAGE 4: reduction / merge, per cluster, isolated failures ----
    for cluster in clusters:
        try:
            candidate = merge_cluster(cluster)
            result.candidates.append(candidate)
        except Exception as exc:
            result.errors.append(
                f"merge_failed for cluster with {len(cluster.records)} records: {exc}"
            )

    # ---- STAGE 5: canonical store — immutable per-run snapshot ----
    # This is written BEFORE projection so that the canonical record is always
    # preserved independently of any runtime config. Snapshot failure is
    # non-fatal (logged inside CanonicalStore.write_snapshot).
    run_id = make_run_id(source_paths)
    result.run_id = run_id

    _snap_dir = Path(snapshot_dir) if snapshot_dir else Path("output")
    store = CanonicalStore(snapshot_dir=_snap_dir)
    result.snapshot_path = store.write_snapshot(result.candidates, run_id)

    # ---- STAGE 6: runtime projection gate (Pydantic schema guardrails) ----
    for candidate in result.candidates:
        try:
            if projection_config is not None:
                result.projected_output.append(project(candidate, projection_config))
            else:
                result.projected_output.append(project_default(candidate))
        except Exception as exc:
            result.errors.append(
                f"projection_failed for candidate_id={candidate.candidate_id}: {exc}"
            )

    return result


def _safe_extract(result: PipelineRunResult, source_name: str, extract_fn) -> List[SourceRecord]:
    """
    Run a single extractor with isolation: a crash here is logged and the
    source is skipped, the rest of the pipeline proceeds.
    """
    try:
        records = extract_fn()
        if records:
            result.sources_processed.append(source_name)
        else:
            result.sources_skipped.append(f"{source_name} (empty or missing)")
        return records
    except Exception as exc:
        result.errors.append(f"{source_name} extraction failed: {exc}")
        result.sources_skipped.append(source_name)
        return []


def _safe_extract_notes_dir(result: PipelineRunResult, notes_dir: Path) -> List[SourceRecord]:
    """
    Notes are one file per candidate, so this iterates the directory and runs
    extract_notes() per file, isolating failures PER FILE rather than per
    directory â€” one garbled .txt shouldn't drop every other candidate's notes.
    """
    if not notes_dir.exists() or not notes_dir.is_dir():
        result.sources_skipped.append("notes/ (directory missing)")
        return []

    txt_files = sorted(notes_dir.glob("*.txt"))
    if not txt_files:
        result.sources_skipped.append("notes/ (no .txt files found)")
        return []

    all_records: List[SourceRecord] = []
    processed_count = 0

    for txt_file in txt_files:
        try:
            records = extract_notes(txt_file)
            if records:
                all_records.extend(records)
                processed_count += 1
        except Exception as exc:
            result.errors.append(f"notes extraction failed for {txt_file.name}: {exc}")

    if processed_count:
        result.sources_processed.append(f"notes/ ({processed_count}/{len(txt_files)} files)")
    else:
        result.sources_skipped.append("notes/ (0 files yielded usable records)")

    return all_records


def _safe_extract_resumes_dir(result: PipelineRunResult, resumes_dir: Path) -> List[SourceRecord]:
    """
    Resumes are one PDF file per candidate. Iterates the directory and runs
    extract_resume() per file, isolating failures per file.
    """
    if not resumes_dir.exists() or not resumes_dir.is_dir():
        result.sources_skipped.append("resumes/ (directory missing)")
        return []

    pdf_files = sorted(resumes_dir.glob("*.pdf"))
    if not pdf_files:
        result.sources_skipped.append("resumes/ (no .pdf files found)")
        return []

    all_records: List[SourceRecord] = []
    processed_count = 0

    for pdf_file in pdf_files:
        try:
            records = extract_resume(pdf_file)
            if records:
                all_records.extend(records)
                processed_count += 1
        except Exception as exc:
            result.errors.append(f"resume extraction failed for {pdf_file.name}: {exc}")

    if processed_count:
        result.sources_processed.append(f"resumes/ ({processed_count}/{len(pdf_files)} files)")
    else:
        result.sources_skipped.append("resumes/ (0 files yielded usable records)")

    return all_records