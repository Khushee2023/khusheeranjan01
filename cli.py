"""
Thin CLI entrypoint for the Multi-Source Candidate Data Transformer.

Usage:
    python cli.py --input-dir sample_inputs --output output/default.json
    python cli.py --input-dir sample_inputs --config configs/example_config.json --output output/custom.json

Per the assignment: "a clean CLI is completely sufficient... don't spend your
time on polish here." This intentionally stays minimal â€” parse args, run the
pipeline, write JSON, print a short run summary to stdout.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from src.pipeline import run_pipeline
from src.projection.projector import ProjectionConfig


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the multi-source candidate data transformer."
    )
    parser.add_argument(
        "--input-dir", required=True,
        help="Directory containing recruiter.csv, ats.json, notes/, etc.",
    )
    parser.add_argument(
        "--output", required=True,
        help="Path to write the resulting JSON output.",
    )
    parser.add_argument(
        "--config", required=False, default=None,
        help="Path to a runtime projection config JSON. If omitted, emits the full default schema.",
    )
    parser.add_argument(
        "--notes-dir", required=False, default=None,
        help="Directory of recruiter notes .txt files (defaults to <input-dir>/notes).",
    )
    parser.add_argument(
        "--snapshot-dir", required=False, default="output",
        help="Directory to write the canonical snapshot (Stage 5). Defaults to 'output/'.",
    )
    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    if not input_dir.exists():
        print(f"Error: input directory '{input_dir}' does not exist.", file=sys.stderr)
        return 1

    projection_config = None
    if args.config:
        config_path = Path(args.config)
        if not config_path.exists():
            print(f"Error: config file '{config_path}' does not exist.", file=sys.stderr)
            return 1
        try:
            config_data = json.loads(config_path.read_text(encoding="utf-8"))
            projection_config = ProjectionConfig.model_validate(config_data)
        except Exception as exc:
            print(f"Error: failed to parse/validate config '{config_path}': {exc}", file=sys.stderr)
            return 1

    result = run_pipeline(
        input_dir,
        projection_config=projection_config,
        snapshot_dir=args.snapshot_dir,
    )

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(result.projected_output, indent=2, default=str),
        encoding="utf-8",
    )

    # --- run summary to stdout (not part of the JSON output, just operator feedback) ---
    print(f"Run ID:              {result.run_id}")
    print(f"Sources processed:   {result.sources_processed}")
    print(f"Sources skipped:     {result.sources_skipped}")
    print(f"Candidates produced: {len(result.candidates)}")
    if result.snapshot_path:
        print(f"Canonical snapshot:  {result.snapshot_path}")
    if result.errors:
        print(f"Errors encountered ({len(result.errors)}):", file=sys.stderr)
        for err in result.errors:
            print(f"  - {err}", file=sys.stderr)
    print(f"Output written to:   {output_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())