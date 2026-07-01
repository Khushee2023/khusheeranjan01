"""
FlashText Skill Trie — Layer 1 of the pipeline.

FlashText implements the Aho-Corasick algorithm for multi-pattern string
matching: given a set of keywords, it finds ALL occurrences in O(n) time
(where n = len(text)), regardless of the number of keywords. This makes it
dramatically faster than a regex loop at scale (thousands of candidates ×
hundreds of skill terms).

Key features here:
  - Case-insensitive matching (normalized internally)
  - Alias resolution: "js" → "JavaScript", "k8s" → "Kubernetes", etc.
  - Returns CANONICAL names, not the raw text the user wrote
  - Module-level singleton: trie is built once at import time, reused per run
  - Graceful degradation: if flashtext is not installed, falls back to a
    simple set-based keyword scan with the same canonical output

The alias dictionary here is the authoritative canonical skill name list for
this pipeline. Skills from all sources (ATS, CSV, notes, resume) are
canonicalized through this same dict, so "react.js", "React", "ReactJS"
all merge into the single canonical name "React".
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Canonical skill name → list of aliases (all lowercase for matching)
# ---------------------------------------------------------------------------
# Format: "Canonical Name": ["alias1", "alias2", ...]
# The canonical name IS included implicitly (flashtext adds it as its own key).
# Aliases are what users might write; canonical is what we store.

_SKILL_ALIASES: Dict[str, List[str]] = {
    # Languages
    "Python":           ["python", "py"],
    "Java":             ["java"],
    "JavaScript":       ["javascript", "js", "ecmascript", "es6", "es2015", "es2020"],
    "TypeScript":       ["typescript", "ts"],
    "Go":               ["go", "golang"],
    "Rust":             ["rust"],
    "C++":              ["c++", "cpp", "c plus plus"],
    "C#":               ["c#", "csharp", "c sharp"],
    "C":                ["c language"],
    "Ruby":             ["ruby"],
    "PHP":              ["php"],
    "Swift":            ["swift"],
    "Kotlin":           ["kotlin"],
    "Scala":            ["scala"],
    "R":                ["r language", "r programming"],
    "MATLAB":           ["matlab"],
    "Perl":             ["perl"],
    "Shell":            ["bash", "shell", "sh", "zsh", "fish shell"],
    "Dart":             ["dart"],
    # Frontend
    "React":            ["react", "reactjs", "react.js"],
    "Vue.js":           ["vue", "vuejs", "vue.js"],
    "Angular":          ["angular", "angularjs", "angular.js"],
    "Svelte":           ["svelte"],
    "HTML":             ["html", "html5"],
    "CSS":              ["css", "css3"],
    "Sass":             ["sass", "scss"],
    "Next.js":          ["next.js", "nextjs", "next js"],
    "Nuxt.js":          ["nuxt.js", "nuxtjs"],
    "Redux":            ["redux"],
    "jQuery":           ["jquery"],
    # Backend / Frameworks
    "Node.js":          ["node", "node.js", "nodejs"],
    "Django":           ["django"],
    "Flask":            ["flask"],
    "FastAPI":          ["fastapi", "fast api"],
    "Spring":           ["spring", "spring boot", "springboot"],
    "Express":          ["express", "expressjs", "express.js"],
    "Rails":            ["rails", "ruby on rails"],
    "Laravel":          ["laravel"],
    "ASP.NET":          ["asp.net", "asp net", "aspnet"],
    # Databases
    "PostgreSQL":       ["postgresql", "postgres", "pg"],
    "MySQL":            ["mysql"],
    "SQLite":           ["sqlite"],
    "MongoDB":          ["mongodb", "mongo"],
    "Redis":            ["redis"],
    "Cassandra":        ["cassandra"],
    "Elasticsearch":    ["elasticsearch", "elastic search", "es"],
    "DynamoDB":         ["dynamodb", "dynamo db"],
    "Neo4j":            ["neo4j"],
    "Oracle":           ["oracle", "oracle db", "oracle database"],
    "SQL":              ["sql", "structured query language"],
    # Cloud
    "AWS":              ["aws", "amazon web services", "amazon aws"],
    "GCP":              ["gcp", "google cloud", "google cloud platform"],
    "Azure":            ["azure", "microsoft azure"],
    "Heroku":           ["heroku"],
    "Vercel":           ["vercel"],
    "Netlify":          ["netlify"],
    # DevOps / Infrastructure
    "Docker":           ["docker"],
    "Kubernetes":       ["kubernetes", "k8s"],
    "Terraform":        ["terraform"],
    "Ansible":          ["ansible"],
    "Jenkins":          ["jenkins"],
    "GitHub Actions":   ["github actions", "github ci"],
    "GitLab CI":        ["gitlab ci", "gitlab ci/cd"],
    "CI/CD":            ["ci/cd", "ci cd", "continuous integration", "continuous delivery"],
    "Linux":            ["linux", "unix"],
    "Nginx":            ["nginx"],
    "Apache":           ["apache"],
    # ML / Data
    "Machine Learning": ["machine learning", "ml"],
    "Deep Learning":    ["deep learning", "dl"],
    "NLP":              ["nlp", "natural language processing"],
    "Computer Vision":  ["computer vision", "cv", "image recognition"],
    "PyTorch":          ["pytorch", "torch"],
    "TensorFlow":       ["tensorflow", "tf"],
    "Keras":            ["keras"],
    "scikit-learn":     ["scikit-learn", "sklearn", "scikit learn"],
    "Pandas":           ["pandas"],
    "NumPy":            ["numpy"],
    "Matplotlib":       ["matplotlib"],
    "Spark":            ["spark", "apache spark", "pyspark"],
    "Hadoop":           ["hadoop", "apache hadoop"],
    "Kafka":            ["kafka", "apache kafka"],
    "Airflow":          ["airflow", "apache airflow"],
    "dbt":              ["dbt", "data build tool"],
    "Tableau":          ["tableau"],
    "Power BI":         ["power bi", "powerbi"],
    # APIs / Protocols
    "REST API":         ["rest api", "rest", "restful", "restful api"],
    "GraphQL":          ["graphql", "graph ql"],
    "gRPC":             ["grpc", "g rpc"],
    "WebSockets":       ["websockets", "websocket"],
    # Testing
    "Jest":             ["jest"],
    "Pytest":           ["pytest"],
    "JUnit":            ["junit"],
    "Cypress":          ["cypress"],
    "Selenium":         ["selenium"],
    # Version Control
    "Git":              ["git"],
    "GitHub":           ["github"],
    "GitLab":           ["gitlab"],
    "Bitbucket":        ["bitbucket"],
    # Architecture / Patterns
    "Microservices":    ["microservices", "microservice"],
    "Event-Driven":     ["event-driven", "event driven"],
    "Serverless":       ["serverless"],
    "Agile":            ["agile", "scrum", "kanban"],
}

# ---------------------------------------------------------------------------
# Build the FlashText processor (module-level singleton)
# ---------------------------------------------------------------------------

_processor = None
_flashtext_ok = False


def _build_processor():
    """Build the FlashText KeywordProcessor from _SKILL_ALIASES. Called once."""
    global _processor, _flashtext_ok
    try:
        from flashtext import KeywordProcessor  # type: ignore
        kp = KeywordProcessor(case_sensitive=False)
        for canonical, aliases in _SKILL_ALIASES.items():
            # Register canonical name → canonical name (self-match)
            kp.add_keyword(canonical, canonical)
            for alias in aliases:
                kp.add_keyword(alias, canonical)
        _processor = kp
        _flashtext_ok = True
        logger.debug(f"[flashtext_skills] Trie built with {len(_SKILL_ALIASES)} canonical skills.")
    except ImportError:
        logger.warning(
            "[flashtext_skills] flashtext not installed — using fallback keyword scan. "
            "Install with: pip install flashtext"
        )
        _flashtext_ok = False


_build_processor()


# ---------------------------------------------------------------------------
# Fallback: simple set-based scan when FlashText is absent
# ---------------------------------------------------------------------------

_ALIAS_REVERSE: Dict[str, str] = {}
for _canonical, _aliases in _SKILL_ALIASES.items():
    _ALIAS_REVERSE[_canonical.lower()] = _canonical
    for _a in _aliases:
        _ALIAS_REVERSE[_a.lower()] = _canonical


def _fallback_extract(text: str) -> List[str]:
    """Slow O(n·k) fallback scan using the reverse alias dict."""
    import re
    lowered = text.lower()
    found = []
    seen = set()
    for alias, canonical in _ALIAS_REVERSE.items():
        pattern = r"(?<!\w)" + re.escape(alias) + r"(?!\w)"
        if re.search(pattern, lowered) and canonical not in seen:
            found.append(canonical)
            seen.add(canonical)
    return found


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_skills(text: str) -> List[str]:
    """
    Find all skill mentions in `text` and return their CANONICAL names.

    Uses FlashText trie if available (O(n)), fallback scan otherwise.
    Deduplicates: each canonical name appears at most once.
    Order: document order (FlashText) or alphabetical (fallback).

    Returns [] for empty/None text. Never raises.
    """
    if not text or not text.strip():
        return []

    try:
        if _flashtext_ok and _processor is not None:
            raw_matches = _processor.extract_keywords(text)
            # Dedupe while preserving first-occurrence order
            seen: set = set()
            result = []
            for canonical in raw_matches:
                if canonical not in seen:
                    seen.add(canonical)
                    result.append(canonical)
            return result
        else:
            return _fallback_extract(text)
    except Exception as exc:
        logger.debug(f"[flashtext_skills] extraction error: {exc}")
        return []


def canonical_name(raw_skill: str) -> Optional[str]:
    """
    Return the canonical name for a single raw skill string.
    Uses the reverse alias dict (exact, case-insensitive match only).
    Returns None if the skill is not recognized.

    For fuzzy matching, see skill_engine.canonicalize_skill().
    """
    if not raw_skill:
        return None
    return _ALIAS_REVERSE.get(raw_skill.strip().lower())
