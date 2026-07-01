"""
Identity resolution: group SourceRecords that refer to the same candidate.

UPDATED based on sample data analysis: ats.json contains ~9% duplicate
emails/phones across genuinely different people (Faker-generated contact
info collides by chance across a 1000-record pool). manifest.json confirms
this is a deliberate test case ("duplicate_identity": 198 entries).

This means email/phone matches can NO LONGER be treated as unconditionally
strong signals â€” they must be corroborated by name similarity. If two
records share an email/phone but have CLEARLY DIFFERENT names, that's
evidence of a coincidental collision, not the same person, and merging them
would be exactly the "wrong-but-confident" failure the assignment warns
against. Conversely, manifest also tags 97 "name_variant" cases (nicknames,
middle names, Jr/Sr) which must NOT be rejected as conflicts â€” so name
comparison uses a fuzzy similarity threshold, not exact match.

Policy after this fix:
  - email/phone match + names absent on one/both sides -> merge (can't check, trust the strong key)
  - email/phone match + names present + similar enough  -> merge (corroborated)
  - email/phone match + names present + clearly different -> DO NOT merge
    (flagged as a collision, kept as separate clusters)
  - name-only match (no shared email/phone) -> merge only if no conflicting
    email/phone evidence (unchanged from before)
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Dict, List

import networkx as nx

from src.models import SourceRecord
from src.normalize.name_normalizer import normalize_name_key, script_family, ScriptFamily
from src.normalize.phone_engine import normalize_phone

# ---------------------------------------------------------------------------
# Script-aware name conflict thresholds
# ---------------------------------------------------------------------------
# Below this similarity ratio, two name_keys are considered "clearly different"
# people rather than a variant (nickname, middle name, transliteration) of
# the same person.
#
# The threshold is LOWER for cross-script pairs because unidecode / Hepburn /
# Pinyin romanisation produces keys that are phonetically close but string-
# distance-different from the native Latin form:
#
#   Latin ↔ Latin      : 0.50  (tight — both sides are already ASCII)
#   Latin ↔ Indic/Arabic: 0.45  (unidecode is reliable, small divergence OK)
#   Latin ↔ CJK         : 0.35  (romanisation gaps are larger; be generous)
#   Everything else     : 0.50  (conservative default)
#
# A pair BELOW its threshold is flagged as a likely collision and NOT merged.
# A pair ABOVE its threshold is allowed to merge.
_THRESHOLD_LATIN_LATIN        = 0.50
_THRESHOLD_LATIN_INDIC_ARABIC = 0.45
_THRESHOLD_LATIN_CJK          = 0.35
_THRESHOLD_DEFAULT            = 0.50


def _conflict_threshold(family_a: ScriptFamily, family_b: ScriptFamily) -> float:
    """
    Return the similarity threshold for a pair of name keys whose source
    strings belong to script families `family_a` and `family_b`.
    Lower threshold = more lenient (two names can differ more and still merge).
    """
    pair = frozenset([family_a, family_b])

    cjk_pair          = frozenset([ScriptFamily.CJK, ScriptFamily.LATIN])
    indic_arabic_pair = frozenset([ScriptFamily.INDIC_ARABIC, ScriptFamily.LATIN])
    both_latin        = frozenset([ScriptFamily.LATIN])

    if pair == both_latin:
        return _THRESHOLD_LATIN_LATIN
    if pair == indic_arabic_pair or pair == frozenset([ScriptFamily.INDIC_ARABIC]):
        return _THRESHOLD_LATIN_INDIC_ARABIC
    if pair == cjk_pair or pair == frozenset([ScriptFamily.CJK]):
        return _THRESHOLD_LATIN_CJK
    # Mixed CJK + Indic, or UNKNOWN in the mix — use default (conservative)
    return _THRESHOLD_DEFAULT


@dataclass
class CandidateCluster:
    candidate_id: str
    records: List[SourceRecord] = field(default_factory=list)


def _record_keys(record: SourceRecord) -> dict[str, list]:
    """
    Extract identity keys from a SourceRecord.

    Returns a dict with three keys:
      "email"    : list of normalised email strings
      "phone"    : list of E.164 phone strings
      "name"     : list of (name_key, raw_name) tuples
                   raw_name is kept for script_family detection so that the
                   conflict threshold can be calibrated to the source script.
    """
    keys: dict[str, list] = {"email": [], "phone": [], "name": []}

    for raw_email in record.emails:
        if raw_email.value:
            keys["email"].append(raw_email.value.strip().lower())

    for raw_phone in record.phones:
        if raw_phone.value:
            result = normalize_phone(raw_phone.value)
            if result.e164:
                keys["phone"].append(result.e164)

    if record.full_name and record.full_name.value:
        raw_name = record.full_name.value
        name_key = normalize_name_key(raw_name)
        if name_key:
            keys["name"].append((name_key, raw_name))  # (key, raw) tuple

    return keys


def _name_similarity(name_key_a: str, name_key_b: str) -> float:
    """
    Token-sorted name_keys (already produced by normalize_name_key) compared
    via simple sequence-ratio similarity. Deterministic, no extra dependency.
    1.0 = identical, 0.0 = nothing in common.
    """
    return SequenceMatcher(None, name_key_a, name_key_b).ratio()


def _names_conflict(keys_a: dict, keys_b: dict) -> bool:
    """
    True only if BOTH records have a name AND that name is clearly different
    (below the script-aware conflict threshold). If either side lacks a name,
    we can't evaluate a conflict, so we don't block the merge on this basis.

    Uses script_family() on the raw name strings to pick a per-pair threshold:
      - Latin ↔ Latin       : 0.50 (tight)
      - Latin ↔ Indic/Arabic : 0.45 (unidecode is reliable)
      - Latin ↔ CJK          : 0.35 (romanisation diverges more)
    This means a Devanagari name and its English transliteration will NOT be
    flagged as a conflict even when the SequenceMatcher ratio sits at ~0.42.
    """
    names_a: list = keys_a["name"]  # list of (name_key, raw_name) tuples
    names_b: list = keys_b["name"]
    if not names_a or not names_b:
        return False

    # Find the best similarity across all pairings, using a per-pair threshold.
    # We report conflict only if ALL pairs fall below their respective threshold.
    for key_a, raw_a in names_a:
        for key_b, raw_b in names_b:
            sim = _name_similarity(key_a, key_b)
            fam_a = script_family(raw_a)
            fam_b = script_family(raw_b)
            threshold = _conflict_threshold(fam_a, fam_b)
            if sim >= threshold:
                # At least one pairing is similar enough — not a conflict.
                return False

    # Every pairing fell below its script-aware threshold — this is a conflict.
    return True


def _conflicts_on_strong_keys(keys_a: dict, keys_b: dict) -> bool:
    """True if both records have email/phone evidence that actively disagrees."""
    emails_a, emails_b = set(keys_a["email"]), set(keys_b["email"])
    phones_a, phones_b = set(keys_a["phone"]), set(keys_b["phone"])

    email_conflict = bool(emails_a and emails_b and emails_a.isdisjoint(emails_b))
    phone_conflict = bool(phones_a and phones_b and phones_a.isdisjoint(phones_b))

    return email_conflict or phone_conflict


def resolve_identities(records: List[SourceRecord]) -> List[CandidateCluster]:
    """
    Group records into candidate clusters via connected components, with
    BOTH directions of conflict-gating applied:
      - strong-key (email/phone) edges are rejected if names clearly conflict
      - weak-key (name-only) edges are rejected if email/phone clearly conflict
    """
    graph = nx.Graph()
    for idx, _ in enumerate(records):
        graph.add_node(idx)

    email_index: Dict[str, List[int]] = {}
    phone_index: Dict[str, List[int]] = {}
    name_index: Dict[str, List[int]] = {}

    per_record_keys = [_record_keys(r) for r in records]

    for idx, keys in enumerate(per_record_keys):
        for email in keys["email"]:
            email_index.setdefault(email, []).append(idx)
        for phone in keys["phone"]:
            phone_index.setdefault(phone, []).append(idx)
        for name_key, _raw in keys["name"]:          # unpack (key, raw) tuple
            name_index.setdefault(name_key, []).append(idx)

    # Strong signals (email, phone): now gated against conflicting names,
    # to avoid merging unrelated people who happen to share a colliding
    # contact value (confirmed present in this dataset â€” see module docstring).
    for index_map, reason in ((email_index, "email"), (phone_index, "phone")):
        for matching_indices in index_map.values():
            for i in range(len(matching_indices)):
                for j in range(i + 1, len(matching_indices)):
                    a, b = matching_indices[i], matching_indices[j]
                    if _names_conflict(per_record_keys[a], per_record_keys[b]):
                        continue  # likely a Faker-pool collision, not the same person
                    graph.add_edge(a, b, reason=reason)

    # Weak signal (name only): unchanged â€” gated against conflicting strong keys.
    for matching_indices in name_index.values():
        for i in range(len(matching_indices)):
            for j in range(i + 1, len(matching_indices)):
                a, b = matching_indices[i], matching_indices[j]
                if _conflicts_on_strong_keys(per_record_keys[a], per_record_keys[b]):
                    continue
                graph.add_edge(a, b, reason="name_only")

    clusters: List[CandidateCluster] = []
    for component in nx.connected_components(graph):
        cluster_records = [records[i] for i in sorted(component)]
        clusters.append(
            CandidateCluster(candidate_id=str(uuid.uuid4()), records=cluster_records)
        )

    return clusters