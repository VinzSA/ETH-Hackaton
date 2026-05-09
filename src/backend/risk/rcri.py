"""
Revised Cardiac Risk Index (Lee et al. 1999)

6 independent predictors of major adverse cardiac events (MACE)
following non-cardiac surgery. Each criterion scores 1 point.

Score → MACE risk
  0   → ~0.4%
  1   → ~1.0%
  2   → ~2.4%
  ≥3  → ~5.4%
"""
from __future__ import annotations
from dataclasses import dataclass


@dataclass
class RCRIResult:
    score: int
    criteria_met: list[str]
    criteria_absent: list[str]
    mace_risk_pct: float        # point estimate
    risk_label: str             # "low" | "intermediate" | "high"
    missing_data: list[str]     # items that could not be assessed

    def to_dict(self) -> dict:
        return self.__dict__.copy()


# Probability table from Lee 1999 / AHA 2014 update
_MACE_RISK = {0: 0.4, 1: 1.0, 2: 2.4, 3: 5.4}


def compute_rcri(record) -> RCRIResult:
    """
    record: PatientRecord from ingestion/merger.py

    Each criterion is evaluated as True/False/None (None = missing data).
    Missing criteria are not counted but are surfaced in missing_data.
    """
    criteria_met: list[str] = []
    criteria_absent: list[str] = []
    missing: list[str] = []

    def _diag_contains(*keywords: str) -> bool | None:
        for d in record.diagnoses:
            text = d.description.lower()
            if any(k in text for k in keywords):
                return True
        return False  # absence of evidence is not missing when we have diagnoses

    def _med_contains(*keywords: str) -> bool | None:
        for m in record.medications:
            if any(k in m.name.lower() for k in keywords):
                return True
        return False

    def _lab(name: str) -> float | None:
        for lab in record.labs:
            if lab.test_name.upper() == name.upper():
                return lab.value
        return None

    # ── 1. High-risk surgery ─────────────────────────────────────────────────
    # Assessed at the plan level; not derivable from patient record alone.
    # The caller may override by passing `high_risk_surgery=True`.
    # We mark it as missing unless diagnoses hint at the surgery type.
    high_risk_surg = False
    high_risk_keywords = [
        "suprainguinal", "intraabdominal", "intrathoracic",
        "aortic", "major vascular", "bowel resection", "whipple",
        "hepatectomy", "pneumonectomy", "esophagectomy",
    ]
    for proc in getattr(record, "procedures", []):
        if any(k in proc.name.lower() for k in high_risk_keywords):
            high_risk_surg = True
            break

    if high_risk_surg:
        criteria_met.append("High-risk surgery (suprainguinal vascular/intraabdominal/intrathoracic)")
    else:
        missing.append("Surgery type not determinable from record — manually confirm high-risk surgery")

    # ── 2. Ischaemic heart disease ───────────────────────────────────────────
    ihd_keywords = [
        "coronary artery disease", "cad", "ischemic heart", "ischaemic heart",
        "myocardial infarction", "mi ", "angina", "stent",
        "coronary artery bypass", "cabg", "ptca",
    ]
    has_cardiac = record.cardiac
    ihd_from_diag = _diag_contains(*ihd_keywords)
    ihd_from_cardiac = any(
        c.has_history_mi or c.has_stents for c in (has_cardiac or [])
    )

    if ihd_from_diag or ihd_from_cardiac:
        criteria_met.append("Ischaemic heart disease (CAD / prior MI / stents)")
    else:
        criteria_absent.append("No ischaemic heart disease found")

    # ── 3. Congestive heart failure ──────────────────────────────────────────
    chf_keywords = [
        "congestive heart failure", "chf", "heart failure", "cardiac failure",
        "reduced ejection fraction", "hfref", "hfpef",
        "nyha", "cardiomyopathy",
    ]
    chf_from_diag = _diag_contains(*chf_keywords)
    # EF < 40% as a proxy
    ef = next((c.ejection_fraction_pct for c in (has_cardiac or []) if c.ejection_fraction_pct is not None), None)
    chf_from_ef = ef is not None and ef < 40.0

    if chf_from_diag or chf_from_ef:
        criteria_met.append(
            f"Congestive heart failure"
            + (f" (EF {ef:.0f}%)" if chf_from_ef else "")
        )
    else:
        criteria_absent.append("No congestive heart failure found")

    # ── 4. Cerebrovascular disease ───────────────────────────────────────────
    cvd_keywords = [
        "stroke", "tia", "transient ischemic attack", "cerebrovascular",
        "carotid stenosis", "cva",
    ]
    if _diag_contains(*cvd_keywords):
        criteria_met.append("Cerebrovascular disease (stroke / TIA)")
    else:
        criteria_absent.append("No cerebrovascular disease found")

    # ── 5. Insulin-dependent diabetes mellitus ───────────────────────────────
    dm_keywords = ["insulin-dependent diabetes", "type 1 diabetes", "iddm"]
    insulin_med = any(
        "insulin" in m.name.lower() for m in record.medications
    )
    dm_from_diag = _diag_contains(*dm_keywords)

    if dm_from_diag or insulin_med:
        criteria_met.append("Insulin-dependent diabetes mellitus")
    else:
        criteria_absent.append("No insulin-dependent DM found")

    # ── 6. Pre-operative creatinine > 2.0 mg/dL ─────────────────────────────
    cr = _lab("creatinine")
    if cr is not None:
        if cr > 2.0:
            criteria_met.append(f"Pre-operative creatinine > 2.0 mg/dL (found: {cr:.2f})")
        else:
            criteria_absent.append(f"Creatinine ≤ 2.0 mg/dL ({cr:.2f})")
    else:
        missing.append("Creatinine not found in labs — cannot assess criterion 6")

    score = len(criteria_met)
    mace_pct = _MACE_RISK.get(min(score, 3), 5.4)

    if score == 0:
        label = "low"
    elif score <= 2:
        label = "intermediate"
    else:
        label = "high"

    return RCRIResult(
        score=score,
        criteria_met=criteria_met,
        criteria_absent=criteria_absent,
        mace_risk_pct=mace_pct,
        risk_label=label,
        missing_data=missing,
    )
