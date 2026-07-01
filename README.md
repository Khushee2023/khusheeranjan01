# Multi-Source Candidate Data Transformer

Deterministic DAG pipeline that ingests ATS JSON, recruiter CSV, resume PDFs, and recruiter notes, then resolves, merges, and projects a canonical candidate record.

---

## Setup

```bash
pip install -r requirements.txt
```

> **Note:** `gliner` and `spacy` are optional — the pipeline degrades gracefully if they are absent.

---

## Run

### Default output (full canonical schema)

```bash
python cli.py --input-dir sample_inputs --output output/default.json
```

### With a custom projection config

```bash
python cli.py \
  --input-dir sample_inputs \
  --config configs/example_config.json \
  --output output/custom.json
```

### All flags

| Flag | Required | Description |
|---|---|---|
| `--input-dir` | ✅ | Directory containing `recruiter.csv`, `ats.json`, `notes/`, etc. |
| `--output` | ✅ | Path to write the resulting JSON |
| `--config` | ➖ | Path to a runtime projection config JSON (omit for full schema) |
| `--notes-dir` | ➖ | Notes `.txt` directory (defaults to `<input-dir>/notes`) |
| `--snapshot-dir` | ➖ | Where to write the canonical snapshot (default: `output/`) |

---

## Sample Run Output (stdout)

Running against the provided `sample_inputs/`:

```
Run ID:              fb60e0c8c11b
Sources processed:   3
Sources skipped:     0
Candidates produced: 500
Canonical snapshot:  output/canonical_fb60e0c8c11b.json
Output written to:   output/default.json
```

---

## Produced Output

Output is a JSON array. Each element is a resolved candidate record. Example (first two records from `output/default.json`):

```json
[
  {
    "candidate_id": "a4de8c49-b04c-45f1-bff4-5c53d6418178",
    "full_name": "Jay Ramirez II",
    "emails": ["susanrogers@example.org"],
    "phones": ["+16157594078"],
    "location": null,
    "links": { "linkedin": null, "github": null, "portfolio": null, "other": [] },
    "skills": [],
    "headline": null,
    "years_experience": null,
    "experience": [
      { "company": "JetBlue", "title": "Angular2 Software Developer", "start": null, "end": null, "summary": null }
    ],
    "education": [],
    "provenance": [
      { "field": "full_name",           "source": "ats_json", "method": "direct_field", "raw_value": "Jay Ramirez II",          "confidence": 0.95 },
      { "field": "emails[...]",         "source": "ats_json", "method": "direct_field", "raw_value": "susanrogers@example.org", "confidence": 0.95 },
      { "field": "phones[+16157594078]","source": "ats_json", "method": "regex",        "raw_value": "(615)759-4078x1618",      "confidence": 0.57 }
    ],
    "overall_confidence": 0.8233,
    "source_records_merged": ["recruiter_csv", "ats_json"],
    "created_at": "2026-06-30T21:27:23.954744"
  },
  {
    "candidate_id": "5bf60c71-0363-4bd7-a6a5-704776b2e151",
    "full_name": "Michele Williams",
    "emails": ["kendragalloway@example.org"],
    "phones": [],
    "location": null,
    "links": { "linkedin": null, "github": null, "portfolio": null, "other": [] },
    "skills": [],
    "headline": null,
    "years_experience": null,
    "experience": [
      { "company": "Reid, Ferguson and Sanchez", "title": "Database Administrator/ IT Support", "start": null, "end": null, "summary": null }
    ],
    "education": [],
    "provenance": [
      { "field": "full_name",      "source": "ats_json", "method": "direct_field", "raw_value": "Michele Williams",          "confidence": 0.95 },
      { "field": "emails[...]",    "source": "ats_json", "method": "direct_field", "raw_value": "kendragalloway@example.org","confidence": 0.95 }
    ],
    "overall_confidence": 0.95,
    "source_records_merged": ["recruiter_csv", "ats_json"],
    "created_at": "2026-06-30T21:27:23.962779"
  }
]
```

**Key fields:**

| Field | Description |
|---|---|
| `candidate_id` | Stable UUID for the merged candidate |
| `full_name` | Unicode NFKC-normalized, authority-resolved name |
| `phones` | E.164 normalized (`+1XXXXXXXXXX`) |
| `provenance` | Full audit trail — every field logs source, method, raw value, and confidence |
| `overall_confidence` | Weighted aggregate: `Σ(source_trust × method_fidelity × cross-source_consensus)` |
| `source_records_merged` | Which source types contributed to this record |

---

## Tests

Run all tests:

```bash
pytest tests/ -v
```

### Test files

| File | What it covers |
|---|---|
| `test_date_engine.py` | `normalize_date` (ISO-8601, "Present" synonyms, year-only, inversion swap, garbage → None), `normalize_date_pair`, `parse_years_experience` |
| `test_skill_engine.py` | `canonicalize_skill` (exact alias: `js→JavaScript`, `k8s→Kubernetes`, `golang→Go`; fuzzy misspellings; unknown → None; deduplication; determinism) |
| `test_layout_parser.py` | `tag_lines` (heading / bullet / body / blank detection, indent levels, section context propagation), `lines_in_section`, two-column PDF layout detection |
| `test_multilingual_identity.py` | `resolve_identities` (Devanagari + Latin → merge via shared email; Arabic + Latin → merge via shared phone; CJK lenient threshold; Faker phone collision → no false merge; Jr./Sr. suffix stripping; first/last name swap → same token-sorted key) |
| `test_name_normalizer_multilingual.py` | Name key normalization across scripts, suffix stripping, transliteration stability |
| `test_indent_edge_cases.py` | Edge cases: mixed tabs/spaces, deeply nested bullets, single-line documents |
| `test_resume_extractor.py` | Resume PDF extraction smoke tests |

### Selected test assertions (what actually runs)

```python
# Date normalization
assert normalize_date("January 2018")      == "2018-01"
assert normalize_date("present")           == "present"
assert normalize_date("till date")         == "present"
assert normalize_date("garbage")           is None
start, end = normalize_date_pair("March 2022", "January 2018")
assert start == "2018-01"  # chronological inversion → swapped

# Skill canonicalization
assert canonicalize_skill("js")       == "JavaScript"
assert canonicalize_skill("k8s")      == "Kubernetes"
assert canonicalize_skill("golang")   == "Go"
assert canonicalize_skill("sklearn")  == "scikit-learn"
assert canonicalize_skill("bash")     == "Shell"
assert canonicalize_skill("garbage")  is None
assert canonicalize_skills(["js","javascript","JavaScript"]).count("JavaScript") == 1  # dedup

# Layout parser
tagged = tag_lines("Skills:\n  Python\n  Docker\nEducation:\n  MIT")
assert tagged[0].tag == LineTag.HEADING
assert tagged[1].tag == LineTag.BULLET   # indented → bullet
assert tagged[1].section == "Skills"

# Identity resolution
clusters = resolve_identities([ats_record("Priya Sharma", email="p@x.com"),
                                notes_record("प्रिया शर्मा",  email="p@x.com")])
assert len(clusters) == 1   # Devanagari transliterates → same key → merged

clusters = resolve_identities([ats_record("Jay Ramirez",  phone="+15559991234"),
                                ats_record("Susan Rogers", phone="+15559991234")])
assert len(clusters) == 2   # same phone, different names → NOT merged
```
