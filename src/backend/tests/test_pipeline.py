"""
End-to-end pipeline tests.
Run with: ANTHROPIC_API_KEY=sk-ant-... python tests/test_pipeline.py
"""
import json
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# ── Test documents ───────────────────────────────────────────────────────────

DISCHARGE_NOTE = """
DISCHARGE SUMMARY
Patient: John D., 67M  |  Admission: 2024-01-10  |  Discharge: 2024-01-15

ALLERGIES: Penicillin (rash, moderate). Latex (contact dermatitis, mild).

ACTIVE DIAGNOSES:
1. Atrial fibrillation (chronic)
2. Hypertension
3. Type 2 Diabetes Mellitus (HbA1c 7.8% on 2023-11-01)
4. Chronic kidney disease, stage 3

MEDICATIONS ON DISCHARGE:
- Apixaban 5mg BID (anticoagulant, last dose 2024-01-15 08:00)
- Metoprolol succinate 50mg daily
- Lisinopril 10mg daily
- Metformin 1000mg BID
- Atorvastatin 40mg nightly
"""

LAB_NOTE = """
LABORATORY RESULTS — 2024-01-14

Patient: John D., MRN 123456

Hemoglobin: 10.8 g/dL  [ref: 13.5-17.5]  LOW
Platelets: 142 K/uL     [ref: 150-400]    LOW
INR: 1.2               [ref: 0.8-1.2]
Creatinine: 1.6 mg/dL  [ref: 0.7-1.3]   HIGH
HbA1c: 7.8%            [ref: <5.7]       HIGH
"""

ANESTHESIA_NOTE = """
ANESTHESIA RECORD
Date: 2022-06-15  |  Procedure: Right total knee replacement

ASA Classification: III
Anesthesia type: General endotracheal
Intubation: Grade 1 view, uneventful.
Airway notes: Mallampati Class 2, no difficult airway anticipated.
Complications: Mild hypotension post-induction, responded to ephedrine 10mg IV.
"""

OPERATIVE_NOTE = """
OPERATIVE REPORT
Date: 2018-03-20  |  Surgeon: Dr. Smith

PROCEDURE: Right total knee arthroplasty

IMPLANT: Zimmer NexGen Complete Knee Solution, Size 4 femoral component.

COMPLICATIONS: None intraoperative.
"""

# Older lab from a prior visit — used to test temporal reconciliation
OLD_LAB_NOTE = """
LABORATORY RESULTS — 2021-06-01

Patient: John D., MRN 123456

Hemoglobin: 13.2 g/dL
INR: 1.0
Creatinine: 1.1 mg/dL
"""

# German discharge summary — tests language detection + translation
GERMAN_DISCHARGE = """
Entlassungsbrief
Datum: 2023-08-10

Patient: Hans M., 72J

DIAGNOSEN:
1. Vorhofflimmern
2. Arterielle Hypertonie
3. Diabetes mellitus Typ 2

MEDIKAMENTE BEI ENTLASSUNG:
- Marcoumar 3mg täglich (Antikoagulans)
- Metoprolol 50mg täglich
- Metformin 500mg zweimal täglich

ALLERGIEN: Penicillin (Hautausschlag, moderat)
"""


def section(title: str):
    print(f"\n{'='*65}")
    print(f"  {title}")
    print(f"{'='*65}")


def print_result(result, label: str = ""):
    tag = f" [{label}]" if label else ""
    print(f"Type{tag}:        {result.document_type}")
    print(f"Date:           {result.document_date or 'not found'}")
    print(f"Language:       {result.language_detected}")
    print(f"Confidence:     {result.extraction_confidence}")
    print(f"Medications:    {len(result.medications)}")
    print(f"Diagnoses:      {len(result.diagnoses)}")
    print(f"Allergies:      {len(result.allergies)}")
    print(f"Labs:           {len(result.labs)}")
    print(f"Procedures:     {len(result.procedures)}")
    print(f"Implants:       {len(result.implants)}")
    print(f"Anesthesia:     {len(result.anesthesia_history)}")
    print(f"Cardiac:        {len(result.cardiac)}")
    if result.extraction_warnings:
        for w in result.extraction_warnings:
            print(f"  ⚠  {w}")


def run_single_doc_tests():
    from src.ingestion.pipeline import process_text
    from src.utils.date_extractor import extract_document_date

    section("TEST 1 — Date extractor (no API)")
    date_tests = [
        ("DISCHARGE SUMMARY\nDate: 2024-01-15\nPatient admitted.", "2024-01-15"),
        ("OPERATIVE REPORT\nProcedure Date: January 15, 2024", "2024-01-15"),
        ("LAB RESULTS\n15/01/2024\nINR: 2.8", "2024-01-15"),
        ("No date in this text at all.", None),
    ]
    for text, expected in date_tests:
        result = extract_document_date(text)
        status = "OK" if result == expected else f"FAIL (got {result}, expected {expected})"
        print(f"  '{text[:40]}...' → {result}  {status}")

    section("TEST 2 — Discharge summary")
    r = process_text(DISCHARGE_NOTE, document_id="test_discharge")
    print_result(r)
    print("\nMedications:")
    for m in r.medications:
        flag = " [ANTICOAG]" if m.is_anticoagulant else ""
        print(f"  {m.name} {m.dose} {m.frequency}{flag} | rxnorm={m.rxnorm_code} atc={m.atc_code}")
    print("\nDiagnoses:")
    for d in r.diagnoses:
        print(f"  {d.description} [{d.icd10_code}]")
    print("\nAllergies:")
    for a in r.allergies:
        print(f"  {a.substance} | {a.reaction} | {a.severity}")

    section("TEST 3 — Lab report")
    r = process_text(LAB_NOTE, document_id="test_labs")
    print_result(r)
    print("\nLabs:")
    for lab in r.labs:
        print(f"  {lab.test_name}: {lab.value} {lab.unit} | loinc={lab.loinc_code}")

    section("TEST 4 — Anesthesia record")
    r = process_text(ANESTHESIA_NOTE, document_id="test_anesthesia")
    print_result(r)
    if r.anesthesia_history:
        a = r.anesthesia_history[0]
        print(f"\n  ASA={a.asa_score} | type={a.anesthesia_type}")
        print(f"  Airway: {a.airway_notes}")
        print(f"  Complications: {a.complications}")

    section("TEST 5 — Operative note")
    r = process_text(OPERATIVE_NOTE, document_id="test_operative")
    print_result(r)
    for p in r.procedures:
        print(f"\n  Procedure: {p.name} | date={p.procedure_date}")
    for i in r.implants:
        print(f"  Implant: {i.description} | site={i.body_site}")

    section("TEST 6 — German discharge (language detection + translation)")
    r = process_text(GERMAN_DISCHARGE, document_id="test_german")
    print_result(r)
    print(f"\n  (original language detected: {r.language_detected})")
    if r.medications:
        print("  Medications:")
        for m in r.medications:
            print(f"    {m.name} {m.dose or ''} | anticoag={m.is_anticoagulant}")
    if r.diagnoses:
        print("  Diagnoses:")
        for d in r.diagnoses:
            print(f"    {d.description} [{d.icd10_code}]")


def run_merger_test():
    from src.ingestion.pipeline import process_patient

    section("TEST 7 — Multi-document merger + temporal reconciliation")
    print("Simulating 5 documents from the same patient across different dates...")
    print("(discharge 2024-01-15, labs 2024-01-14, anesthesia 2022-06-15,")
    print(" operative 2018-03-20, OLD labs 2021-06-01)")

    record = process_patient(
        sources=[],
        patient_id="patient_john_d",
        texts=[DISCHARGE_NOTE, LAB_NOTE, ANESTHESIA_NOTE, OPERATIVE_NOTE, OLD_LAB_NOTE],
    )

    print(f"\nPatient ID:         {record.patient_id}")
    print(f"Overall confidence: {record.overall_confidence}")
    print(f"\nDocument timeline:")
    for doc_id, date in record.document_timeline.items():
        print(f"  {doc_id}: {date or 'undated'}")

    print(f"\nMerged medications ({len(record.medications)}):")
    for m in record.medications:
        print(f"  {m.name} {m.dose or ''} {m.frequency or ''} | anticoag={m.is_anticoagulant}")

    print(f"\nMerged diagnoses ({len(record.diagnoses)}):")
    for d in record.diagnoses:
        print(f"  {d.description} [{d.icd10_code}]")

    print(f"\nMerged labs — most recent per test ({len(record.labs)}):")
    for lab in record.labs:
        print(f"  {lab.test_name}: {lab.value} {lab.unit}")

    print(f"\nProcedures ({len(record.procedures)}):")
    for p in record.procedures:
        print(f"  {p.name}")

    print(f"\nImplants ({len(record.implants)}):")
    for i in record.implants:
        print(f"  {i.description}")

    if record.stale_labs:
        print(f"\nStale labs (>6 months):")
        for s in record.stale_labs:
            print(f"  ⚠  {s}")

    if record.conflicts:
        print(f"\nConflicts detected:")
        for c in record.conflicts:
            print(f"  ↔  {c}")

    print(f"\nWarnings ({len(record.warnings)}):")
    for w in record.warnings:
        print(f"  ⚠  {w}")

    # Save full JSON
    out_path = os.path.join(os.path.dirname(__file__), "..", "data", "patient_record.json")
    with open(out_path, "w") as f:
        json.dump(record.to_dict(), f, indent=2, default=str)
    print(f"\nFull JSON saved → data/patient_record.json")


if __name__ == "__main__":
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ERROR: Set ANTHROPIC_API_KEY first.\n  export ANTHROPIC_API_KEY=sk-ant-...")
        sys.exit(1)

    run_single_doc_tests()
    run_merger_test()

    print(f"\n{'='*65}")
    print("  ALL TESTS DONE")
    print(f"{'='*65}\n")
