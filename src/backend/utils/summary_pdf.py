"""
Patient-summary PDF builder.

Renders a single A4 page with the mandatory demographics block, the verdict, and
a curated set of clinical findings drawn from the merged record. Uses PyMuPDF
(already a dependency for PDF ingestion) — no extra wheel required.
"""
from __future__ import annotations
from datetime import datetime
import io

import fitz  # PyMuPDF


_PAGE_W, _PAGE_H = 595.0, 842.0     # A4 in points
_MARGIN_X = 48.0
_TEXT_COLOR = (0.12, 0.14, 0.18)
_MUTED      = (0.45, 0.49, 0.55)
_ACCENT     = (0.18, 0.45, 0.85)
_GREEN      = (0.18, 0.55, 0.32)
_RED        = (0.78, 0.18, 0.22)
_RULE       = (0.85, 0.87, 0.91)


def build_summary_pdf(
    patient: dict,
    verdict: dict,
    state: dict,
    risk: dict,
) -> bytes:
    """
    Returns the rendered PDF bytes. Inputs are the same dicts the API hands to
    the frontend, so the PDF and the screen show the same numbers.
    """
    doc = fitz.open()
    page = doc.new_page(width=_PAGE_W, height=_PAGE_H)
    cursor = _MARGIN_X + 4

    cursor = _draw_header(page, cursor, patient)
    cursor = _draw_verdict(page, cursor, verdict)
    cursor = _draw_demographics(page, cursor, patient)
    cursor = _draw_section_title(page, cursor, "Clinical findings")
    cursor = _draw_findings(page, cursor, state)
    cursor = _draw_section_title(page, cursor, "Risk scores")
    cursor = _draw_risk_scores(page, cursor, risk)
    cursor = _draw_section_title(page, cursor, "Cautions for the anaesthesiologist")
    _draw_cautions(page, cursor, verdict)
    _draw_footer(page)

    out = io.BytesIO()
    doc.save(out)
    doc.close()
    return out.getvalue()


# ── Section renderers ────────────────────────────────────────────────────────

def _draw_header(page, y: float, patient: dict) -> float:
    name = patient.get("name") or "Unknown patient"
    page.insert_text((_MARGIN_X, y + 14), "ANESTHESIA PRE-OP SUMMARY", color=_ACCENT, fontsize=10, fontname="helv")
    page.insert_text((_MARGIN_X, y + 36), name, color=_TEXT_COLOR, fontsize=20, fontname="hebo")
    sub = _patient_subtitle(patient)
    if sub:
        page.insert_text((_MARGIN_X, y + 54), sub, color=_MUTED, fontsize=10, fontname="helv")
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    page.insert_text(
        (_PAGE_W - _MARGIN_X - 130, y + 14),
        f"Generated {stamp}", color=_MUTED, fontsize=9, fontname="helv",
    )
    return _hr(page, y + 74)


def _draw_verdict(page, y: float, verdict: dict) -> float:
    label = verdict.get("label", "NOT OK")
    color = _GREEN if label == "OK" else _RED
    headline = verdict.get("headline", "")
    confidence = verdict.get("confidence_pct", 0)
    threshold = verdict.get("threshold_pct", 70)
    subtitle = verdict.get("subtitle", "")

    box_h = 78
    rect = fitz.Rect(_MARGIN_X, y, _PAGE_W - _MARGIN_X, y + box_h)
    page.draw_rect(rect, color=color, fill=color, fill_opacity=0.10, width=0.6)
    page.insert_text((_MARGIN_X + 14, y + 22), f"VERDICT: {label}", color=color, fontsize=14, fontname="hebo")
    page.insert_text((_MARGIN_X + 14, y + 40), headline, color=_TEXT_COLOR, fontsize=11, fontname="helv")
    _wrap_text(page, _MARGIN_X + 14, y + 56, _PAGE_W - 2 * _MARGIN_X - 130, subtitle, fontsize=9, color=_MUTED)
    page.insert_text(
        (_PAGE_W - _MARGIN_X - 86, y + 28),
        f"{confidence}%", color=color, fontsize=24, fontname="hebo",
    )
    page.insert_text(
        (_PAGE_W - _MARGIN_X - 92, y + 46),
        f"confidence (≥{threshold}% to proceed)", color=_MUTED, fontsize=8, fontname="helv",
    )
    return y + box_h + 14


def _draw_demographics(page, y: float, patient: dict) -> float:
    rows = [
        ("Name",       patient.get("name", "—")),
        ("Age",        str(patient.get("age", "—"))),
        ("Sex",        patient.get("sex", "—")),
        ("Blood type", patient.get("blood_type", "Unknown")),
        ("Surgery",    patient.get("surgery_type", "—")),
        ("Urgency",    patient.get("urgency", "—")),
        ("Allergies",  patient.get("allergies_summary", "None on record")),
        ("Patient ID", patient.get("id", "—")),
    ]
    col_w = (_PAGE_W - 2 * _MARGIN_X) / 2
    page.insert_text((_MARGIN_X, y + 4), "Patient details", color=_TEXT_COLOR, fontsize=11, fontname="hebo")
    y += 18
    for i, (k, v) in enumerate(rows):
        col = i % 2
        row = i // 2
        x = _MARGIN_X + col * col_w
        ry = y + row * 22
        page.insert_text((x, ry + 8),  k, color=_MUTED,      fontsize=8,  fontname="helv")
        page.insert_text((x, ry + 20), str(v), color=_TEXT_COLOR, fontsize=11, fontname="hebo")
    return _hr(page, y + (len(rows) + 1) // 2 * 22 + 12)


def _draw_section_title(page, y: float, title: str) -> float:
    page.insert_text((_MARGIN_X, y + 4), title.upper(), color=_ACCENT, fontsize=9, fontname="hebo")
    return y + 16


def _draw_findings(page, y: float, state: dict) -> float:
    bullets: list[str] = []
    for a in state.get("allergies", [])[:5]:
        reaction = a.get("reaction")
        suffix = f" ({reaction})" if reaction else ""
        bullets.append(f"Allergy — {a['substance']}{suffix}")
    for ac in state.get("anticoagulants", [])[:5]:
        hours = ac.get("last_dose_hours_ago")
        suffix = f" — last dose ~{hours}h ago" if hours is not None else " — last dose unknown"
        bullets.append(f"Anticoagulant — {ac['drug']}{suffix}")
    for m in state.get("current_medications", [])[:5]:
        bullets.append(f"Medication — {m['drug']} {m.get('dose', '')}".strip())
    for af in state.get("airway_flags", [])[:3]:
        bullets.append(f"Airway flag — {af['flag']}")
    for d in state.get("implants_or_devices", [])[:3]:
        bullets.append(f"Device — {d['device']}")
    for lab in state.get("labs", [])[:6]:
        bullets.append(f"Lab — {lab['test']} {lab['value']} {lab['unit']}")
    for c in state.get("cardiac_risks", [])[:3]:
        bullets.append(f"Cardiac — {c['condition']}")
    for p in state.get("pulmonary_risks", [])[:3]:
        bullets.append(f"Pulmonary — {p['condition']}")
    if not bullets:
        bullets = ["No structured clinical findings extracted."]
    return _draw_bullets(page, y, bullets)


def _draw_risk_scores(page, y: float, risk: dict) -> float:
    rcri = risk.get("rcri", {})
    hb   = risk.get("hasbled", {})
    asa  = risk.get("asa", {})
    bullets = [
        f"RCRI score {rcri.get('score', '?')}/6 — {rcri.get('risk_label', '?')} ({rcri.get('mace_risk_pct', 0)}% MACE)",
        f"HAS-BLED {hb.get('score', '?')} — {hb.get('risk_label', '?')} ({hb.get('bleed_risk_pct', 0)}%/yr bleed)",
        f"ASA estimated class {asa.get('estimated_class', '?')}",
    ]
    return _draw_bullets(page, y, bullets)


def _draw_cautions(page, y: float, verdict: dict) -> float:
    cautions = verdict.get("cautions", [])
    if not cautions:
        return _draw_bullets(page, y, ["No primary cautions recorded."])
    bullets = [f"{c['title']} — {c['detail']}" for c in cautions]
    return _draw_bullets(page, y, bullets)


def _draw_footer(page) -> None:
    msg = (
        "Decision-support only. Output requires independent clinician verification "
        "before any anesthesia or surgical action."
    )
    page.insert_text((_MARGIN_X, _PAGE_H - 36), msg, color=_MUTED, fontsize=8, fontname="helv")


# ── Layout primitives ────────────────────────────────────────────────────────

def _hr(page, y: float) -> float:
    page.draw_line((_MARGIN_X, y), (_PAGE_W - _MARGIN_X, y), color=_RULE, width=0.6)
    return y + 14


def _draw_bullets(page, y: float, bullets: list[str]) -> float:
    for b in bullets:
        page.insert_text((_MARGIN_X, y + 10), "•", color=_ACCENT, fontsize=11, fontname="hebo")
        used = _wrap_text(page, _MARGIN_X + 12, y + 10, _PAGE_W - 2 * _MARGIN_X - 12, b, fontsize=10, color=_TEXT_COLOR)
        y += max(14.0, used)
    return y + 6


def _wrap_text(page, x: float, y: float, max_w: float, text: str, *, fontsize: float, color) -> float:
    """Very small word-wrap on the rendered page. Returns total height used."""
    if not text:
        return 0
    charw = fontsize * 0.5
    cols = max(20, int(max_w / charw))
    words = text.split()
    line = ""
    line_h = fontsize + 3
    used = 0
    for w in words:
        candidate = (line + " " + w).strip()
        if len(candidate) > cols and line:
            page.insert_text((x, y + used), line, color=color, fontsize=fontsize, fontname="helv")
            used += line_h
            line = w
        else:
            line = candidate
    if line:
        page.insert_text((x, y + used), line, color=color, fontsize=fontsize, fontname="helv")
        used += line_h
    return used


def _patient_subtitle(p: dict) -> str:
    parts: list[str] = []
    if p.get("age") is not None and p.get("sex"):
        parts.append(f"{p['age']}{p['sex']}")
    if p.get("surgery_type"):
        parts.append(str(p["surgery_type"]))
    if p.get("urgency"):
        parts.append(str(p["urgency"]).upper())
    return "  ·  ".join(parts)
