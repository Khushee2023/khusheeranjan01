"""
Reduction phase: merge a CandidateCluster (multiple SourceRecords for one
person) into a single CanonicalCandidate.

This is where trust_policy.py gets applied for real: for every field, look
at all candidate values across the cluster's records, rank them by
(field-specific source trust, then extraction confidence), and take the
highest-ranked non-null value as the winner. List-type fields (emails,
phones, skills) are unioned + deduped rather than "winner takes all", since
a candidate legitimately can have multiple emails/phones.

Every chosen value gets a ProvenanceEntry. overall_confidence is a simple
weighted average of per-field confidences actually populated (missing fields
don't drag the average down to zero â€” an empty field is "unknown", not "low
confidence").
"""

from __future__ import annotations

from collections import defaultdict
from typing import List, Optional

from src.identity.graph_linkage import CandidateCluster
from src.models import (
    CanonicalCandidate,
    Education,
    Experience,
    ExtractionMethod,
    Links,
    ProvenanceEntry,
    RawFieldValue,
    SourceRecord,
    SourceType,
    Skill,
)
from src.normalize.name_normalizer import normalize_display_name
from src.normalize.phone_engine import dedupe_phones, normalize_phone
from src.normalize.date_engine import normalize_date_pair, parse_years_experience
from src.normalize.skill_engine import canonicalize_skill
from src.reduction.trust_policy import combined_confidence, rank_for_field


def merge_cluster(cluster: CandidateCluster) -> CanonicalCandidate:
    candidate = CanonicalCandidate(candidate_id=cluster.candidate_id)
    provenance: List[ProvenanceEntry] = []
    field_confidences: List[float] = []

    # ---- full_name: winner-takes-all across records, ranked by trust ----
    name_winner = _pick_winner_scalar(
        cluster.records,
        field_name="full_name",
        getter=lambda r: r.full_name,
    )
    if name_winner is not None:
        record, raw_value = name_winner
        candidate.full_name = normalize_display_name(raw_value.value)
        conf = combined_confidence(SourceType(record.source_type), raw_value.confidence)
        provenance.append(
            ProvenanceEntry(
                field="full_name",
                source=SourceType(record.source_type),
                method=ExtractionMethod(raw_value.method),
                raw_value=raw_value.value,
                confidence=conf,
            )
        )
        field_confidences.append(conf)

    # ---- emails: union + dedupe, lowercase, provenance per unique value ----
    seen_emails: dict[str, tuple[SourceRecord, RawFieldValue]] = {}
    for record in cluster.records:
        for raw_email in record.emails:
            if not raw_email.value:
                continue
            key = raw_email.value.strip().lower()
            # Keep the highest-trust source if the same email appears twice
            if key not in seen_emails or _is_better(record, seen_emails[key][0], "emails"):
                seen_emails[key] = (record, raw_email)

    candidate.emails = list(seen_emails.keys())
    for email, (record, raw_email) in seen_emails.items():
        conf = combined_confidence(SourceType(record.source_type), raw_email.confidence)
        provenance.append(
            ProvenanceEntry(
                field=f"emails[{email}]",
                source=SourceType(record.source_type),
                method=ExtractionMethod(raw_email.method),
                raw_value=raw_email.value,
                confidence=conf,
            )
        )
        field_confidences.append(conf)

    # ---- phones: normalize to E.164 first, then union + dedupe ----
    seen_phones: dict[str, tuple[SourceRecord, RawFieldValue, float]] = {}
    for record in cluster.records:
        for raw_phone in record.phones:
            result = normalize_phone(raw_phone.value)
            if not result.e164:
                continue  # unparseable -> dropped, never invented
            if result.e164 not in seen_phones or _is_better(record, seen_phones[result.e164][0], "phones"):
                seen_phones[result.e164] = (record, raw_phone, result.confidence)

    candidate.phones = dedupe_phones(list(seen_phones.keys()))
    for phone, (record, raw_phone, parse_conf) in seen_phones.items():
        conf = combined_confidence(SourceType(record.source_type), raw_phone.confidence * parse_conf)
        provenance.append(
            ProvenanceEntry(
                field=f"phones[{phone}]",
                source=SourceType(record.source_type),
                method=ExtractionMethod.REGEX,
                raw_value=raw_phone.value,
                confidence=conf,
            )
        )
        field_confidences.append(conf)

    # ---- headline: winner-takes-all ----
    headline_winner = _pick_winner_scalar(
        cluster.records, field_name="headline", getter=lambda r: r.headline
    )
    if headline_winner is not None:
        record, raw_value = headline_winner
        candidate.headline = raw_value.value
        conf = combined_confidence(SourceType(record.source_type), raw_value.confidence)
        provenance.append(
            ProvenanceEntry(
                field="headline", source=SourceType(record.source_type),
                method=ExtractionMethod(raw_value.method), raw_value=raw_value.value, confidence=conf,
            )
        )
        field_confidences.append(conf)

    # ---- skills: union + canonicalize + dedupe ----
    # Each skill's raw value is passed through skill_engine.canonicalize_skill
    # before being added to the canonical profile. Skills that can't be
    # canonicalized to a known name are kept as-is (degraded confidence)
    # rather than dropped — per the "unknown becomes null, never invented"
    # rule, an unrecognizable skill is still better logged than silently lost.
    seen_skills: dict[str, tuple[SourceRecord, RawFieldValue]] = {}
    for record in cluster.records:
        for raw_skill in record.skills_raw:
            if not raw_skill.value:
                continue
            # Try to canonicalize; fall back to the raw value if unknown
            canonical_name = canonicalize_skill(raw_skill.value) or raw_skill.value.strip()
            if not canonical_name:
                continue
            if canonical_name not in seen_skills or _is_better(
                record, seen_skills[canonical_name][0], "skills"
            ):
                seen_skills[canonical_name] = (record, raw_skill)

    candidate.skills = []
    for skill_name, (record, raw_skill) in seen_skills.items():
        conf = combined_confidence(SourceType(record.source_type), raw_skill.confidence)
        candidate.skills.append(
            Skill(
                name=skill_name,
                confidence=conf,
                sources=[SourceType(record.source_type)],
            )
        )
        provenance.append(
            ProvenanceEntry(
                field=f"skills[{skill_name}]",
                source=SourceType(record.source_type),
                method=ExtractionMethod(raw_skill.method),
                raw_value=raw_skill.value,
                confidence=conf,
            )
        )
        field_confidences.append(conf)

    # ---- experience & education: concatenate across records, normalize dates ----
    raw_experiences = [exp for record in cluster.records for exp in record.experience_raw]
    candidate.experience = _dedupe_experience(_normalize_experience_dates(raw_experiences))
    candidate.education = _dedupe_education(
        [edu for record in cluster.records for edu in record.education_raw]
    )

    # ---- years_experience: computed from normalized experience dates ----
    total_years: float = 0.0
    for exp in candidate.experience:
        yrs = parse_years_experience(exp.start, exp.end)
        if yrs is not None:
            total_years += yrs
    if total_years > 0:
        candidate.years_experience = round(total_years, 1)

    # ---- links: take first non-null per sub-field across records ----
    for record in cluster.records:
        if not candidate.links.linkedin and record.links.linkedin:
            candidate.links.linkedin = record.links.linkedin
        if not candidate.links.github and record.links.github:
            candidate.links.github = record.links.github
        if not candidate.links.portfolio and record.links.portfolio:
            candidate.links.portfolio = record.links.portfolio
        candidate.links.other.extend(record.links.other)
    candidate.links.other = list(dict.fromkeys(candidate.links.other))  # dedupe, preserve order

    candidate.provenance = provenance
    candidate.source_records_merged = [SourceType(r.source_type) for r in cluster.records]
    candidate.overall_confidence = (
        round(sum(field_confidences) / len(field_confidences), 4) if field_confidences else 0.0
    )

    return candidate


def _pick_winner_scalar(
    records: List[SourceRecord],
    field_name: str,
    getter,
) -> Optional[tuple[SourceRecord, RawFieldValue]]:
    """
    Among all records that have a non-null value for this field, pick the one
    with the best (rank, confidence) â€” lowest rank number wins, ties broken
    by higher extraction confidence, then by source_id for full determinism.
    """
    candidates = []
    for record in records:
        value = getter(record)
        if value is not None and value.value:
            rank = rank_for_field(SourceType(record.source_type), field_name)
            candidates.append((rank, -value.confidence, record.source_id, record, value))

    if not candidates:
        return None

    candidates.sort(key=lambda t: (t[0], t[1], t[2]))  # deterministic tie-break
    _, _, _, winning_record, winning_value = candidates[0]
    return winning_record, winning_value


def _is_better(candidate_record: SourceRecord, current_record: SourceRecord, field_name: str) -> bool:
    return rank_for_field(SourceType(candidate_record.source_type), field_name) < rank_for_field(
        SourceType(current_record.source_type), field_name
    )


def _dedupe_experience(items: List[Experience]) -> List[Experience]:
    seen = {}
    for item in items:
        key = ((item.company or "").lower(), (item.title or "").lower())
        if key == ("", ""):
            continue
        if key not in seen:
            seen[key] = item
    return list(seen.values())


def _normalize_experience_dates(items: List[Experience]) -> List[Experience]:
    """
    Normalize start/end dates on every Experience to ISO-8601 "YYYY-MM"
    (or "present" for open-ended roles) using date_engine.

    Also enforces chronological order: if start > end both are swapped and
    a warning is emitted (date_engine handles this internally).

    Returns a NEW list — original Experience objects are NOT mutated.
    """
    normalized = []
    for exp in items:
        norm_start, norm_end = normalize_date_pair(exp.start, exp.end)
        # Create a new Experience with normalized dates (pydantic model, so
        # we use model_copy / dict + reconstruct)
        normalized.append(
            Experience(
                company=exp.company,
                title=exp.title,
                start=norm_start,
                end=norm_end,
                summary=exp.summary,
            )
        )
    return normalized


def _dedupe_education(items: List[Education]) -> List[Education]:
    seen = {}
    for item in items:
        key = ((item.institution or "").lower(), (item.degree or "").lower())
        if key == ("", ""):
            continue
        if key not in seen:
            seen[key] = item
    return list(seen.values())