"""
Multi-document patient merger + temporal reconciliation.

Takes a list of ExtractedDocuments (one per uploaded PDF) and merges them
into a single consolidated PatientRecord. Rules:
  - Labs: most recent value per test name wins; stale values (>6 months) are flagged
  - Medications: union, deduplicated by name (most recent document wins on conflict)
  - Diagnoses: union, deduplicated by description
  - Allergies: union, deduplicated by substance
  - Procedures / Implants: all kept (each is a distinct historical event)
  - Anesthesia / Cardiac: most recent record per type kept
  - Conflicts (same field, different values across docs) → surfaced in warnings
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

from src.schema.preop_brief import (
    Allergy, AnesthesiaHistory, CardiacAssessment,
    Diagnosis, ExtractedDocument, Implant, LabValue,
    Medication, Procedure,
)
from src.utils.date_extractor import days_since, is_stale

STALE_DAYS = 180  # 6 months


@dataclass
class PatientRecord:
    """
    Consolidated view of a patient across all their documents.
    This is what the backend FHIR layer receives.
    """
    patient_id: str

    # Temporal index: doc_id → document_date (ISO string or None)
    document_timeline: dict[str, str | None] = field(default_factory=dict)

    # Wearable signals (optional — only present if a ZIP was uploaded)
    wearable_osa_signal: dict | None = None          # OSASignal serialised
    wearable_functional_capacity: dict | None = None  # FunctionalCapacity serialised
    wearable_hr_trend: dict | None = None             # HRTrend serialised

    # Merged clinical entities
    medications: list[Medication] = field(default_factory=list)
    diagnoses: list[Diagnosis] = field(default_factory=list)
    allergies: list[Allergy] = field(default_factory=list)
    procedures: list[Procedure] = field(default_factory=list)
    implants: list[Implant] = field(default_factory=list)
    labs: list[LabValue] = field(default_factory=list)          # most recent per test
    anesthesia_history: list[AnesthesiaHistory] = field(default_factory=list)
    cardiac: list[CardiacAssessment] = field(default_factory=list)

    # Quality
    stale_labs: list[str] = field(default_factory=list)         # lab names that are >6 months old
    conflicts: list[str] = field(default_factory=list)          # human-readable conflict notes
    warnings: list[str] = field(default_factory=list)
    overall_confidence: float = 1.0

    def to_dict(self) -> dict:
        import dataclasses, json
        return json.loads(json.dumps(dataclasses.asdict(self), default=str))


def merge_documents(
    documents: list[ExtractedDocument],
    patient_id: str | None = None,
) -> PatientRecord:
    """
    Merge a list of ExtractedDocuments (one per PDF) into one PatientRecord.
    Documents do not need to be pre-sorted — this function sorts by date internally.
    """
    import uuid
    pid = patient_id or str(uuid.uuid4())

    if not documents:
        return PatientRecord(patient_id=pid)

    # Sort documents by date (oldest first, None dates go last)
    sorted_docs = sorted(documents, key=_doc_sort_key)

    record = PatientRecord(patient_id=pid)

    # Build timeline index
    for doc in sorted_docs:
        record.document_timeline[doc.document_id] = doc.document_date

    # Merge each entity type
    record.medications    = _merge_medications(sorted_docs, record.conflicts)
    record.diagnoses      = _merge_diagnoses(sorted_docs)
    record.allergies      = _merge_allergies(sorted_docs)
    record.procedures     = _merge_all(sorted_docs, "procedures")
    record.implants       = _merge_all(sorted_docs, "implants")
    record.labs, record.stale_labs = _merge_labs(sorted_docs, record.conflicts)
    record.anesthesia_history = _merge_anesthesia(sorted_docs)
    record.cardiac        = _merge_cardiac(sorted_docs, record.conflicts)

    # Propagate per-document warnings
    for doc in sorted_docs:
        for w in doc.extraction_warnings:
            tagged = f"[{doc.document_type} / {doc.document_date or 'undated'}] {w}"
            if tagged not in record.warnings:
                record.warnings.append(tagged)

    # Clinical safety gap checks on the merged record
    record.warnings.extend(_safety_gap_checks(record))

    # Overall confidence = mean of document confidences, penalised by conflicts
    mean_conf = sum(d.extraction_confidence for d in sorted_docs) / len(sorted_docs)
    conflict_penalty = min(0.2, len(record.conflicts) * 0.05)
    record.overall_confidence = round(max(0.0, mean_conf - conflict_penalty), 2)

    return record


# ── Merge helpers ────────────────────────────────────────────────────────────

def _doc_sort_key(doc: ExtractedDocument):
    """Sort key: documents with dates first (oldest → newest), undated last."""
    if doc.document_date:
        try:
            return datetime.strptime(doc.document_date, "%Y-%m-%d")
        except ValueError:
            pass
    return datetime(9999, 1, 1)


def _merge_medications(docs: list[ExtractedDocument], conflicts: list[str]) -> list[Medication]:
    """
    Union of all medications, deduplicated by normalised drug name.
    Later documents (more recent) win on conflict.
    """
    seen: dict[str, Medication] = {}
    for doc in docs:
        for med in doc.medications:
            key = _normalize_str(med.name)
            if key in seen:
                prev = seen[key]
                # Flag dose conflict across documents
                if prev.dose and med.dose and prev.dose != med.dose:
                    conflicts.append(
                        f"Medication dose conflict for {med.name}: "
                        f"'{prev.dose}' vs '{med.dose}' — using more recent value"
                    )
            seen[key] = med  # later (more recent) doc always wins
    return list(seen.values())


def _merge_diagnoses(docs: list[ExtractedDocument]) -> list[Diagnosis]:
    seen: dict[str, Diagnosis] = {}
    for doc in docs:
        for diag in doc.diagnoses:
            key = _normalize_str(diag.description)
            if key not in seen:
                seen[key] = diag
            else:
                # If a later document marks it active, trust that
                if diag.is_active and not seen[key].is_active:
                    seen[key] = diag
    return list(seen.values())


def _merge_allergies(docs: list[ExtractedDocument]) -> list[Allergy]:
    seen: dict[str, Allergy] = {}
    for doc in docs:
        for allergy in doc.allergies:
            key = _normalize_str(allergy.substance)
            if key not in seen:
                seen[key] = allergy
            else:
                # Escalate severity if a newer document reports worse reaction
                existing = seen[key]
                if _severity_rank(allergy.severity) > _severity_rank(existing.severity):
                    seen[key] = allergy
    return list(seen.values())


def _merge_all(docs: list[ExtractedDocument], attr: str) -> list:
    """Procedures and implants — just concatenate, each is a distinct event."""
    result = []
    for doc in docs:
        result.extend(getattr(doc, attr))
    return result


def _merge_labs(
    docs: list[ExtractedDocument],
    conflicts: list[str],
) -> tuple[list[LabValue], list[str]]:
    """
    Most recent lab value per test name wins.
    Flags stale values (>6 months old) and significant value shifts.
    """
    seen: dict[str, tuple[LabValue, str | None]] = {}  # test_name → (lab, doc_date)

    for doc in docs:
        for lab in doc.labs:
            key = lab.test_name.upper()
            doc_date = doc.document_date

            if key not in seen:
                seen[key] = (lab, doc_date)
            else:
                prev_lab, prev_date = seen[key]
                # Significant shift check for critical labs
                if _is_significant_shift(lab.test_name, prev_lab.value, lab.value):
                    conflicts.append(
                        f"Significant {lab.test_name} shift: "
                        f"{prev_lab.value} {prev_lab.unit} ({prev_date or 'undated'}) → "
                        f"{lab.value} {lab.unit} ({doc_date or 'undated'})"
                    )
                seen[key] = (lab, doc_date)  # most recent wins

    merged_labs = []
    stale_names = []
    for key, (lab, doc_date) in seen.items():
        merged_labs.append(lab)
        if is_stale(doc_date, STALE_DAYS):
            stale_names.append(f"{lab.test_name} ({doc_date})")

    return merged_labs, stale_names


def _merge_anesthesia(docs: list[ExtractedDocument]) -> list[AnesthesiaHistory]:
    """Keep the most recent anesthesia record (last in sorted list)."""
    all_records = []
    for doc in docs:
        all_records.extend(doc.anesthesia_history)
    # Return most recent (last document wins due to sort order)
    return [all_records[-1]] if all_records else []


def _merge_cardiac(
    docs: list[ExtractedDocument],
    conflicts: list[str],
) -> list[CardiacAssessment]:
    """Most recent cardiac assessment. Flag significant EF changes."""
    all_cardiac = []
    for doc in docs:
        all_cardiac.extend(doc.cardiac)

    if len(all_cardiac) > 1:
        first_ef = all_cardiac[0].ejection_fraction_pct
        last_ef = all_cardiac[-1].ejection_fraction_pct
        if first_ef and last_ef and abs(first_ef - last_ef) >= 10:
            conflicts.append(
                f"EF changed significantly: {first_ef}% → {last_ef}% — clinical review needed"
            )

    return [all_cardiac[-1]] if all_cardiac else []


# ── Safety gap checks on merged record ──────────────────────────────────────

def _safety_gap_checks(record: PatientRecord) -> list[str]:
    warnings = []

    anticoag_names = {"warfarin", "apixaban", "rivaroxaban", "dabigatran",
                      "heparin", "enoxaparin", "fondaparinux", "edoxaban"}
    on_anticoag = any(
        _normalize_str(m.name) in anticoag_names or m.is_anticoagulant
        for m in record.medications
    )
    has_inr = any(lab.test_name.upper() == "INR" for lab in record.labs)
    if on_anticoag and not has_inr:
        warnings.append("SAFETY: Patient on anticoagulant — no INR found across all documents")

    has_diabetes = any(
        "diabet" in _normalize_str(d.description)
        for d in record.diagnoses
    )
    has_hba1c = any(lab.test_name == "HbA1c" for lab in record.labs)
    if has_diabetes and not has_hba1c:
        warnings.append("SAFETY: Diabetes diagnosed — no HbA1c found across all documents")

    has_cardiac = bool(record.cardiac)
    has_ef = any(c.ejection_fraction_pct is not None for c in record.cardiac)
    if has_cardiac and not has_ef:
        warnings.append("SAFETY: Cardiac history present — no ejection fraction recorded")

    if record.stale_labs:
        warnings.append(
            f"STALE DATA (>6 months): {', '.join(record.stale_labs)} — verify current values"
        )

    pacemaker_in_implants = any(
        "pacemaker" in _normalize_str(i.description) or "icd" in _normalize_str(i.description)
        for i in record.implants
    )
    if pacemaker_in_implants:
        warnings.append("SAFETY: Cardiac device implant found — confirm device type and last check")

    return warnings


def apply_wearable_signals(record: PatientRecord, signals) -> None:
    """
    Merge wearable signals into an existing PatientRecord in-place.
    `signals` is a WearableSignals object from wearable_extractor.py.
    Adds wearable fields and fires cross-source gap rules.
    """
    import dataclasses

    if signals.osa:
        record.wearable_osa_signal = dataclasses.asdict(signals.osa)
        _check_osa_gaps(record, signals.osa)

    if signals.functional_capacity:
        record.wearable_functional_capacity = dataclasses.asdict(signals.functional_capacity)
        _check_functional_capacity_gaps(record, signals.functional_capacity)

    if signals.hr_trend:
        record.wearable_hr_trend = dataclasses.asdict(signals.hr_trend)
        if signals.hr_trend.trend == "rising":
            record.warnings.append(
                f"WEARABLE: Resting HR rising "
                f"({signals.hr_trend.slope_bpm_per_day:+.2f} bpm/day over "
                f"{signals.hr_trend.days_analyzed} days) — possible cardiac decompensation"
            )


def _check_osa_gaps(record: PatientRecord, osa) -> None:
    if not osa.probable_osa:
        return

    # Rule 1: probable OSA but no CPAP/BiPAP in medication or anesthesia records
    cpap_keywords = {"cpap", "bipap", "apap", "continuous positive", "sleep apnea"}
    cpap_in_meds = any(
        any(kw in _normalize_str(m.name) for kw in cpap_keywords)
        for m in record.medications
    )
    cpap_in_anesthesia = any(
        a.airway_notes and any(kw in a.airway_notes.lower() for kw in cpap_keywords)
        for a in record.anesthesia_history
    )
    osa_in_diagnoses = any(
        "apnea" in _normalize_str(d.description) or "osa" in _normalize_str(d.description)
        for d in record.diagnoses
    )

    if not cpap_in_meds and not cpap_in_anesthesia:
        if osa_in_diagnoses:
            record.warnings.append(
                f"WEARABLE + CLINICAL: OSA diagnosed but no CPAP/BiPAP found in records "
                f"(wearable: {osa.nights_with_dips}/{osa.nights_analyzed} nights with SpO₂ dips)"
            )
        else:
            record.warnings.append(
                f"WEARABLE: Probable OSA signal — {osa.nights_with_dips}/{osa.nights_analyzed} "
                f"nights with SpO₂<90% dips (confidence {osa.confidence:.0%}). "
                f"No OSA diagnosis or CPAP found in clinical records — flag for anaesthesiologist"
            )


def _check_functional_capacity_gaps(record: PatientRecord, fc) -> None:
    # Rule 2: wearable says high capacity but ASA ≥ III — possible ASA overestimate
    asa_scores = [a.asa_score for a in record.anesthesia_history if a.asa_score is not None]
    if asa_scores and fc.level == "high":
        max_asa = max(asa_scores)
        if max_asa >= 3:
            record.warnings.append(
                f"WEARABLE ↔ CLINICAL CONFLICT: Wearable shows high functional capacity "
                f"({int(fc.avg_daily_steps_30d):,} steps/day) but prior ASA score is {max_asa} — "
                f"possible ASA overestimate; reassess"
            )

    # Rule 3: low functional capacity is a direct anaesthesia risk flag
    if fc.level == "low":
        record.warnings.append(
            f"WEARABLE: Low functional capacity — {int(fc.avg_daily_steps_30d):,} steps/day avg "
            f"(<3,500 threshold). Equivalent to <4 METs; increased perioperative risk."
        )


# ── Utilities ────────────────────────────────────────────────────────────────

def _normalize_str(s: str) -> str:
    import re
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _severity_rank(severity: str | None) -> int:
    return {"mild": 1, "moderate": 2, "severe": 3, "anaphylaxis": 4}.get(severity or "", 0)


def _is_significant_shift(test_name: str, old_val: float, new_val: float) -> bool:
    """Flag clinically meaningful changes between documents."""
    thresholds = {
        "INR": 0.5,          # e.g. 1.2 → 2.8 is a big deal
        "creatinine": 0.5,
        "hemoglobin": 2.0,
        "platelets": 50.0,
        "HbA1c": 1.5,
        "EF": 10.0,
    }
    threshold = thresholds.get(test_name, float("inf"))
    return abs(new_val - old_val) >= threshold
