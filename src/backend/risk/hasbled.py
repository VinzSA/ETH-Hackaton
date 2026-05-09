"""
HAS-BLED bleeding risk score (Pisters et al. 2010)

Used for anticoagulated AF patients to estimate major bleeding risk.
Each letter = 1 point (H can also score 2 for both systolic HT and poor BP control).

Letter  Criterion
H       Hypertension (uncontrolled SBP > 160)
A       Abnormal renal/liver function (1 point each)
S       Stroke history
B       Bleeding history or predisposition
L       Labile INR (time-in-range < 60%)
E       Elderly (age > 65)
D       Drugs (antiplatelets / NSAIDs) or alcohol (1 point each)

Score → major bleed / year
  0–1  → ~1%   low
  2    → ~2%   moderate
  ≥3   → ≥3%   high (warrants more frequent review, not necessarily no anticoagulation)
"""
from __future__ import annotations
from dataclasses import dataclass


@dataclass
class HASBLEDResult:
    score: int
    criteria_met: list[str]
    criteria_absent: list[str]
    bleed_risk_pct: float
    risk_label: str             # "low" | "moderate" | "high"
    missing_data: list[str]

    def to_dict(self) -> dict:
        return self.__dict__.copy()


_BLEED_RISK = {0: 1.0, 1: 1.0, 2: 2.0, 3: 3.0, 4: 4.0, 5: 5.0, 6: 6.0, 7: 7.0, 8: 8.0, 9: 9.0}


def compute_hasbled(record, patient_age: int | None = None) -> HASBLEDResult:
    """
    record: PatientRecord

    patient_age is not stored on PatientRecord by default — pass it explicitly
    if available. If None, the E criterion is marked as missing.
    """
    score = 0
    met: list[str] = []
    absent: list[str] = []
    missing: list[str] = []

    def _diag(*kw: str) -> bool:
        return any(any(k in d.description.lower() for k in kw) for d in record.diagnoses)

    def _med(*kw: str) -> bool:
        return any(any(k in m.name.lower() for k in kw) for m in record.medications)

    def _lab(name: str) -> float | None:
        for l in record.labs:
            if l.test_name.upper() == name.upper():
                return l.value
        return None

    # H — Hypertension (uncontrolled): SBP > 160 or hypertension diagnosis
    # We can check diagnoses; BP reading would require vital signs not in current schema
    has_htn = _diag("hypertension", "htn")
    sbp = None  # vital signs not modelled yet
    if has_htn:
        # Check for "uncontrolled" qualifier
        uncontrolled = _diag("uncontrolled hypertension", "resistant hypertension")
        if uncontrolled or sbp is not None and sbp > 160:
            score += 1
            met.append("H — Uncontrolled hypertension (SBP > 160 or documented)")
        else:
            absent.append("H — Hypertension present but appears controlled")
    else:
        absent.append("H — No hypertension found")

    # A — Abnormal renal function: dialysis, Cr > 2.26 mg/dL, renal transplant
    cr = _lab("creatinine")
    renal_diag = _diag("dialysis", "chronic kidney disease", "renal failure", "renal transplant",
                        "ckd", "end-stage renal")
    a_renal = (cr is not None and cr > 2.26) or renal_diag
    if a_renal:
        score += 1
        met.append(f"A — Abnormal renal function" + (f" (Cr {cr:.2f})" if cr else ""))
    else:
        absent.append("A (renal) — Renal function normal or not impaired")

    # A — Abnormal liver function: cirrhosis, bilirubin > 2x ULN, ALT/AST/ALP > 3x ULN
    liver_diag = _diag("cirrhosis", "liver failure", "hepatic failure", "liver disease")
    alt = _lab("alt") or _lab("alanine aminotransferase")
    ast = _lab("ast") or _lab("aspartate aminotransferase")
    bili = _lab("bilirubin") or _lab("total bilirubin")
    a_liver = liver_diag or (alt and alt > 120) or (ast and ast > 120) or (bili and bili > 2.0)
    if a_liver:
        score += 1
        met.append("A — Abnormal liver function (cirrhosis / elevated transaminases)")
    else:
        absent.append("A (liver) — Liver function normal or not impaired")

    # S — Stroke history
    if _diag("stroke", "tia", "transient ischemic attack", "cva", "cerebrovascular"):
        score += 1
        met.append("S — Prior stroke / TIA / cerebrovascular disease")
    else:
        absent.append("S — No stroke / TIA history")

    # B — Bleeding history or predisposition (anaemia, thrombocytopenia, bleeding diathesis)
    bleed_diag = _diag("gastrointestinal bleed", "gi bleed", "haemorrhage", "hemorrhage",
                       "bleeding disorder", "haemophilia", "hemophilia", "thrombocytopenia")
    hgb = _lab("hemoglobin") or _lab("haemoglobin") or _lab("hgb") or _lab("hb")
    plt = _lab("platelets") or _lab("plt") or _lab("thrombocytes")
    bleed_labs = (hgb is not None and hgb < 10.0) or (plt is not None and plt < 100)
    if bleed_diag or bleed_labs:
        score += 1
        met.append("B — Bleeding history or predisposition"
                   + (f" (Hgb {hgb:.1f} g/dL)" if hgb and hgb < 10 else "")
                   + (f" (Plt {plt:.0f}×10⁹/L)" if plt and plt < 100 else ""))
    else:
        absent.append("B — No bleeding history or predisposition")

    # L — Labile INR: TTR < 60%
    # We don't track TTR directly. Proxy: INR out of range for AF target (2–3)
    inr = _lab("inr")
    if inr is not None:
        on_warfarin = _med("warfarin", "coumadin", "acenocoumarol")
        if on_warfarin and (inr < 2.0 or inr > 3.5):
            score += 1
            met.append(f"L — Labile INR (INR {inr:.1f}, outside 2.0–3.0 target range)")
        else:
            absent.append(f"L — INR {inr:.1f}, within or near target range")
    else:
        missing.append("L — INR not available; cannot assess labile INR criterion")

    # E — Elderly (> 65 years)
    if patient_age is not None:
        if patient_age > 65:
            score += 1
            met.append(f"E — Age > 65 ({patient_age} years)")
        else:
            absent.append(f"E — Age ≤ 65 ({patient_age} years)")
    else:
        missing.append("E — Patient age not available; cannot assess elderly criterion")

    # D — Antiplatelet drugs or NSAIDs
    antiplatelet = _med("aspirin", "clopidogrel", "ticagrelor", "prasugrel", "dipyridamole")
    nsaid = _med("ibuprofen", "naproxen", "diclofenac", "celecoxib", "indomethacin",
                 "ketorolac", "meloxicam", "piroxicam")
    if antiplatelet or nsaid:
        score += 1
        meds_found = []
        if antiplatelet:
            meds_found.append("antiplatelet")
        if nsaid:
            meds_found.append("NSAID")
        met.append(f"D — Drugs: {', '.join(meds_found)}")
    else:
        absent.append("D — No antiplatelet drugs or NSAIDs")

    # D — Alcohol (≥8 units/week) — rarely documented; check diagnoses
    if _diag("alcohol use disorder", "alcoholism", "alcohol dependence", "alcohol abuse",
             "harmful alcohol use"):
        score += 1
        met.append("D — Alcohol use disorder documented")
    else:
        absent.append("D (alcohol) — No alcohol use disorder documented")

    bleed_pct = _BLEED_RISK.get(min(score, 9), 9.0)

    if score <= 1:
        label = "low"
    elif score == 2:
        label = "moderate"
    else:
        label = "high"

    return HASBLEDResult(
        score=score,
        criteria_met=met,
        criteria_absent=absent,
        bleed_risk_pct=bleed_pct,
        risk_label=label,
        missing_data=missing,
    )
