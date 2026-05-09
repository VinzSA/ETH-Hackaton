"""
Risk summary: runs all four risk calculators and returns a unified report.
"""
from __future__ import annotations
from dataclasses import dataclass, field

from .rcri import compute_rcri, RCRIResult
from .hasbled import compute_hasbled, HASBLEDResult
from .asa_estimator import estimate_asa, ASAResult
from .doac_washout import compute_doac_washout, DOACWashoutResult


@dataclass
class RiskSummary:
    rcri: RCRIResult
    hasbled: HASBLEDResult
    asa: ASAResult
    doac_washout: list[DOACWashoutResult]
    overall_risk_label: str          # "low" | "intermediate" | "high" | "critical"
    headline_warnings: list[str]     # top 3 action items for the anaesthesiologist

    def to_dict(self) -> dict:
        return {
            "rcri": self.rcri.to_dict(),
            "hasbled": self.hasbled.to_dict(),
            "asa": self.asa.to_dict(),
            "doac_washout": [d.to_dict() for d in self.doac_washout],
            "overall_risk_label": self.overall_risk_label,
            "headline_warnings": self.headline_warnings,
        }


def compute_risk_summary(
    record,
    patient_age: int | None = None,
    patient_sex: str | None = None,
) -> RiskSummary:
    rcri = compute_rcri(record)
    hasbled = compute_hasbled(record, patient_age=patient_age)
    asa = estimate_asa(record, patient_age=patient_age)
    doac = compute_doac_washout(record, patient_age=patient_age, patient_sex=patient_sex)

    # Derive overall risk label
    risk_votes: list[str] = [rcri.risk_label, hasbled.risk_label]
    if asa.estimated_class >= 4:
        risk_votes.append("high")
    elif asa.estimated_class == 3:
        risk_votes.append("intermediate")
    else:
        risk_votes.append("low")

    if "high" in risk_votes:
        overall = "high"
    elif "intermediate" in risk_votes:
        overall = "intermediate"
    else:
        overall = "low"

    # Override to critical if ASA IV/V
    if asa.estimated_class >= 4:
        overall = "critical"

    # Build top-3 headline warnings
    warnings: list[str] = []

    if rcri.score >= 3:
        warnings.append(
            f"RCRI {rcri.score}/6 — estimated MACE risk {rcri.mace_risk_pct:.1f}%; "
            f"consider cardiology referral"
        )
    elif rcri.score == 2:
        warnings.append(
            f"RCRI {rcri.score}/6 — estimated MACE risk {rcri.mace_risk_pct:.1f}% (intermediate)"
        )

    if hasbled.score >= 3:
        warnings.append(
            f"HAS-BLED {hasbled.score} — high bleeding risk ({hasbled.bleed_risk_pct:.0f}%/year); "
            f"weigh anticoagulation carefully"
        )

    if asa.estimated_class >= 3:
        top_reason = asa.upgrades_applied[0] if asa.upgrades_applied else "see rationale"
        warnings.append(f"ASA {asa.estimated_class}E/IV — {top_reason}")

    for d in doac:
        warnings.append(
            f"DOAC ({d.drug}): neuraxial hold ≥{d.washout_hours_neuraxial:.0f}h "
            f"({d.washout_hours_neuraxial//24:.0f}d); last dose {d.last_dose or 'unknown'}"
        )

    # Surface RCRI missing data warnings
    for m in rcri.missing_data[:2]:
        warnings.append(f"RCRI gap: {m}")

    return RiskSummary(
        rcri=rcri,
        hasbled=hasbled,
        asa=asa,
        doac_washout=doac,
        overall_risk_label=overall,
        headline_warnings=warnings[:6],
    )
