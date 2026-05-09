"""
Hand-annotated ground truth answer keys for the validation suite.

Two layers:
  1. ANNOTATED_CASES  — curated test documents with known facts (used in CI/unit tests).
     These are the same notes used in test_pipeline.py so the pipeline can be re-run
     and the output can be graded without any manual re-labelling.

  2. build_mtsamples_ground_truth()  — partial ground truth derived from the MT Samples
     keywords column.  Keywords are procedure/specialty descriptors that map to
     expected procedure extraction results.  This gives a scalable (if noisy) benchmark
     for the operative_note document type.

Categories graded: allergies, medications, conditions, anesthesia_history, labs, procedures
"""
from __future__ import annotations

# ── Curated annotated cases ───────────────────────────────────────────────────
# Each entry: { case_id: { category: set_of_expected_fact_strings } }
# Fact strings are normalised (lowercase) — grader normalises too, so case doesn't matter.
# Only include facts that are *explicitly* stated in the source text (no inferences).

ANNOTATED_CASES: dict[str, dict[str, set[str]]] = {

    # ── Discharge summary (English) ───────────────────────────────────────────
    "discharge_en": {
        "allergies": {
            "penicillin",
            "latex",
        },
        "medications": {
            "apixaban",
            "metoprolol succinate",
            "lisinopril",
            "metformin",
            "atorvastatin",
        },
        "conditions": {
            "atrial fibrillation",
            "hypertension",
            "type 2 diabetes mellitus",
            "chronic kidney disease",
        },
        "labs": set(),       # no labs in this note
        "procedures": set(),
        "anesthesia_history": set(),
    },

    # ── Lab report ────────────────────────────────────────────────────────────
    "lab_report": {
        "allergies":  set(),
        "medications": set(),
        "conditions": set(),
        "labs": {
            "hemoglobin",
            "platelets",
            "inr",
            "creatinine",
            "hba1c",
        },
        "procedures":        set(),
        "anesthesia_history": set(),
    },

    # ── Anesthesia record ─────────────────────────────────────────────────────
    "anesthesia_record": {
        "allergies":  set(),
        "medications": set(),
        "conditions": set(),
        "labs":       set(),
        "procedures": set(),
        # For anesthesia_history we grade the ASA score and complication type
        "anesthesia_history": {
            "asa iii",
            "general endotracheal",
            "hypotension",
        },
    },

    # ── Operative note ────────────────────────────────────────────────────────
    "operative_note": {
        "allergies":  set(),
        "medications": set(),
        "conditions": set(),
        "labs":       set(),
        "procedures": {
            "right total knee arthroplasty",
        },
        "anesthesia_history": set(),
    },

    # ── German discharge summary (tests translation pipeline) ─────────────────
    "discharge_de": {
        "allergies": {
            "penicillin",
        },
        "medications": {
            # Marcoumar = phenprocoumon; accept both names
            "phenprocoumon",
            "metoprolol",
            "metformin",
        },
        "conditions": {
            "atrial fibrillation",
            "hypertension",
            "type 2 diabetes mellitus",
        },
        "labs":       set(),
        "procedures": set(),
        "anesthesia_history": set(),
    },
}

# The raw source texts corresponding to the annotated cases above.
# These are intentionally duplicated here (they also live in test_pipeline.py)
# so the validation module is self-contained and does not depend on test imports.
CASE_TEXTS: dict[str, str] = {
    "discharge_en": """
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
""",

    "lab_report": """
LABORATORY RESULTS — 2024-01-14

Patient: John D., MRN 123456

Hemoglobin: 10.8 g/dL  [ref: 13.5-17.5]  LOW
Platelets: 142 K/uL     [ref: 150-400]    LOW
INR: 1.2               [ref: 0.8-1.2]
Creatinine: 1.6 mg/dL  [ref: 0.7-1.3]   HIGH
HbA1c: 7.8%            [ref: <5.7]       HIGH
""",

    "anesthesia_record": """
ANESTHESIA RECORD
Date: 2022-06-15  |  Procedure: Right total knee replacement

ASA Classification: III
Anesthesia type: General endotracheal
Intubation: Grade 1 view, uneventful.
Airway notes: Mallampati Class 2, no difficult airway anticipated.
Complications: Mild hypotension post-induction, responded to ephedrine 10mg IV.
""",

    "operative_note": """
OPERATIVE REPORT
Date: 2018-03-20  |  Surgeon: Dr. Smith

PROCEDURE: Right total knee arthroplasty

IMPLANT: Zimmer NexGen Complete Knee Solution, Size 4 femoral component.

COMPLICATIONS: None intraoperative.
""",

    "discharge_de": """
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
""",
}


# ── MT Samples partial ground truth ──────────────────────────────────────────

def build_mtsamples_ground_truth(samples: list[dict]) -> dict[str, dict[str, set[str]]]:
    """
    Build a partial ground truth dict from MT Samples rows.

    For operative notes, the 'keywords' column typically contains procedure names
    and anatomical terms that should appear in the extraction output.  This is a
    noisy but scalable proxy for ground truth on procedures.

    Only procedures are annotated this way — other categories require manual review.

    Parameters
    ----------
    samples : list[dict]  — rows from mtsamples.load_samples(), each must have
                            keys: 'id', 'document_type', 'keywords', 'transcription'

    Returns
    -------
    dict { sample_id: { category: set_of_facts } }
    """
    gt: dict[str, dict[str, set[str]]] = {}

    for row in samples:
        if row.get("document_type") != "operative_note":
            continue

        keywords_raw = row.get("keywords", "")
        if not keywords_raw:
            continue

        # Keywords are comma-separated; clean each one
        procedure_hints: set[str] = set()
        for kw in keywords_raw.split(","):
            kw = kw.strip().lower()
            # Skip very short / generic tokens
            if len(kw) >= 5 and kw not in {
                "surgery", "procedure", "patient", "right", "left", "bilateral",
                "general", "local", "anesthesia", "report", "note",
            }:
                procedure_hints.add(kw)

        if procedure_hints:
            gt[row["id"]] = {
                "allergies":         set(),
                "medications":       set(),
                "conditions":        set(),
                "labs":              set(),
                "procedures":        procedure_hints,
                "anesthesia_history": set(),
            }

    return gt


# ── Helpers ───────────────────────────────────────────────────────────────────

def normalise_ai_output(pipeline_result) -> dict[str, set[str]]:
    """
    Convert an ExtractedDocument (Pydantic model) into the flat { category: set }
    format expected by grade_category / grade_full_report.

    Medication and diagnosis names are stripped of dose/frequency suffixes so that
    "apixaban 5mg bid" matches the ground truth fact "apixaban".
    """
    def _strip_dose(name: str) -> str:
        import re
        # Remove trailing dose/frequency: "apixaban 5mg bid" → "apixaban"
        return re.split(r"\s+\d", name.strip().lower())[0].strip()

    meds = {_strip_dose(m.name) for m in pipeline_result.medications}
    allergies = {a.substance.lower().strip() for a in pipeline_result.allergies}
    conditions = {d.description.lower().strip() for d in pipeline_result.diagnoses}
    labs = {l.test_name.lower().strip() for l in pipeline_result.labs}
    procedures = {p.name.lower().strip() for p in pipeline_result.procedures}

    anesthesia_facts: set[str] = set()
    for ah in pipeline_result.anesthesia_history:
        if ah.asa_score is not None:
            anesthesia_facts.add(f"asa {_asa_numeral(ah.asa_score)}")
        if ah.anesthesia_type:
            anesthesia_facts.add(ah.anesthesia_type.lower().strip())
        if ah.complications:
            # Pull first word of complication as a rough signal
            first = ah.complications.lower().strip().split()[0]
            anesthesia_facts.add(first)

    return {
        "allergies":         allergies,
        "medications":       meds,
        "conditions":        conditions,
        "labs":              labs,
        "procedures":        procedures,
        "anesthesia_history": anesthesia_facts,
    }


def _asa_numeral(n: int) -> str:
    numerals = {1: "i", 2: "ii", 3: "iii", 4: "iv", 5: "v"}
    return numerals.get(n, str(n))
