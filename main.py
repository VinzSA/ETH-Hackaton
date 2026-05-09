"""
ER Pre-Op Brief — FastAPI backend.

Run (default port 8010 — avoids common conflicts on 8000):
  PORT=8010 uvicorn main:app --reload --port 8010
  # or: python main.py
"""
import asyncio
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from functools import partial

# Resolve imports: pipeline uses "from src.classifier..." where src/ is
# a self-referential symlink inside src/backend/ pointing to the same dir.
_BACKEND = os.path.join(os.path.dirname(__file__), "src", "backend")
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel

from ingestion.pipeline import process_patient
from validation.bayesian import score_patient_record
from risk.summary import compute_risk_summary
from risk.verdict import compute_verdict
from utils.summary_pdf import build_summary_pdf

# Thread pool for synchronous pipeline calls (process_patient uses asyncio.run
# internally and cannot be called directly from FastAPI's event loop).
_POOL = ThreadPoolExecutor(max_workers=4)


async def run_patient(*args, **kwargs):
    """Run process_patient in a thread so asyncio.run() inside it doesn't conflict."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_POOL, partial(process_patient, *args, **kwargs))

app = FastAPI(title="ER Pre-Op Brief API")

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# The same 6 documents used by demo.ts (demoDocuments array) so the demo
# endpoint produces results grounded in the same clinical case the UI shows.
DEMO_TEXTS = [
    (
        "ED Triage Note",
        "67-year-old male brought in after mechanical fall at home. Patient is confused, GCS 13, "
        "unable to provide reliable history. Past history per chart includes atrial fibrillation. "
        "Family reports a known penicillin allergy with rash.",
    ),
    (
        "Outpatient Medication List",
        "Active medications reconciled from pharmacy refill records. Apixaban 5 mg orally twice daily "
        "for atrial fibrillation; last documented dose at 18:00 the prior evening. Metoprolol succinate "
        "50 mg orally once daily. Atorvastatin 40 mg nightly.",
    ),
    (
        "Anesthesia Record 2022",
        "Prior difficult intubation documented during cholecystectomy in 2022, required video "
        "laryngoscopy and bougie. Postoperative nausea and vomiting noted in PACU. No malignant "
        "hyperthermia history reported.",
    ),
    (
        "Pulmonology Clinic Letter",
        "Patient followed for moderate COPD on tiotropium inhaler. Baseline oxygen saturation 93% "
        "on room air. No recent exacerbations. Smoking history 40 pack-years, quit 5 years ago.",
    ),
    (
        "Recent Laboratory Results",
        "Chronic kidney disease stage 3 documented on prior nephrology notes. Creatinine 1.9 mg/dL "
        "today, up from baseline 1.4. Potassium 5.8 mmol/L today, repeat pending. Hemoglobin 11.2 g/dL. "
        "No INR or coagulation panel resulted.",
    ),
    (
        "Cardiology Device Card",
        "Dual-chamber pacemaker implanted 2019 for sick sinus syndrome, Medtronic model. Last "
        "interrogation 4 months ago, normal function.",
    ),
]


def record_to_pre_anesthesia_state(
    record,
    doc_id_map: dict[str, int],
    *,
    id_offset: int = 0,
) -> dict:
    """Convert a PatientRecord dataclass to the PreAnesthesiaState TypeScript shape."""

    def sid(src_obj) -> str:
        idx = doc_id_map.get(src_obj.document_id, 0)
        return f"D{id_offset + idx + 1}:S1"

    def snip(src_obj) -> str:
        return src_obj.snippet or ""

    allergies = [
        {
            "substance": a.substance,
            "reaction": a.reaction,
            "severity": a.severity,
            "source_id": sid(a.source),
            "source_snippet": snip(a.source),
        }
        for a in record.allergies
    ]

    anticoagulants = [
        {
            "drug": m.name,
            "dose": m.dose,
            "frequency": m.frequency,
            "last_dose": m.last_dose_datetime,
            "source_id": sid(m.source),
            "source_snippet": snip(m.source),
        }
        for m in record.medications
        if m.is_anticoagulant
    ]

    current_medications = [
        {
            "drug": m.name,
            "dose": m.dose,
            "frequency": m.frequency,
            "source_id": sid(m.source),
            "source_snippet": snip(m.source),
        }
        for m in record.medications
        if not m.is_anticoagulant
    ]

    airway_flags = []
    prior_anesthesia_complications = []
    for ah in record.anesthesia_history:
        if ah.airway_notes:
            airway_flags.append({
                "flag": ah.airway_notes,
                "source_id": sid(ah.source),
                "source_snippet": snip(ah.source),
            })
        if ah.complications:
            prior_anesthesia_complications.append({
                "event": ah.complications,
                "source_id": sid(ah.source),
                "source_snippet": snip(ah.source),
            })

    cardiac_risks = []
    for c in record.cardiac:
        if c.has_atrial_fibrillation:
            cardiac_risks.append({"condition": "atrial fibrillation", "source_id": sid(c.source), "source_snippet": snip(c.source)})
        if c.has_history_mi:
            cardiac_risks.append({"condition": "prior myocardial infarction", "source_id": sid(c.source), "source_snippet": snip(c.source)})
        if c.has_stents:
            cardiac_risks.append({"condition": "coronary stent", "source_id": sid(c.source), "source_snippet": snip(c.source)})
        if c.nyha_class and c.nyha_class >= 3:
            cardiac_risks.append({"condition": f"NYHA class {c.nyha_class} heart failure", "source_id": sid(c.source), "source_snippet": snip(c.source)})

    pulmonary_kws = ["copd", "asthma", "pulmonary hypertension", "sleep apnea", "emphysema", "respiratory"]
    pulmonary_risks = [
        {"condition": d.description, "source_id": sid(d.source), "source_snippet": snip(d.source)}
        for d in record.diagnoses
        if any(kw in d.description.lower() for kw in pulmonary_kws)
    ]

    renal_kws = ["kidney", "ckd", "dialysis", "diabet", "renal", "metabolic", "hyperkalemia"]
    renal_metabolic_risks = [
        {"condition": d.description, "source_id": sid(d.source), "source_snippet": snip(d.source)}
        for d in record.diagnoses
        if any(kw in d.description.lower() for kw in renal_kws)
    ]

    labs = [
        {
            "test": lab.test_name,
            "value": lab.value,
            "unit": lab.unit,
            "source_id": sid(lab.source),
            "source_snippet": snip(lab.source),
        }
        for lab in record.labs
    ]

    implants_or_devices = [
        {"device": i.description, "source_id": sid(i.source), "source_snippet": snip(i.source)}
        for i in record.implants
    ]

    return {
        "allergies": allergies,
        "anticoagulants": anticoagulants,
        "current_medications": current_medications,
        "airway_flags": airway_flags,
        "prior_anesthesia_complications": prior_anesthesia_complications,
        "cardiac_risks": cardiac_risks,
        "pulmonary_risks": pulmonary_risks,
        "renal_metabolic_risks": renal_metabolic_risks,
        "labs": labs,
        "implants_or_devices": implants_or_devices,
    }


_DOC_TYPE_TITLE = {
    "discharge_summary": "Discharge summary",
    "operative_note": "Operative note",
    "anesthesia_record": "Anesthesia record",
    "cardiology_consult": "Cardiology consult",
    "lab_report": "Laboratory report",
    "medication_list": "Medication list",
    "unknown": "Clinical document",
}


def ui_documents_payload(
    record,
    doc_id_map: dict[str, int],
    *,
    id_offset: int = 0,
) -> list[dict]:
    """Per-document excerpt + title for the frontend (grounded citations)."""
    out: list[dict] = []
    for doc in getattr(record, "source_documents", None) or []:
        idx = doc_id_map.get(doc.document_id, 0)
        label = _DOC_TYPE_TITLE.get(
            doc.document_type,
            str(doc.document_type).replace("_", " ").title(),
        )
        date_part = doc.document_date
        title = f"{label} · {date_part}" if date_part else label
        body = (getattr(doc, "raw_text", None) or "").strip()
        out.append(
            {
                "id": f"D{id_offset + idx + 1}",
                "title": title,
                "text": body,
                "document_type": doc.document_type,
                "document_date": doc.document_date,
            }
        )
    out.sort(key=lambda d: int(d["id"][1:]))
    return out


def _api_bundle(
    record,
    *,
    id_offset: int = 0,
    patient: dict | None = None,
) -> dict:
    patient = patient or {}
    doc_id_map = {doc_id: i for i, doc_id in enumerate(record.document_timeline.keys())}
    state = record_to_pre_anesthesia_state(record, doc_id_map, id_offset=id_offset)
    conf = score_patient_record(record)

    # Patient-supplied age/sex always wins; fall back to text extraction.
    age = patient.get("age")
    sex = patient.get("sex")
    if age is None or sex is None:
        ext_age, ext_sex = _extract_age_sex(
            [d.raw_text or "" for d in (getattr(record, "source_documents", None) or [])]
        )
        age = age or ext_age
        sex = sex or ext_sex

    risk = compute_risk_summary(record, patient_age=age, patient_sex=sex)
    risk_dict = risk.to_dict()

    documents = ui_documents_payload(record, doc_id_map, id_offset=id_offset)
    validation = build_validation_steps(state, conf, risk, documents)
    verdict = compute_verdict(
        state,
        risk_dict,
        surgery_type=patient.get("surgery_type"),
        threshold_pct=int(patient.get("threshold_pct") or 70),
    )

    enriched_patient = {
        **patient,
        "age": age,
        "sex": sex,
        "allergies_summary": (
            ", ".join(a["substance"] for a in state["allergies"]) or "None on record"
        ),
        "id": patient.get("id") or record.patient_id,
    }

    return {
        "state": state,
        "warnings": record.warnings,
        "confidence": record.overall_confidence,
        "fact_confidence": conf.to_dict(),
        "risk_scores": risk_dict,
        "documents": documents,
        "validation_steps": validation,
        "verdict": verdict,
        "patient": enriched_patient,
    }


def build_validation_steps(state, conf, risk, documents):
    """Each step explains a check that ran and how it shifted the recommendation."""
    steps: list[dict] = []

    n_docs = len(documents)
    steps.append({
        "id": "ingest",
        "title": "Document ingestion",
        "status": "pass" if n_docs > 0 else "warn",
        "summary": (
            f"Read {n_docs} source document(s); each was classified, dated, and tokenised."
            if n_docs > 0
            else "No documents were ingested — no analysis possible."
        ),
        "impact": (
            f"Subsequent steps run against {n_docs} grounded text source(s)."
            if n_docs > 0
            else "Pipeline halted — output suppressed."
        ),
    })

    facts = (conf.to_dict() if hasattr(conf, "to_dict") else conf)["facts"]
    high = sum(1 for f in facts if f["posterior"] >= 0.85)
    mid = sum(1 for f in facts if 0.5 <= f["posterior"] < 0.85)
    low = sum(1 for f in facts if f["posterior"] < 0.5)
    bayes_status = "pass" if high > 0 else "warn" if mid > 0 else "info"
    steps.append({
        "id": "bayes",
        "title": "Bayesian fact validation",
        "status": bayes_status,
        "summary": (
            f"Cross-checked {len(facts)} extracted facts across documents using a "
            f"Bayes-odds update (LR_confirm=10, LR_contradict=0.3): "
            f"{high} high-confidence, {mid} medium, {low} low."
        ),
        "impact": (
            "Facts above the 0.85 posterior bar are surfaced in the headline plan; "
            "lower-confidence facts are demoted to the 'requires verification' list."
        ),
    })

    rcri = risk.rcri
    rcri_status = "pass" if rcri.risk_label == "low" else "warn" if rcri.risk_label == "intermediate" else "fail"
    steps.append({
        "id": "rcri",
        "title": "Cardiac risk (RCRI)",
        "status": rcri_status,
        "summary": (
            f"RCRI {rcri.score}/6 → MACE risk {rcri.mace_risk_pct:.1f}% ({rcri.risk_label}). "
            f"Met: {', '.join(rcri.criteria_met) or 'none'}."
        ),
        "impact": (
            f"Increased decision weight toward 'requires senior review'."
            if rcri.risk_label == "high"
            else f"Cautious posture but does not by itself block proceeding."
            if rcri.risk_label == "intermediate"
            else "No upward pressure on the cardiac risk axis."
        ),
    })

    hb = risk.hasbled
    hb_status = "pass" if hb.risk_label == "low" else "warn" if hb.risk_label == "moderate" else "fail"
    steps.append({
        "id": "hasbled",
        "title": "Bleeding risk (HAS-BLED)",
        "status": hb_status,
        "summary": (
            f"HAS-BLED {hb.score} → annual bleed risk {hb.bleed_risk_pct:.0f}% ({hb.risk_label}). "
            f"Drivers: {', '.join(hb.criteria_met) or 'none scored'}."
        ),
        "impact": (
            "Pushes the plan toward delaying neuraxial / verifying anticoagulation washout."
            if hb.score >= 3
            else "Adds bleed-monitoring guidance but does not delay the case."
        ),
    })

    asa = risk.asa
    asa_status = "pass" if asa.estimated_class <= 2 else "warn" if asa.estimated_class == 3 else "fail"
    steps.append({
        "id": "asa",
        "title": "ASA physical status",
        "status": asa_status,
        "summary": (
            f"Estimated ASA class {asa.estimated_class}. "
            f"Drivers: {', '.join(asa.upgrades_applied) if asa.upgrades_applied else 'baseline'}."
        ),
        "impact": (
            "Class IV/V triggers the 'critical risk' threshold; intra-op monitoring expanded."
            if asa.estimated_class >= 4
            else "Class III flags shared decision-making; procedure may still proceed with caution."
            if asa.estimated_class == 3
            else "Routine ASA does not modify the recommendation."
        ),
    })

    doac = risk.doac_washout
    if doac:
        worst = max(d.washout_hours_neuraxial for d in doac)
        steps.append({
            "id": "doac",
            "title": "DOAC washout window",
            "status": "fail" if worst >= 48 else "warn",
            "summary": (
                f"{len(doac)} anticoagulant(s) on board. "
                f"Required neuraxial hold: ≥{worst:.0f}h."
            ),
            "impact": (
                "Decision shifted to 'delay or reverse anticoagulation' until window clears."
            ),
        })
    else:
        steps.append({
            "id": "doac",
            "title": "DOAC washout window",
            "status": "pass",
            "summary": "No active anticoagulants found in extracted facts.",
            "impact": "No bleeding-driven delay applied.",
        })

    drug_safety: list[str] = []
    k = next((l for l in state["labs"] if l["test"] == "potassium"), None)
    if k and k["value"] > 5.5:
        drug_safety.append(f"Hyperkalemia (K+ {k['value']}) — succinylcholine excluded.")
    for a in state["allergies"]:
        drug_safety.append(f"{a['substance'].title()} allergy — related drugs avoided.")
    if state["airway_flags"]:
        drug_safety.append("Difficult airway flag — awake/video laryngoscopy planned.")
    if state["implants_or_devices"]:
        drug_safety.append("Implant/device on board — magnet & bipolar protocol.")

    steps.append({
        "id": "drug_safety",
        "title": "Drug & airway safety checks",
        "status": "fail" if drug_safety else "pass",
        "summary": "; ".join(drug_safety) if drug_safety else "No hard safety constraints triggered.",
        "impact": (
            "Each constraint added a 'drug to avoid' or contingency to the plan."
            if drug_safety
            else "Plan free to use standard induction agents."
        ),
    })

    return steps


def _extract_age_sex(texts: list[str]) -> tuple[int | None, str | None]:
    """Best-effort age and sex extraction from raw text for risk scoring."""
    import re
    age: int | None = None
    sex: str | None = None
    for text in texts:
        if age is None:
            m = re.search(r"(\d{1,3})[- ]?(?:year|yr)[- ]?old", text, re.I)
            if m:
                age = int(m.group(1))
        if sex is None:
            if re.search(r"\bmale\b|\bman\b|\bM\b", text):
                sex = "M"
            elif re.search(r"\bfemale\b|\bwoman\b|\bF\b", text):
                sex = "F"
        if age and sex:
            break
    return age, sex


class Patient(BaseModel):
    """Demographics & case context the user types into the upload form."""
    name: str | None = None
    age: int | None = None
    sex: str | None = None         # "M" | "F" | "X"
    blood_type: str | None = None
    surgery_type: str | None = None
    urgency: str | None = None
    threshold_pct: int | None = None
    id: str | None = None


class ExtractRequest(BaseModel):
    texts: list[str]
    patient: Patient | None = None
    patient_id: str | None = None


class DecideRequest(BaseModel):
    """Inline analysis (texts + JSON dicts) — used by the batch validator."""
    texts: list[str] = []
    json_records: list[dict] = []
    patient: Patient | None = None
    patient_id: str | None = None


def _patient_dict(p: Patient | None) -> dict:
    if not p:
        return {}
    return {k: v for k, v in p.model_dump().items() if v is not None}


def _json_to_text(payload) -> str:
    """Render a JSON record as a flat human-readable text block.

    The pipeline is text-first (Claude classifier + extractors), so the simplest
    reliable way to support arbitrary JSON inputs is to flatten them into a
    labelled text representation. This keeps every key/value addressable by the
    extractors and keeps citations consistent.
    """
    if isinstance(payload, str):
        return payload
    lines: list[str] = []

    def _walk(prefix: str, value) -> None:
        if isinstance(value, dict):
            for k, v in value.items():
                _walk(f"{prefix}.{k}" if prefix else str(k), v)
        elif isinstance(value, list):
            for i, item in enumerate(value):
                _walk(f"{prefix}[{i}]", item)
        else:
            if value is None or value == "":
                return
            label = prefix.replace(".", " · ")
            lines.append(f"{label}: {value}")

    _walk("", payload)
    return "\n".join(lines) if lines else json.dumps(payload, indent=2)


@app.get("/api/health")
def health():
    return {"status": "ok"}


DEMO_PATIENT = {
    "name": "Robert Hayes",
    "age": 67,
    "sex": "M",
    "blood_type": "A+",
    "surgery_type": "Hip fracture ORIF",
    "urgency": "emergent",
}


@app.get("/api/demo")
async def demo():
    texts = [t for _, t in DEMO_TEXTS]
    record = await run_patient(texts=texts, patient_id="demo_patient")
    return _api_bundle(record, id_offset=0, patient=DEMO_PATIENT)


@app.post("/api/extract")
async def extract(req: ExtractRequest):
    if not req.texts:
        raise HTTPException(status_code=400, detail="No texts provided")
    record = await run_patient(
        texts=req.texts,
        patient_id=req.patient_id or (req.patient.id if req.patient else None),
    )
    return _api_bundle(record, id_offset=0, patient=_patient_dict(req.patient))


@app.post("/api/decide")
async def decide(req: DecideRequest):
    """Headless one-shot: takes texts + JSON dicts + patient form, returns full bundle."""
    texts = list(req.texts)
    for js in req.json_records:
        texts.append(_json_to_text(js))
    if not texts:
        raise HTTPException(status_code=400, detail="No input provided")
    record = await run_patient(texts=texts, patient_id=req.patient_id)
    return _api_bundle(record, id_offset=0, patient=_patient_dict(req.patient))


@app.post("/api/upload")
async def upload(
    files: list[UploadFile] = File(...),
    id_offset: int = Query(0, ge=0, le=500),
    patient_name: str | None = Form(default=None),
    patient_age: int | None = Form(default=None),
    patient_sex: str | None = Form(default=None),
    patient_blood_type: str | None = Form(default=None),
    surgery_type: str | None = Form(default=None),
    urgency: str | None = Form(default=None),
):
    pdf_bytes: list[bytes] = []
    json_texts: list[str] = []
    wearable_bytes: bytes | None = None

    for f in files:
        content = await f.read()
        name = (f.filename or "").lower()
        if name.endswith(".zip"):
            wearable_bytes = content
        elif name.endswith(".json"):
            try:
                json_texts.append(_json_to_text(json.loads(content.decode("utf-8"))))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise HTTPException(status_code=400, detail=f"Bad JSON in {f.filename}: {exc}") from exc
        elif name.endswith(".txt") or name.endswith(".md") or (f.content_type or "").startswith("text/"):
            json_texts.append(content.decode("utf-8", errors="replace"))
        else:
            pdf_bytes.append(content)

    if not pdf_bytes and not json_texts and wearable_bytes is None:
        raise HTTPException(status_code=400, detail="No files uploaded")

    record = await run_patient(
        sources=pdf_bytes or None,
        texts=json_texts or None,
        wearable_path=wearable_bytes,
    )
    patient = _patient_dict(Patient(
        name=patient_name,
        age=patient_age,
        sex=patient_sex,
        blood_type=patient_blood_type,
        surgery_type=surgery_type,
        urgency=urgency,
    ))
    return _api_bundle(record, id_offset=id_offset, patient=patient)


class SummaryPDFRequest(BaseModel):
    patient: Patient
    verdict: dict
    state: dict
    risk_scores: dict | None = None


@app.post("/api/summary.pdf")
def summary_pdf(req: SummaryPDFRequest):
    """Render the patient summary as a PDF given the bundle the UI already has."""
    pdf_bytes = build_summary_pdf(
        patient=_patient_dict(req.patient),
        verdict=req.verdict,
        state=req.state,
        risk=req.risk_scores or {},
    )
    safe_name = (req.patient.name or "patient").lower().replace(" ", "_")
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="anasafe-summary-{safe_name}.pdf"'
        },
    )


if __name__ == "__main__":
    import uvicorn

    default_port = 8010
    port = int(os.environ.get("PORT", os.environ.get("BACKEND_PORT", str(default_port))))
    uvicorn.run(app, host="0.0.0.0", port=port)
