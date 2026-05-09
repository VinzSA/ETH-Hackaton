"""
ASA Physical Status Classification estimator (ASA 2020 revision)

Estimates the most likely ASA class from a PatientRecord.
This is NOT a replacement for an anaesthesiologist's clinical assessment;
it is a decision-support hint to flag if the extracted data suggests
a class the clinician should confirm.

ASA I    — Normal healthy patient
ASA II   — Mild systemic disease, no functional limitation
ASA III  — Severe systemic disease, functional limitation
ASA IV   — Severe systemic disease, constant threat to life
ASA V    — Moribund
ASA VI   — Brain-dead organ donor
"""
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class ASAResult:
    estimated_class: int        # 1–5
    rationale: list[str]        # conditions that drove the estimate
    upgrades_applied: list[str] # each rule that pushed the score up
    caveats: list[str]          # missing info that might change the estimate

    def to_dict(self) -> dict:
        return self.__dict__.copy()


def estimate_asa(record, patient_age: int | None = None) -> ASAResult:
    """
    Returns an estimated ASA class and the rules that drove it.
    Starts at 1, applies upgrade rules in priority order, returns the max.
    """
    upgrades: list[tuple[int, str]] = []  # (class, reason)
    caveats: list[str] = []

    def _diag(*kw: str) -> bool:
        return any(any(k in d.description.lower() for k in kw) for d in record.diagnoses)

    def _med(*kw: str) -> bool:
        return any(any(k in m.name.lower() for k in kw) for m in record.medications)

    def _lab(name: str) -> float | None:
        for l in record.labs:
            if l.test_name.upper() == name.upper():
                return l.value
        return None

    # ── ASA II upgrades ──────────────────────────────────────────────────────
    # Well-controlled single-organ disease, mild comorbidities

    if _diag("hypothyroidism", "hyperthyroidism") or _med("levothyroxine"):
        upgrades.append((2, "Thyroid disease (ASA II — well-controlled)"))

    if _diag("mild asthma", "seasonal asthma") and not _diag("severe asthma", "status asthmaticus"):
        upgrades.append((2, "Mild asthma, no hospitalisation (ASA II)"))

    if _diag("atrial fibrillation") and not _diag("heart failure"):
        upgrades.append((2, "Controlled atrial fibrillation without CHF (ASA II)"))

    bmi = _lab("bmi") or _lab("body mass index")
    if bmi and 30 <= bmi < 40:
        upgrades.append((2, f"Obesity BMI {bmi:.1f} (ASA II — BMI 30–39)"))

    if _diag("controlled hypertension", "hypertension") and not _diag("uncontrolled hypertension"):
        upgrades.append((2, "Controlled hypertension (ASA II)"))

    if _diag("type 2 diabetes") and not _diag("diabetic nephropathy", "end-organ damage"):
        # Controlled DM without end-organ damage
        hba1c = _lab("hba1c") or _lab("hba1c")
        if hba1c and hba1c <= 8.0:
            upgrades.append((2, f"Well-controlled type 2 DM (HbA1c {hba1c:.1f}%, ASA II)"))
        else:
            upgrades.append((2, "Type 2 DM (ASA II, HbA1c unknown or not specified)"))

    if patient_age and (patient_age < 1 or patient_age > 75):
        upgrades.append((2, f"Age {patient_age} — age extremes (ASA II)"))

    # ── ASA III upgrades ─────────────────────────────────────────────────────

    # Poorly controlled DM (HbA1c > 8)
    hba1c = _lab("hba1c")
    if hba1c and hba1c > 8.0:
        upgrades.append((3, f"Poorly controlled DM (HbA1c {hba1c:.1f}%, ASA III)"))

    # COPD (any severity documented)
    if _diag("copd", "chronic obstructive pulmonary", "emphysema", "chronic bronchitis"):
        upgrades.append((3, "COPD (ASA III)"))

    # Morbid obesity
    if bmi and bmi >= 40:
        upgrades.append((3, f"Morbid obesity BMI {bmi:.1f} (ASA III)"))

    # Active hepatitis or alcohol abuse
    if _diag("hepatitis", "cirrhosis", "liver failure"):
        upgrades.append((3, "Significant hepatic disease (ASA III)"))

    # Implanted cardiac device
    pacemaker = any(
        "pacemaker" in i.description.lower() or "icd" in i.description.lower()
        for i in record.implants
    )
    if pacemaker:
        upgrades.append((3, "Implanted cardiac device (pacemaker / ICD) — ASA III"))

    # Prior MI > 3 months ago
    cardiac = record.cardiac
    if any(c.has_history_mi for c in (cardiac or [])):
        upgrades.append((3, "History of myocardial infarction (> 3 months ago — ASA III)"))

    # Chronic kidney disease
    cr = _lab("creatinine")
    if _diag("chronic kidney disease", "ckd") or (cr and cr > 1.5):
        upgrades.append((3, "Chronic kidney disease / elevated creatinine (ASA III)"))

    # Controlled CHF (EF 30–40%) or NYHA II–III
    ef = next((c.ejection_fraction_pct for c in (cardiac or []) if c.ejection_fraction_pct is not None), None)
    if ef is not None and 30 <= ef < 45:
        upgrades.append((3, f"Reduced EF {ef:.0f}% (ASA III)"))

    if any((c.nyha_class or 0) in (2, 3) for c in (cardiac or [])):
        upgrades.append((3, "NYHA Class II–III (ASA III)"))

    # Poorly controlled hypertension
    if _diag("uncontrolled hypertension", "resistant hypertension"):
        upgrades.append((3, "Uncontrolled / resistant hypertension (ASA III)"))

    # Severe pulmonary hypertension, severe valvular disease
    if _diag("pulmonary hypertension"):
        upgrades.append((3, "Pulmonary hypertension (ASA III)"))

    if _diag("severe aortic stenosis", "severe mitral stenosis"):
        upgrades.append((3, "Severe valvular heart disease (ASA III)"))

    # Active cancer receiving treatment
    if _diag("malignancy", "cancer", "carcinoma", "lymphoma", "leukaemia", "leukemia"):
        upgrades.append((3, "Active malignancy (ASA III)"))

    # ── ASA IV upgrades ──────────────────────────────────────────────────────

    # Recent MI (< 3 months)
    # We can't tell timing from our schema; flag as missing
    if any(c.has_history_mi for c in (cardiac or [])):
        caveats.append("Cannot determine if MI was < 3 months ago — recent MI would upgrade to ASA IV")

    # Severe CHF / EF < 25%
    if ef is not None and ef < 25:
        upgrades.append((4, f"Severely reduced EF {ef:.0f}% (ASA IV)"))

    # NYHA IV
    if any((c.nyha_class or 0) == 4 for c in (cardiac or [])):
        upgrades.append((4, "NYHA Class IV — heart failure at rest (ASA IV)"))

    # Sepsis / multi-organ failure
    if _diag("sepsis", "septic shock", "multi-organ failure", "multiorgan failure"):
        upgrades.append((4, "Sepsis / multi-organ failure (ASA IV)"))

    # Dialysis
    if _diag("dialysis", "end-stage renal disease", "esrd"):
        upgrades.append((4, "Dialysis / ESRD (ASA IV)"))

    # ── ASA V upgrades ───────────────────────────────────────────────────────
    if _diag("moribund", "ruptured aortic aneurysm", "massive pulmonary embolism",
             "traumatic brain injury", "intracranial haemorrhage"):
        upgrades.append((5, "Life-threatening emergency (ASA V)"))

    # ── Resolve ──────────────────────────────────────────────────────────────
    if not upgrades:
        estimated = 1
        rationale = ["No significant comorbidities found (ASA I)"]
        applied = []
    else:
        estimated = max(u[0] for u in upgrades)
        applied = [u[1] for u in upgrades if u[0] == estimated]
        rationale = [u[1] for u in upgrades]

    if not record.diagnoses and not record.medications:
        caveats.append("No diagnoses or medications found — ASA I may be falsely low")

    return ASAResult(
        estimated_class=estimated,
        rationale=rationale,
        upgrades_applied=applied,
        caveats=caveats,
    )
