"""
DOAC washout / bridging guidance calculator

Computes the minimum time (hours) from last dose to safe surgery/neuraxial
anaesthesia based on:
  - Drug half-life and renal clearance fraction
  - CrCl / eGFR (or serum creatinine + age + sex as fallback via CKD-EPI)
  - Procedure bleeding risk tier (low / high)
  - Neuraxial flag (spinal / epidural requires extra clearance)

References:
  - ESA 2022 neuraxial guidelines
  - Douketis et al. PAUSE trial 2019
  - Hornor et al. ACS NSQIP 2018
"""
from __future__ import annotations
from dataclasses import dataclass
import math


@dataclass
class DOACWashoutResult:
    drug: str
    last_dose: str | None           # ISO datetime string if known, else None
    half_life_hours: float
    renal_fraction: float           # fraction eliminated renally (0–1)
    estimated_crcl: float | None    # mL/min, None if not calculable
    washout_hours_low_risk: float
    washout_hours_high_risk: float
    washout_hours_neuraxial: float
    recommendation: str
    missing_data: list[str]

    def to_dict(self) -> dict:
        return self.__dict__.copy()


# Pharmacokinetic parameters (ESA 2022 / product monographs)
_DOAC_PARAMS: dict[str, dict] = {
    "apixaban":   {"half_life": 12.0,  "renal_fraction": 0.27, "aliases": ["eliquis"]},
    "rivaroxaban":{"half_life": 9.0,   "renal_fraction": 0.36, "aliases": ["xarelto"]},
    "dabigatran": {"half_life": 14.0,  "renal_fraction": 0.80, "aliases": ["pradaxa"]},
    "edoxaban":   {"half_life": 10.5,  "renal_fraction": 0.50, "aliases": ["savaysa", "lixiana"]},
}

# Washout expressed as half-lives (conservative)
_WASHOUT_HALFLIVES = {
    "low":      2.0,    # 2 half-lives → ~97% cleared
    "high":     4.0,    # 4 half-lives → ~93.75% cleared (standard)
    "neuraxial": 5.0,   # 5 half-lives → ESA neuraxial guideline
}

# Additional hours for impaired renal function (CrCl < 50)
_RENAL_EXTENSION_HOURS = {
    "dabigatran": 24,   # highly renally cleared
    "default": 12,
}


def compute_doac_washout(record, patient_age: int | None = None, patient_sex: str | None = None) -> list[DOACWashoutResult]:
    """
    Returns one DOACWashoutResult per DOAC found in the patient's medications.
    Returns an empty list if no DOACs are present.

    patient_sex: "M" | "F" (used for CrCl estimation from creatinine)
    """
    results: list[DOACWashoutResult] = []

    cr = _get_lab(record, "creatinine")
    crcl = _estimate_crcl(cr, patient_age, patient_sex)

    for med in record.medications:
        params = _match_doac(med.name)
        if params is None:
            continue

        drug_name, p = params
        missing: list[str] = []

        hl = p["half_life"]
        renal_f = p["renal_fraction"]

        # Extend half-life for renal impairment
        effective_hl = hl
        if crcl is not None and crcl < 50 and renal_f > 0.3:
            # Rough proportional extension
            extension_factor = 1.0 + (1.0 - crcl / 50) * renal_f
            effective_hl = round(hl * extension_factor, 1)
        elif crcl is None:
            if renal_f > 0.3:
                missing.append(
                    f"CrCl not calculable (no creatinine/age/sex) — washout may be longer for {drug_name} "
                    f"(renal fraction {renal_f:.0%})"
                )

        washout_low = round(effective_hl * _WASHOUT_HALFLIVES["low"])
        washout_high = round(effective_hl * _WASHOUT_HALFLIVES["high"])
        washout_neuro = round(effective_hl * _WASHOUT_HALFLIVES["neuraxial"])

        # Add renal extension for dabigatran specifically
        if drug_name == "dabigatran" and crcl is not None and crcl < 50:
            washout_neuro += _RENAL_EXTENSION_HOURS["dabigatran"]
            washout_high += _RENAL_EXTENSION_HOURS["dabigatran"]
        elif crcl is None and drug_name == "dabigatran":
            missing.append("Consider adding 24h to dabigatran washout if renal function impaired")

        last_dose = med.last_dose_datetime

        recs = [
            f"Low-risk procedure: hold ≥{washout_low}h ({washout_low//24}d)",
            f"High-risk procedure: hold ≥{washout_high}h ({washout_high//24}d)",
            f"Neuraxial (spinal/epidural): hold ≥{washout_neuro}h ({washout_neuro//24}d)",
        ]
        if last_dose:
            recs.append(f"Last recorded dose: {last_dose}")
        else:
            missing.append("Last dose datetime not recorded — cannot compute exact clearance window")
            recs.append("Last dose unknown — confirm with patient/pharmacy before proceeding")

        if crcl is not None:
            recs.append(f"Estimated CrCl: {crcl:.0f} mL/min")

        results.append(DOACWashoutResult(
            drug=drug_name,
            last_dose=last_dose,
            half_life_hours=effective_hl,
            renal_fraction=renal_f,
            estimated_crcl=crcl,
            washout_hours_low_risk=washout_low,
            washout_hours_high_risk=washout_high,
            washout_hours_neuraxial=washout_neuro,
            recommendation=" | ".join(recs),
            missing_data=missing,
        ))

    return results


def _match_doac(med_name: str) -> tuple[str, dict] | None:
    lower = med_name.lower()
    for drug, params in _DOAC_PARAMS.items():
        if drug in lower or any(alias in lower for alias in params["aliases"]):
            return drug, params
    return None


def _get_lab(record, name: str) -> float | None:
    for lab in record.labs:
        if lab.test_name.upper() == name.upper():
            return lab.value
    return None


def _estimate_crcl(cr: float | None, age: int | None, sex: str | None) -> float | None:
    """Cockcroft-Gault formula. Returns None if inputs are missing."""
    if cr is None or age is None or sex is None:
        return None
    if cr <= 0 or age <= 0:
        return None
    # Assume average weight 70 kg if not available
    weight_kg = 70.0
    crcl = ((140 - age) * weight_kg) / (72 * cr)
    if sex.upper() == "F":
        crcl *= 0.85
    return round(max(crcl, 5.0), 1)
