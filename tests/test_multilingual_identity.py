"""
Tests for multilingual identity resolution.

Covers:
  1. Devanagari name + Latin same name → merged into one cluster
  2. Arabic name + Latin same name → merged into one cluster
  3. CJK name + Latin phonetic form → NOT falsely split (threshold is lenient)
  4. Two different people sharing a phone → NOT merged when names clearly differ
  5. Name with suffix variants (Jr./Sr.) → treated as same person
  6. First/last name swap across sources → merged (name_key is token-sorted)
"""

from __future__ import annotations

import pytest

from src.identity.graph_linkage import resolve_identities
from src.models import (
    ExtractionMethod,
    RawFieldValue,
    SourceRecord,
    SourceType,
)


def _make_record(
    name: str | None = None,
    email: str | None = None,
    phone: str | None = None,
    source_type: SourceType = SourceType.RECRUITER_NOTES,
    source_id: str = "test",
) -> SourceRecord:
    """Helper: build a minimal SourceRecord for identity tests."""
    record = SourceRecord(source_type=source_type, source_id=source_id)
    if name:
        record.full_name = RawFieldValue(
            value=name, method=ExtractionMethod.REGEX, confidence=0.9
        )
    if email:
        record.emails.append(
            RawFieldValue(value=email, method=ExtractionMethod.REGEX, confidence=0.9)
        )
    if phone:
        record.phones.append(
            RawFieldValue(value=phone, method=ExtractionMethod.REGEX, confidence=0.8)
        )
    return record


# ---------------------------------------------------------------------------
# Test 1: Devanagari + Latin → same candidate (merged via shared email)
# ---------------------------------------------------------------------------

def test_devanagari_latin_same_person_via_email():
    """
    ATS record: "Priya Sharma" (Latin)
    Notes record: "प्रिया शर्मा" (Devanagari)
    Same email → should merge into ONE cluster.
    The name gate must NOT block the merge: unidecode('प्रिया शर्मा')
    → 'Priya Sharma' → key 'priya_sharma' which is identical to the Latin key.
    """
    r_ats = _make_record(
        name="Priya Sharma",
        email="priya@example.com",
        source_type=SourceType.ATS_JSON,
        source_id="ats_row_1",
    )
    r_notes = _make_record(
        name="प्रिया शर्मा",
        email="priya@example.com",  # same email
        source_type=SourceType.RECRUITER_NOTES,
        source_id="notes_priya.txt",
    )

    clusters = resolve_identities([r_ats, r_notes])
    assert len(clusters) == 1, (
        f"Expected 1 cluster (same person, different scripts), got {len(clusters)}. "
        "Devanagari name should transliterate to the same key as the Latin form."
    )
    assert len(clusters[0].records) == 2


# ---------------------------------------------------------------------------
# Test 2: Arabic + Latin same person via shared phone
# ---------------------------------------------------------------------------

def test_arabic_latin_same_person_via_phone():
    """
    CSV record: "Ali Hassan" (Latin)
    Notes record: "علي حسن" (Arabic)
    Same phone → should merge. Script-aware threshold: INDIC_ARABIC ↔ LATIN = 0.45.
    """
    r_csv = _make_record(
        name="Ali Hassan",
        phone="+14155551234",
        source_type=SourceType.RECRUITER_CSV,
        source_id="csv_row_5",
    )
    r_notes = _make_record(
        name="علي حسن",
        phone="+14155551234",  # same phone
        source_type=SourceType.RECRUITER_NOTES,
        source_id="notes_ali.txt",
    )

    clusters = resolve_identities([r_csv, r_notes])
    assert len(clusters) == 1, (
        f"Expected 1 cluster (Arabic + Latin same person via phone), got {len(clusters)}. "
        "The name gate should not block this merge (names are transliteration-similar)."
    )


# ---------------------------------------------------------------------------
# Test 3: CJK name + Latin phonetic → not falsely split (lenient threshold)
# ---------------------------------------------------------------------------

def test_cjk_latin_not_falsely_split():
    """
    Two records for the same person:
      - Japanese katakana name: "プリヤ シャルマ"
      - Latin phonetic: "Puriya Sharuma" (Hepburn romanisation)
    They share an email. The SequenceMatcher on their name_keys may produce
    a ratio BELOW 0.5 (Latin-Latin default). With the CJK-aware threshold
    of 0.35, the merge should go through.
    """
    r_ats = _make_record(
        name="Puriya Sharuma",
        email="puriya@example.com",
        source_type=SourceType.ATS_JSON,
        source_id="ats_puriya",
    )
    r_notes = _make_record(
        name="プリヤ シャルマ",
        email="puriya@example.com",  # same email
        source_type=SourceType.RECRUITER_NOTES,
        source_id="notes_puriya.txt",
    )

    clusters = resolve_identities([r_ats, r_notes])
    # With the lenient CJK threshold, the name gate should not block this.
    assert len(clusters) == 1, (
        f"Expected 1 cluster (CJK + Latin phonetic via email), got {len(clusters)}. "
        "CJK script-aware threshold (0.35) should prevent false split."
    )


# ---------------------------------------------------------------------------
# Test 4: Phone collision between DIFFERENT people → not merged
# ---------------------------------------------------------------------------

def test_phone_collision_different_names_not_merged():
    """
    Faker-pool phone collision: two unrelated people happen to share a phone
    number in the dataset. Their names are clearly different → should NOT merge.
    This is the 'wrong-but-confident' failure the assignment explicitly warns against.
    """
    r1 = _make_record(
        name="Jay Ramirez",
        phone="+15559991234",
        source_type=SourceType.ATS_JSON,
        source_id="ats_jay",
    )
    r2 = _make_record(
        name="Susan Rogers",
        phone="+15559991234",  # same phone, different person
        source_type=SourceType.ATS_JSON,
        source_id="ats_susan",
    )

    clusters = resolve_identities([r1, r2])
    assert len(clusters) == 2, (
        f"Expected 2 clusters (Faker phone collision), got {len(clusters)}. "
        "Records with the same phone but clearly different names must NOT merge."
    )


# ---------------------------------------------------------------------------
# Test 5: Suffix variants (Jr./Sr.) → same candidate
# ---------------------------------------------------------------------------

def test_suffix_variants_same_person():
    """
    "John Smith Jr." and "John Smith" appear in different sources.
    name_key strips suffixes → both yield key "john_smith" → merged.
    """
    r_ats = _make_record(
        name="John Smith Jr.",
        email="jsmith@example.com",
        source_type=SourceType.ATS_JSON,
        source_id="ats_jsmith",
    )
    r_csv = _make_record(
        name="John Smith",
        email="jsmith@example.com",
        source_type=SourceType.RECRUITER_CSV,
        source_id="csv_jsmith",
    )

    clusters = resolve_identities([r_ats, r_csv])
    assert len(clusters) == 1, (
        f"Expected 1 cluster (Jr. suffix stripped → same key), got {len(clusters)}."
    )


# ---------------------------------------------------------------------------
# Test 6: First/last name swap across sources → merged
# ---------------------------------------------------------------------------

def test_first_last_swap_same_person():
    """
    "Sharma Priya" (last-first) in one source, "Priya Sharma" (first-last) in another.
    normalize_name_key sorts tokens → both produce "priya_sharma".
    """
    r_ats = _make_record(
        name="Priya Sharma",
        email="priya.sharma@corp.com",
        source_type=SourceType.ATS_JSON,
        source_id="ats_ps",
    )
    r_notes = _make_record(
        name="Sharma Priya",  # last-first swap
        email="priya.sharma@corp.com",
        source_type=SourceType.RECRUITER_NOTES,
        source_id="notes_ps.txt",
    )

    clusters = resolve_identities([r_ats, r_notes])
    assert len(clusters) == 1, (
        f"Expected 1 cluster (first/last swap → same token-sorted key), got {len(clusters)}."
    )
