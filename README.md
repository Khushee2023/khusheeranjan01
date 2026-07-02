<div align="center">

<img src="https://img.shields.io/badge/Python-3.10%2B-3776AB?style=for-the-badge&logo=python&logoColor=white" />
<img src="https://img.shields.io/badge/Pydantic-v2-E92063?style=for-the-badge&logo=pydantic&logoColor=white" />
<img src="https://img.shields.io/badge/NetworkX-Graph_Linkage-FF6B35?style=for-the-badge&logo=python&logoColor=white" />
<img src="https://img.shields.io/badge/FastAPI-REST_API-009688?style=for-the-badge&logo=fastapi&logoColor=white" />
<img src="https://img.shields.io/badge/GLiNER-Zero--Shot_NER-6C3483?style=for-the-badge&logo=huggingface&logoColor=white" />
<img src="https://img.shields.io/badge/License-MIT-22C55E?style=for-the-badge" />

<br /><br />

# 🧬 Multi-Source Candidate Data Transformer

### *Deterministic, audit-complete candidate intelligence — from chaos to canonical.*

**A production-grade DAG pipeline** that ingests ATS JSON, recruiter CSVs, PDF resumes, and freeform recruiter notes — then resolves identity, merges conflicts, and outputs a fully-normalized, Pydantic-validated canonical candidate record.

<br />

**🌐 Live Demo:** [**khusheeranjan01-1.onrender.com**](https://khusheeranjan01-1.onrender.com)

<br />

---

</div>

## 📖 Table of Contents

- [Why This Exists](#-why-this-exists)
- [Features at a Glance](#-features-at-a-glance)
- [System Architecture](#-system-architecture)
  - [High-Level DAG Pipeline](#high-level-dag-pipeline)
  - [Stage-by-Stage Breakdown](#stage-by-stage-breakdown)
  - [Identity Resolution Workflow](#identity-resolution-workflow)
  - [Confidence Scoring Model](#confidence-scoring-model)
- [Canonical Schema](#-canonical-schema)
- [Merge Policy & Conflict Resolution](#-merge-policy--conflict-resolution)
- [Edge Cases & Resilience](#-edge-cases--resilience)
- [Tech Stack](#-tech-stack)
- [Getting Started](#-getting-started)
  - [Install](#1-install)
  - [Run (CLI)](#2-run-cli)
  - [Run (Web UI + API)](#3-run-web-ui--api)
  - [Custom Output Config](#4-custom-output-config)
- [Sample Output](#-sample-output)
- [Test Suite](#-test-suite)
- [Design Decisions](#-design-decisions--reasoning)
- [Contact](#-contact)

---

## 💡 Why This Exists

Recruiting pipelines accumulate candidate data from **multiple, inconsistent sources** — ATS databases, recruiter spreadsheets, uploaded résumés, and raw notes. Each source uses a different format, different phone notations, different skill aliases, and different name spellings. Without a principled merge layer, the same candidate can appear as three separate records, skills like `"js"` and `"JavaScript"` are treated as different entities, and fields like `"till date"` are left un-normalized.

This system solves that problem with a **fully deterministic, reproducible pipeline** — every transformation is traceable, every conflict is audited, and every output record is schema-validated before delivery.

---

## ✨ Features at a Glance

| Category | What It Does |
|---|---|
| 🗂 **Multi-Source Ingestion** | ATS JSON, Recruiter CSV, PDF Résumés, Free-text Notes — all in one pass |
| 🧠 **Hybrid NER** | GLiNER (zero-shot) for prose, FlashText skill-trie for canonical skill lookup |
| 🔗 **Graph Identity Resolution** | NetworkX clustering on high-entropy keys (email + phone); zero false merges |
| ⚖️ **Authority Matrix Merge** | `ATS > CSV > Resume > Notes` trust hierarchy, losers retained in provenance |
| 📐 **Format Normalization** | Phones → E.164, Dates → ISO-8601, Names → Unicode NFKC + transliteration |
| 🛡 **Pydantic Schema Guards** | Projection layer validates every output record before it leaves the pipeline |
| 📋 **Full Provenance Audit** | Every field logs: `source`, `method`, `raw_value`, `confidence` |
| 🌐 **Multilingual Support** | Devanagari, Arabic, CJK, Latin — all resolve to stable merge keys |
| 💥 **Atomic Failure Model** | One bad source never kills the run — isolated per-branch error logging |
| ⚙️ **Runtime Output Config** | Reshape, rename, and filter output fields without touching pipeline code |
| 🖥 **Web UI + REST API** | Interactive frontend + FastAPI backend with PDF upload support |

---

## 🏗 System Architecture

### High-Level DAG Pipeline

```
                        ┌─────────────────────────────────────────────────┐
                        │              INPUT SOURCES                       │
                        │  ATS JSON  │  Recruiter CSV  │  PDF Résumés  │  Notes  │
                        └─────┬──────┴────────┬─────────┴───────┬───────┴────┬───┘
                               │               │                 │            │
                        ╔══════▼═══════════════▼═════════════════▼════════════▼══════╗
                        ║         STAGE 0–1 │ PRE-FLIGHT + EXTRACTION                ║
                        ║  • Coordinate-aware layout parsing (column-mixing prevention)║
                        ║  • GLiNER zero-shot NER  │  FlashText skill-trie            ║
                        ║  • Regex phone/email/date │  OCR fallback (Tesseract)        ║
                        ╚══════════════════════════╦═══════════════════════════════════╝
                                                   │  List[SourceRecord]
                        ╔══════════════════════════▼═══════════════════════════════════╗
                        ║         STAGE 2 │ NORMALIZATION                              ║
                        ║  • Phones → E.164 (libphonenumber)                           ║
                        ║  • Dates  → ISO-8601 │ "present" synonyms                   ║
                        ║  • Skills → canonical alias (RapidFuzz + alias table)        ║
                        ║  • Names  → Unicode NFKC + transliteration                  ║
                        ╚══════════════════════════╦═══════════════════════════════════╝
                                                   │
                        ╔══════════════════════════▼═══════════════════════════════════╗
                        ║         STAGE 3 │ IDENTITY RESOLUTION (NetworkX)             ║
                        ║  • Graph nodes = SourceRecords                               ║
                        ║  • Edges = shared high-entropy keys (email OR phone)         ║
                        ║  • Connected components = candidate clusters                 ║
                        ║  • Fuzzy name matching: corroborating signal only, never     ║
                        ║    edge-trigger (prevents false merges)                      ║
                        ╚══════════════════════════╦═══════════════════════════════════╝
                                                   │  List[Cluster]
                        ╔══════════════════════════▼═══════════════════════════════════╗
                        ║         STAGE 4 │ REDUCTION / MERGE                          ║
                        ║  • Authority matrix: ATS > CSV > Resume > Notes              ║
                        ║  • Losers retained in provenance history, never discarded    ║
                        ║  • Confidence: Σ(source_trust × method_fidelity × consensus) ║
                        ╚══════════════════════════╦═══════════════════════════════════╝
                                                   │
                        ╔══════════════════════════▼═══════════════════════════════════╗
                        ║         STAGE 5 │ CANONICAL STORE                            ║
                        ║  • Immutable per-run snapshot written BEFORE projection      ║
                        ║  • Snapshot failure is non-fatal — logged, never crashes     ║
                        ╚══════════════════════════╦═══════════════════════════════════╝
                                                   │
                        ╔══════════════════════════▼═══════════════════════════════════╗
                        ║         STAGE 6 │ RUNTIME PROJECTION GATE                   ║
                        ║  • Config Ω: field selection, path remapping, on_missing     ║
                        ║  • Pydantic schema guardrail validates every output record   ║
                        ║  • Output: P = C × Ω (canonical record × config)            ║
                        ╚══════════════════════════════════════════════════════════════╝
                                                   │
                                             JSON Output
```

### Stage-by-Stage Breakdown

| Stage | Name | Key Technology | Purpose |
|---|---|---|---|
| **0–1** | Pre-flight + Extraction | GLiNER, FlashText, PyMuPDF, Tesseract | Detect source type, parse layout, extract raw fields |
| **2** | Normalization | libphonenumber, python-dateutil, RapidFuzz | Deterministic canonical formats |
| **3** | Identity Resolution | NetworkX graph clustering | Deduplicate candidates across sources |
| **4** | Reduction / Merge | Authority matrix, provenance tracking | Conflict resolution with full audit trail |
| **5** | Canonical Store | Filesystem snapshot | Immutable per-run record, pre-projection |
| **6** | Projection Gate | Pydantic v2 | Runtime output reshaping with schema validation |

### Identity Resolution Workflow

The identity resolver builds a **weighted graph** where each `SourceRecord` is a node, and edges are drawn when two records share a high-entropy key:

```
Node A: { email: "p@x.com", name: "Priya Sharma" }   ←──── shared email ────→  Node B: { email: "p@x.com", name: "प्रिया शर्मा" }
                                                                                        │
                                                                              (Devanagari transliterates
                                                                               to "priya sharma" → same
                                                                               token-sorted key → MERGED)

Node C: { phone: "+15559991234", name: "Jay Ramirez" }  ←── SAME phone ───→  Node D: { phone: "+15559991234", name: "Susan Rogers" }
                                                                                        │
                                                                              (Different names → phone
                                                                               collision → NOT merged.
                                                                               Two separate clusters.)
```

**Key design guarantee:** Name fuzzy matching is a *corroborating signal*, never an *edge-trigger*. Only strict high-entropy key intersections (email or phone) create merge edges. This ensures **zero false positives** at the cost of potentially missing same-person records with no shared contact info — an intentional trade-off for deterministic reproducibility.

### Confidence Scoring Model

Every output record carries an **overall confidence score** aggregated from per-field provenance:

$$C_a = \sum (w_i \cdot m_i \cdot \phi_i)$$

| Symbol | Meaning |
|---|---|
| $w_i$ | Source trust weight (`ats_json=0.95`, `recruiter_csv=0.85`, `resume=0.75`, `notes=0.65`) |
| $m_i$ | Method fidelity (`direct_field=1.0`, `regex=0.6`, `ner_gliner=0.75`, `ocr=0.5`) |
| $\phi_i$ | Cross-source consensus bonus (field confirmed by multiple sources → higher score) |

---

## 📦 Canonical Schema

Each candidate in the output JSON array follows this structure:

```json
{
  "candidate_id":  "a4de8c49-b04c-45f1-bff4-5c53d6418178",
  "full_name":     "Priya Sharma",
  "emails":        ["priya@example.com"],
  "phones":        ["+14155552671"],
  "location":      { "city": "San Francisco", "region": "CA", "country": "US" },
  "links": {
    "linkedin":  "https://linkedin.com/in/priyasharma",
    "github":    null,
    "portfolio": null,
    "other":     []
  },
  "skills": [
    { "name": "Python",     "confidence": 0.95, "sources": ["ats_json", "resume"] },
    { "name": "Kubernetes", "confidence": 0.80, "sources": ["resume"] }
  ],
  "headline":         "Senior Backend Engineer",
  "years_experience": 6.0,
  "experience": [
    { "company": "Stripe", "title": "Staff Engineer", "start": "2021-03", "end": "present", "summary": null }
  ],
  "education": [
    { "institution": "IIT Delhi", "degree": "B.Tech", "field": "Computer Science", "end_year": 2018 }
  ],
  "provenance": [
    { "field": "full_name",        "source": "ats_json",       "method": "direct_field", "raw_value": "Priya Sharma",      "confidence": 0.95 },
    { "field": "phones[0]",        "source": "ats_json",       "method": "regex",        "raw_value": "(415)555-2671",     "confidence": 0.57 },
    { "field": "skills[Python]",   "source": "resume",         "method": "skill_trie",   "raw_value": "python",           "confidence": 0.90 },
    { "field": "skills[Python]",   "source": "ats_json",       "method": "direct_field", "raw_value": "Python",           "confidence": 0.95 }
  ],
  "overall_confidence":    0.891,
  "source_records_merged": ["ats_json", "recruiter_csv", "resume"],
  "created_at":            "2026-06-30T21:27:23.954744"
}
```

**Key field reference:**

| Field | Format | Notes |
|---|---|---|
| `candidate_id` | UUID v4 | Stable deterministic hash for the merged candidate |
| `full_name` | Unicode NFKC string | Authority-resolved, suffix-stripped |
| `phones` | E.164 (`+1XXXXXXXXXX`) | Normalized via `libphonenumber` |
| `emails` | Lowercased, RFC-5321 | Deduplicated across sources |
| `location.country` | ISO-3166 alpha-2 | e.g. `"US"`, `"IN"`, `"GB"` |
| `experience[].start/end` | `YYYY-MM` or `"present"` | `"till date"`, `"current"` → `"present"` |
| `skills[].name` | Canonical alias | `"js"` → `"JavaScript"`, `"k8s"` → `"Kubernetes"` |
| `provenance` | Array of trace entries | Full audit trail — every value is traceable |
| `overall_confidence` | `0.0 – 1.0` | Weighted aggregate across all provenance entries |
| `source_records_merged` | Array of source types | Which sources contributed to this record |

---

## ⚖️ Merge Policy & Conflict Resolution

When two source records claim different values for the same field (e.g. ATS says name is `"Michael R. Jordan"`, CSV says `"Mike Jordan"`), the pipeline uses a **fixed authority matrix**:

```
ATS JSON  >  Recruiter CSV  >  Resume PDF  >  Recruiter Notes
  (0.95)         (0.85)           (0.75)           (0.65)
```

The winning value is stored in the canonical record. The losing value is **never discarded** — it's retained in the `provenance` history buffer, fully auditable. This satisfies the equation:

$$V_{final} = \arg\max_{v \in V} \sum_{s \in S} T_s \cdot \mathbb{1}(v, s)$$

Where $T_s$ is the source trust weight and $\mathbb{1}(v, s)$ indicates whether source $s$ produced value $v$.

**Match key rules:**
- ✅ `email` → exact match → edge in identity graph
- ✅ `phone` (E.164 normalized) → exact match → edge in identity graph
- ⚠️ `name` → token-sorted fuzzy key → **corroborating signal only, never an edge-trigger**
- ❌ Fuzzy matching on contact info → explicitly disabled to prevent false merges

---

## 🛡 Edge Cases & Resilience

| Scenario | How It's Handled |
|---|---|
| **Non-linear PDF layouts** (two-column résumés) | Coordinate-aware spatial segmentation — field relationships are preserved, columns don't bleed into each other |
| **Phone number collisions** (two people, same phone) | Detected via mismatched names → NOT merged; logged as separate clusters |
| **Multilingual name variants** (Devanagari ↔ Latin, Arabic ↔ Latin) | Unicode NFKC + transliteration yields stable match keys while preserving original display strings |
| **Skill aliases** (`"js"`, `"JavaScript"`, `"javascript"`) | All map to canonical `"JavaScript"` via alias trie + RapidFuzz; deduplicated in output |
| **Chronologically inverted dates** (`"March 2022"` as start, `"January 2018"` as end) | Auto-detected and swapped; logged in provenance |
| **"Present" synonyms** (`"till date"`, `"current"`, `"ongoing"`) | All normalized to `"present"` |
| **Malformed source files** (truncated JSON, empty CSV) | Independent failure logging — only the failed branch terminates, the rest of the DAG continues |
| **Missing optional fields** | Always `null` or `[]` — never invented, never guessed |
| **Unreadable PDF text layers** | OCR (Tesseract) break-glass fallback, lower confidence score logged |
| **Suffix / honorific variants** (`"Jr."`, `"Sr."`, `"II"`) | Stripped before name key computation |
| **First/last name swaps** | Token-sorted key normalization ensures `"Sharma Priya"` and `"Priya Sharma"` resolve identically |

**Deliberately left out** (under time constraints, documented honestly):
- Probabilistic/fuzzy identity matching — excluded to guarantee 100% deterministic reproducibility
- Full-scale OCR as primary path — limited to break-glass fallback for unreadable text layers only
- Horizontal distributed scaling — optimized for high-performance single-machine batch processing

---

## 🛠 Tech Stack

| Layer | Technology | Why |
|---|---|---|
| **Core Runtime** | Python 3.10+ | Type annotations, `match` statements, pathlib |
| **Schema & Validation** | Pydantic v2 | Strict schema guards at every stage boundary |
| **Identity Graph** | NetworkX | Flexible graph clustering for identity resolution |
| **PDF Parsing** | PyMuPDF (fitz) | Coordinate-aware layout extraction |
| **OCR Fallback** | Tesseract + pytesseract | Break-glass for image-only PDFs |
| **NER (prose)** | GLiNER | Zero-shot entity extraction — no training data needed |
| **NER (secondary)** | spaCy | Secondary signal for person/org/location |
| **Skill Extraction** | FlashText | O(n) trie-based canonical skill lookup |
| **Skill Fuzzy Match** | RapidFuzz | Misspelling tolerance (e.g. `"pytohn"` → `"Python"`) |
| **Phone Normalization** | libphonenumber | E.164 normalization globally |
| **Date Normalization** | python-dateutil | ISO-8601 with inversion detection |
| **Transliteration** | Unidecode | Multilingual name key stability |
| **Lang Detection** | langdetect | Seeded for deterministic output |
| **Web API** | FastAPI + Uvicorn | Async REST API with PDF upload |
| **Report Generation** | Reportlab | PDF report generation |

---

## 🚀 Getting Started

### 1. Install

```bash
git clone https://github.com/khusheeranjan01/eightfold-transformer
cd eightfold-transformer
pip install -r requirements.txt
```

> **Note:** `gliner` and `spacy` are optional — the pipeline degrades gracefully if they are absent. All other features remain fully functional.

### 2. Run (CLI)

**Default output — full canonical schema:**
```bash
python cli.py --input-dir sample_inputs --output output/default.json
```

**With a custom projection config:**
```bash
python cli.py \
  --input-dir sample_inputs \
  --config custom_config.json \
  --output output/custom.json
```

**All CLI flags:**

| Flag | Required | Default | Description |
|---|---|---|---|
| `--input-dir` | ✅ | — | Directory containing `recruiter.csv`, `ats.json`, `notes/`, `resumes/` |
| `--output` | ✅ | — | Path to write the output JSON array |
| `--config` | ➖ | Full schema | Path to a runtime projection config JSON |
| `--notes-dir` | ➖ | `<input-dir>/notes` | Override notes `.txt` directory |
| `--snapshot-dir` | ➖ | `output/` | Where to write the immutable canonical snapshot |

**Sample stdout after a run:**
```
Run ID:              fb60e0c8c11b
Sources processed:   ['recruiter.csv', 'ats.json', 'notes/ (12/12 files)']
Sources skipped:     ['resumes/ (directory missing)']
Candidates produced: 500
Canonical snapshot:  output/canonical_fb60e0c8c11b.json
Output written to:   output/default.json
```

### 3. Run (Web UI + API)

Start the FastAPI backend:
```bash
uvicorn server:app --reload --port 8000
```

Then open `frontend/index.html` in your browser, or navigate to:
```
http://localhost:8000
```

The Web UI supports:
- Uploading source files (CSV, JSON, PDF, TXT)
- Running the pipeline and previewing results in real-time
- Downloading the canonical output JSON
- Viewing per-candidate provenance traces

Or call the API directly:
```bash
curl -X POST http://localhost:8000/run \
  -F "ats_json=@sample_inputs/ats.json" \
  -F "recruiter_csv=@sample_inputs/recruiter.csv"
```

### 4. Custom Output Config

The projection layer separates the canonical record from the output format. A config JSON (`Ω`) defines exactly what fields appear in the output, how they're named, and what happens when a field is missing:

```json
{
  "fields": [
    { "source_path": "candidate_id",   "output_key": "id" },
    { "source_path": "full_name",      "output_key": "name" },
    { "source_path": "emails[0]",      "output_key": "primary_email" },
    { "source_path": "phones[0]",      "output_key": "primary_phone" },
    { "source_path": "overall_confidence", "output_key": "score" }
  ],
  "on_missing": "null"
}
```

`on_missing` options: `"null"` (include field as `null`), `"omit"` (skip field entirely), `"error"` (fail validation).

---

## 📊 Sample Output

Two records from `output/default.json` after running against the provided `sample_inputs/`:

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
      { "field": "full_name",            "source": "ats_json", "method": "direct_field", "raw_value": "Jay Ramirez II",      "confidence": 0.95 },
      { "field": "emails[...]",          "source": "ats_json", "method": "direct_field", "raw_value": "susanrogers@example.org", "confidence": 0.95 },
      { "field": "phones[+16157594078]", "source": "ats_json", "method": "regex",        "raw_value": "(615)759-4078x1618", "confidence": 0.57 }
    ],
    "overall_confidence": 0.8233,
    "source_records_merged": ["recruiter_csv", "ats_json"],
    "created_at": "2026-06-30T21:27:23.954744"
  }
]
```

---

## 🧪 Test Suite

Run the full test suite:

```bash
pytest tests/ -v
```

### Coverage

| Test File | What It Covers |
|---|---|
| `test_date_engine.py` | `normalize_date` (ISO-8601, "present" synonyms, year-only, chronological inversion swap, garbage → `None`), `normalize_date_pair`, `parse_years_experience` |
| `test_skill_engine.py` | `canonicalize_skill` (exact aliases: `js→JavaScript`, `k8s→Kubernetes`, `golang→Go`; fuzzy misspellings; unknown → `None`; deduplication; determinism) |
| `test_layout_parser.py` | `tag_lines` (heading / bullet / body / blank detection, indent levels, section context propagation), `lines_in_section`, two-column PDF layout detection |
| `test_multilingual_identity.py` | `resolve_identities` (Devanagari + Latin → merge via shared email; Arabic + Latin → merge via shared phone; CJK threshold; phone collision → no false merge; Jr./Sr. suffix stripping; first/last swap → same token-sorted key) |
| `test_name_normalizer_multilingual.py` | Name key normalization across scripts, suffix stripping, transliteration stability |
| `test_indent_edge_cases.py` | Mixed tabs/spaces, deeply nested bullets, single-line documents |
| `test_resume_extractor.py` | Resume PDF extraction smoke tests |

### Selected assertions

```python
# ── Date normalization ──────────────────────────────────────────────────────
assert normalize_date("January 2018")  == "2018-01"
assert normalize_date("present")       == "present"
assert normalize_date("till date")     == "present"
assert normalize_date("garbage")       is None
start, end = normalize_date_pair("March 2022", "January 2018")
assert start == "2018-01"   # chronological inversion auto-corrected

# ── Skill canonicalization ───────────────────────────────────────────────────
assert canonicalize_skill("js")       == "JavaScript"
assert canonicalize_skill("k8s")      == "Kubernetes"
assert canonicalize_skill("golang")   == "Go"
assert canonicalize_skill("sklearn")  == "scikit-learn"
assert canonicalize_skill("bash")     == "Shell"
assert canonicalize_skill("garbage")  is None
assert canonicalize_skills(["js", "javascript", "JavaScript"]).count("JavaScript") == 1  # dedup

# ── Layout parser ────────────────────────────────────────────────────────────
tagged = tag_lines("Skills:\n  Python\n  Docker\nEducation:\n  MIT")
assert tagged[0].tag     == LineTag.HEADING
assert tagged[1].tag     == LineTag.BULLET   # indented → bullet
assert tagged[1].section == "Skills"

# ── Identity resolution ──────────────────────────────────────────────────────
clusters = resolve_identities([
    ats_record("Priya Sharma",  email="p@x.com"),
    notes_record("प्रिया शर्मा", email="p@x.com"),
])
assert len(clusters) == 1   # Devanagari transliterates → same key → MERGED ✅

clusters = resolve_identities([
    ats_record("Jay Ramirez",  phone="+15559991234"),
    ats_record("Susan Rogers", phone="+15559991234"),
])
assert len(clusters) == 2   # same phone, different names → NOT merged ✅
```

---

## 🧭 Design Decisions & Reasoning

| Decision | Rationale |
|---|---|
| **DAG over linear pipeline** | Prevents field-scrambling from naive sequential parsers; enables per-branch isolated failures |
| **Strict high-entropy keys only for identity** | Guarantees zero false merges — probabilistic/fuzzy identity matching explicitly excluded for reproducibility |
| **Authority matrix for conflict resolution** | Losers are retained, never discarded — full audit trail preserved at all times |
| **Pydantic v2 at projection boundary** | Catches schema drift from upstream changes before the record leaves the system |
| **Snapshot written before projection** | The canonical record is always preserved, independent of any runtime config |
| **Stateless per-stage design** | Each stage takes a list in, emits a list out — no shared mutable state, easy to unit test |
| **Graceful degradation for NER** | GLiNER and spaCy are optional — the pipeline still runs on FlashText + regex alone |
| **Atomic failure model** | A malformed CSV row or truncated PDF only fails that branch — the rest of the DAG continues |

---

## 📬 Contact

**Khushee Ranjan**
- 📧 Email: [khusheeranjan@gmail.com](mailto:khusheeranjan@gmail.com)
- 🌐 Live Demo: [khusheeranjan01-1.onrender.com](https://khusheeranjan01-1.onrender.com)
- 💼 Assignment: Eightfold Engineering Intern — Multi-Source Candidate Data Transformer

---

<div align="center">

*Built with determinism, audited at every step.*

**⭐ Star this repo if you found it useful!**

</div>
