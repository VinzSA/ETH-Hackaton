"""
Verdict engine.

Aggregates the structured pre-anesthesia state and the existing risk scorers
(RCRI, HAS-BLED, ASA, DOAC washout) into a single GO / NO-GO decision plus a
calibrated confidence percentage.

Output shape (JSON-serialisable) is what the frontend renders directly:
    {
        "label": "OK" | "NOT OK",
        "headline": "Cleared for anesthesia" | "Hold for anesthesia review",
        "subtitle": "<one-line clinical context>",
        "confidence_pct": 0..100,
        "threshold_pct": int (default 70),
        "score": 0..1,                    # raw probability of safe proceed
        "cautions":       [Factor, ...],  # 3 most important contributors
        "important_info": [Factor, ...],  # next 3 contributors
        "all_factors":    [Factor, ...],  # full ranked list
    }
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict


@dataclass
class Factor:
    title: str            # short label e.g. "Active anticoagulation"
    detail: str           # 1-line clinical explanation
    weight: float         # how much this factor contributed to the verdict (0..1)
    direction: str        # "block" — pushes toward NOT OK; "support" — toward OK
    severity: str         # "critical" | "high" | "moderate" | "info"
    source_ids: list[str] = field(default_factory=list)
    source_snippet: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


# Per-factor blocking weights — calibrated so ≥1 critical block drops confidence
# below the 70% green threshold and ≥2 highs do the same.
_W_CRITICAL = 0.45
_W_HIGH     = 0.20
_W_MODERATE = 0.08
_W_INFO     = 0.03


def _severity_weight(sev: str) -> float:
    return {
        "critical": _W_CRITICAL,
        "high":     _W_HIGH,
        "moderate": _W_MODERATE,
        "info":     _W_INFO,
    }.get(sev, _W_INFO)


def compute_verdict(
    state: dict,
    risk: dict,
    surgery_type: str | None = None,
    threshold_pct: int = 70,
) -> dict:
    """
    Build the verdict from the already-computed PreAnesthesiaState and the risk
    summary. Pure function — no I/O, no hidden state — so the frontend is fully
    deterministic given the same inputs.
    """
    factors: list[Factor] = []

    # ── Anticoagulation (always blocks neuraxial, often the critical factor) ──
    for ac in state.get("anticoagulants", []):
        hours = ac.get("last_dose_hours_ago")
        if hours is None:
            detail = (
                f"{ac['drug']} — last dose unknown. Neuraxial likely contraindicated until clarified."
            )
            severity = "critical"
        elif hours < 24:
            detail = f"{ac['drug']} taken ~{hours}h ago — within active anticoagulation window."
            severity = "critical"
        else:
            detail = f"{ac['drug']} on board (~{hours}h since last dose) — washout in progress."
            severity = "high"
        factors.append(Factor(
            title=f"Active anticoagulation — {ac['drug']}",
            detail=detail,
            weight=_severity_weight(severity),
            direction="block",
            severity=severity,
            source_ids=[ac.get("source_id")] if ac.get("source_id") else [],
            source_snippet=ac.get("source_snippet"),
        ))

    # ── Hyperkalemia (succinylcholine contraindication) ──
    for lab in state.get("labs", []):
        if lab["test"] == "potassium" and lab["value"] > 5.5:
            sev = "critical" if lab["value"] > 6.0 else "high"
            factors.append(Factor(
                title=f"Hyperkalemia — K+ {lab['value']} {lab['unit']}",
                detail="Risk of life-threatening potassium spike with succinylcholine.",
                weight=_severity_weight(sev),
                direction="block",
                severity=sev,
                source_ids=[lab["source_id"]],
                source_snippet=lab.get("source_snippet"),
            ))
        if lab["test"] == "creatinine" and lab["value"] > 2.0:
            factors.append(Factor(
                title=f"Renal impairment — Cr {lab['value']} {lab['unit']}",
                detail="Reduced clearance affects induction dose and reversal choices.",
                weight=_severity_weight("high"),
                direction="block",
                severity="high",
                source_ids=[lab["source_id"]],
                source_snippet=lab.get("source_snippet"),
            ))
        elif lab["test"] == "creatinine" and lab["value"] > 1.5:
            factors.append(Factor(
                title=f"Mild renal impairment — Cr {lab['value']} {lab['unit']}",
                detail="Adjust renally-cleared drugs; not a hard stop.",
                weight=_severity_weight("moderate"),
                direction="block",
                severity="moderate",
                source_ids=[lab["source_id"]],
                source_snippet=lab.get("source_snippet"),
            ))

    # ── Difficult airway flags ──
    for af in state.get("airway_flags", []):
        factors.append(Factor(
            title="Difficult airway",
            detail=af["flag"],
            weight=_severity_weight("high"),
            direction="block",
            severity="high",
            source_ids=[af["source_id"]],
            source_snippet=af.get("source_snippet"),
        ))

    # ── Cardiac implants ──
    for d in state.get("implants_or_devices", []):
        if any(k in d["device"].lower() for k in ["pacemaker", "defibrillator", "icd"]):
            factors.append(Factor(
                title=f"{d['device']}",
                detail="Magnet protocol & bipolar cautery required; confirm recent interrogation.",
                weight=_severity_weight("moderate"),
                direction="block",
                severity="moderate",
                source_ids=[d["source_id"]],
                source_snippet=d.get("source_snippet"),
            ))

    # ── Allergies (high-impact ones) ──
    for al in state.get("allergies", []):
        if any(k in al["substance"].lower() for k in ["penicillin", "latex", "succinyl", "rocuron"]):
            factors.append(Factor(
                title=f"{al['substance'].title()} allergy",
                detail=f"Reaction: {al.get('reaction') or 'unspecified'}. Avoid related drugs.",
                weight=_severity_weight("moderate"),
                direction="block",
                severity="moderate",
                source_ids=[al["source_id"]],
                source_snippet=al.get("source_snippet"),
            ))

    # ── Pulmonary risks ──
    for p in state.get("pulmonary_risks", []):
        factors.append(Factor(
            title=p["condition"],
            detail="Plan postop pulmonary toilet; consider regional vs general.",
            weight=_severity_weight("moderate"),
            direction="block",
            severity="moderate",
            source_ids=[p["source_id"]],
            source_snippet=p.get("source_snippet"),
        ))

    # ── Existing risk scores (RCRI / HAS-BLED / ASA / DOAC) ──
    rcri = risk.get("rcri", {})
    if rcri.get("risk_label") == "high":
        factors.append(Factor(
            title=f"Cardiac risk RCRI {rcri.get('score', 0)}/6",
            detail=f"Estimated MACE {rcri.get('mace_risk_pct', 0):.1f}% — cardiology referral suggested.",
            weight=_severity_weight("high"),
            direction="block",
            severity="high",
        ))
    elif rcri.get("risk_label") == "intermediate":
        factors.append(Factor(
            title=f"Cardiac risk RCRI {rcri.get('score', 0)}/6",
            detail=f"Intermediate cardiac risk (MACE {rcri.get('mace_risk_pct', 0):.1f}%).",
            weight=_severity_weight("moderate"),
            direction="block",
            severity="moderate",
        ))

    hb = risk.get("hasbled", {})
    if hb.get("score", 0) >= 3:
        factors.append(Factor(
            title=f"Bleeding risk HAS-BLED {hb['score']}",
            detail=f"Estimated annual bleed {hb.get('bleed_risk_pct', 0):.0f}% — escalate caution.",
            weight=_severity_weight("high"),
            direction="block",
            severity="high",
        ))

    asa = risk.get("asa", {})
    asa_class = asa.get("estimated_class", 1)
    if asa_class >= 4:
        factors.append(Factor(
            title=f"ASA class {asa_class}",
            detail="Severe systemic disease — anaesthesiologist senior review required.",
            weight=_severity_weight("critical"),
            direction="block",
            severity="critical",
        ))
    elif asa_class == 3:
        factors.append(Factor(
            title=f"ASA class {asa_class}",
            detail="Severe but not life-threatening systemic disease.",
            weight=_severity_weight("moderate"),
            direction="block",
            severity="moderate",
        ))

    for d in risk.get("doac_washout", []) or []:
        hold = d.get("washout_hours_neuraxial", 0)
        factors.append(Factor(
            title=f"DOAC washout — {d.get('drug', 'agent')}",
            detail=f"Required neuraxial hold ≥ {hold:.0f}h before regional anesthesia.",
            weight=_severity_weight("high"),
            direction="block",
            severity="high",
        ))

    # ── Surgery-type weighting ──
    if surgery_type:
        st = surgery_type.lower()
        if any(k in st for k in ["cardiac", "thoracic", "aortic", "vascular major"]):
            factors.append(Factor(
                title=f"High-risk surgery — {surgery_type}",
                detail="Surgery class is itself an independent risk factor.",
                weight=_severity_weight("high"),
                direction="block",
                severity="high",
            ))
        elif any(k in st for k in ["hip fracture", "emergent", "trauma"]):
            factors.append(Factor(
                title=f"Time-pressured surgery — {surgery_type}",
                detail="Limited window for risk optimisation; documents must be reconciled fast.",
                weight=_severity_weight("moderate"),
                direction="block",
                severity="moderate",
            ))

    # ── Compute confidence ──
    # Logistic combination of weighted blockers. Each blocker subtracts logits
    # from a base of ~3 (≈95% prior of safe proceed), so additional blockers
    # have diminishing marginal effect rather than zeroing the score.
    import math
    risk_pressure = sum(f.weight for f in factors if f.direction == "block")
    logit = 3.0 - 6.0 * risk_pressure
    score = 1.0 / (1.0 + math.exp(-logit))
    confidence_pct = int(round(score * 100))

    label = "OK" if confidence_pct >= threshold_pct else "NOT OK"

    if label == "OK":
        headline = "Anesthesia: cleared to proceed"
        subtitle = (
            "All hard stops cleared. "
            f"Confidence {confidence_pct}% (threshold {threshold_pct}%)."
        )
    else:
        # Take the most severe blocking factor and quote it in the subtitle
        worst = max(
            factors,
            key=lambda f: (f.weight if f.direction == "block" else 0),
            default=None,
        )
        subtitle = (
            "Hold and review with senior anaesthesiologist."
            if worst is None
            else f"Primary blocker: {worst.title.lower()}. {worst.detail}"
        )
        headline = "Anesthesia: hold for review"

    factors.sort(key=lambda f: -f.weight)
    cautions       = [f.to_dict() for f in factors[:3]]
    important_info = [f.to_dict() for f in factors[3:6]]
    all_factors    = [f.to_dict() for f in factors]

    return {
        "label": label,
        "headline": headline,
        "subtitle": subtitle,
        "confidence_pct": confidence_pct,
        "threshold_pct": threshold_pct,
        "score": round(score, 3),
        "cautions": cautions,
        "important_info": important_info,
        "all_factors": all_factors,
        "surgery_type": surgery_type,
    }
