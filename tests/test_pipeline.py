"""
End-to-end pipeline tests.
Run with: ANTHROPIC_API_KEY=sk-ant-... python -m pytest tests/ -v
Or for a quick smoke test: ANTHROPIC_API_KEY=sk-ant-... python tests/test_pipeline.py
"""
import json
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

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

DISCHARGE CONDITION: Stable. Follow-up with cardiology in 4 weeks.
"""

LAB_NOTE = """
LABORATORY RESULTS — 2024-01-14

Patient: John D., MRN 123456

Hematology:
  Hemoglobin: 10.8 g/dL  [ref: 13.5-17.5]  LOW
  Platelets: 142 K/uL     [ref: 150-400]    LOW

Coagulation:
  INR: 1.2               [ref: 0.8-1.2]
  PT: 13.4 sec

Chemistry:
  Creatinine: 1.6 mg/dL  [ref: 0.7-1.3]   HIGH
  eGFR: 48 mL/min/1.73m2

Endocrine:
  HbA1c: 7.8%            [ref: <5.7]       HIGH
"""

ANESTHESIA_NOTE = """
ANESTHESIA RECORD
Date: 2022-06-15  |  Procedure: Right total knee replacement

ASA Classification: III
Anesthesia type: General endotracheal
Pre-induction: Midazolam 2mg IV, Fentanyl 100mcg IV
Induction: Propofol 150mg IV
Intubation: Grade 1 view, uneventful. Size 7.5 ETT.
Airway notes: Mallampati Class 2, no difficult airway anticipated.
Maintenance: Sevoflurane 2% in O2/air
Complications: Mild hypotension post-induction, responded to ephedrine 10mg IV.
Emergence: Smooth, extubated in OR. PACU: stable.
"""

OPERATIVE_NOTE = """
OPERATIVE REPORT
Date: 2018-03-20  |  Surgeon: Dr. Smith

PROCEDURE: Right total knee arthroplasty

IMPLANT: Zimmer NexGen Complete Knee Solution, Size 4 femoral component,
size 3 tibial insert. Serial: ZN-2018-4477.

DESCRIPTION: Patient positioned supine. Tourniquet applied right thigh at 300mmHg.
Standard medial parapatellar approach. Distal femur and proximal tibia resected.
Implants seated and cemented. Wound irrigated and closed in layers.

COMPLICATIONS: None intraoperative.
ESTIMATED BLOOD LOSS: 200 mL
"""


def run_test(name: str, text: str, expected_type: str):
    from src.ingestion.pipeline import process_text

    print(f"\n{'='*60}")
    print(f"TEST: {name}")
    print(f"{'='*60}")

    result = process_text(text, document_id=f"test_{name.replace(' ', '_')}")

    print(f"Document type:     {result.document_type}  {'OK' if result.document_type == expected_type else f'FAIL (expected {expected_type})'}")
    print(f"Confidence:        {result.extraction_confidence}")
    print(f"Medications:       {len(result.medications)}")
    print(f"Diagnoses:         {len(result.diagnoses)}")
    print(f"Allergies:         {len(result.allergies)}")
    print(f"Labs:              {len(result.labs)}")
    print(f"Procedures:        {len(result.procedures)}")
    print(f"Implants:          {len(result.implants)}")
    print(f"Anesthesia:        {len(result.anesthesia_history)}")
    print(f"Cardiac:           {len(result.cardiac)}")
    print(f"Warnings:          {result.extraction_warnings}")

    if result.medications:
        print("\nMedications extracted:")
        for m in result.medications:
            print(f"  - {m.name} {m.dose or ''} {m.frequency or ''} | rxnorm={m.rxnorm_code} atc={m.atc_code} | anticoag={m.is_anticoagulant}")

    if result.diagnoses:
        print("\nDiagnoses extracted:")
        for d in result.diagnoses:
            print(f"  - {d.description} [{d.icd10_code}] active={d.is_active}")

    if result.allergies:
        print("\nAllergies extracted:")
        for a in result.allergies:
            print(f"  - {a.substance} | reaction={a.reaction} | severity={a.severity}")

    if result.labs:
        print("\nLabs extracted:")
        for lab in result.labs:
            print(f"  - {lab.test_name}: {lab.value} {lab.unit} | loinc={lab.loinc_code}")

    if result.anesthesia_history:
        a = result.anesthesia_history[0]
        print(f"\nAnesthesia: ASA={a.asa_score} type={a.anesthesia_type}")
        print(f"  Airway: {a.airway_notes}")
        print(f"  Complications: {a.complications}")

    if result.procedures:
        for p in result.procedures:
            print(f"\nProcedure: {p.name} | complications={p.complications}")

    if result.implants:
        for imp in result.implants:
            print(f"\nImplant: {imp.description} | site={imp.body_site}")

    return result


if __name__ == "__main__":
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ERROR: Set ANTHROPIC_API_KEY environment variable first.")
        print("  export ANTHROPIC_API_KEY=sk-ant-...")
        sys.exit(1)

    results = []
    results.append(run_test("Discharge Summary", DISCHARGE_NOTE, "discharge_summary"))
    results.append(run_test("Lab Report", LAB_NOTE, "lab_report"))
    results.append(run_test("Anesthesia Record", ANESTHESIA_NOTE, "anesthesia_record"))
    results.append(run_test("Operative Note", OPERATIVE_NOTE, "operative_note"))

    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    print(f"Tests run: {len(results)}")
    print(f"Avg confidence: {sum(r.extraction_confidence for r in results)/len(results):.2f}")

    # Output full JSON of first result for backend team inspection
    print("\nFull JSON (discharge summary):")
    print(json.dumps(results[0].model_dump(), indent=2, default=str))
