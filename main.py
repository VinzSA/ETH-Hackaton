"""
ER Pre-Op Brief — FastAPI backend.
Run: er-preop-brief/.venv/bin/uvicorn main:app --reload --port 8000
"""
import asyncio
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from functools import partial

# Resolve imports: pipeline uses "from src.classifier..." where src/ is
# a self-referential symlink inside src/backend/ pointing to the same dir.
_BACKEND = os.path.join(os.path.dirname(__file__), "src", "backend")
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from ingestion.pipeline import process_patient

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


def _source_id(src, doc_index: int) -> str:
    """Map a backend SourceRef to the frontend SourceId format (e.g. 'D1:S1')."""
    return f"D{doc_index + 1}:S1"


def record_to_pre_anesthesia_state(record, doc_id_map: dict[str, int]) -> dict:
    """Convert a PatientRecord dataclass to the PreAnesthesiaState TypeScript shape."""

    def sid(src_obj) -> str:
        idx = doc_id_map.get(src_obj.document_id, 0)
        return f"D{idx + 1}:S1"

    allergies = [
        {
            "substance": a.substance,
            "reaction": a.reaction,
            "severity": a.severity,
            "source_id": sid(a.source),
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
        }
        for m in record.medications
        if not m.is_anticoagulant
    ]

    airway_flags = []
    prior_anesthesia_complications = []
    for ah in record.anesthesia_history:
        if ah.airway_notes:
            airway_flags.append({"flag": ah.airway_notes, "source_id": sid(ah.source)})
        if ah.complications:
            prior_anesthesia_complications.append(
                {"event": ah.complications, "source_id": sid(ah.source)}
            )

    cardiac_risks = []
    for c in record.cardiac:
        if c.has_atrial_fibrillation:
            cardiac_risks.append({"condition": "atrial fibrillation", "source_id": sid(c.source)})
        if c.has_history_mi:
            cardiac_risks.append(
                {"condition": "prior myocardial infarction", "source_id": sid(c.source)}
            )
        if c.has_stents:
            cardiac_risks.append({"condition": "coronary stent", "source_id": sid(c.source)})
        if c.nyha_class and c.nyha_class >= 3:
            cardiac_risks.append(
                {"condition": f"NYHA class {c.nyha_class} heart failure", "source_id": sid(c.source)}
            )

    pulmonary_kws = ["copd", "asthma", "pulmonary hypertension", "sleep apnea", "emphysema", "respiratory"]
    pulmonary_risks = [
        {"condition": d.description, "source_id": sid(d.source)}
        for d in record.diagnoses
        if any(kw in d.description.lower() for kw in pulmonary_kws)
    ]

    renal_kws = ["kidney", "ckd", "dialysis", "diabet", "renal", "metabolic", "hyperkalemia"]
    renal_metabolic_risks = [
        {"condition": d.description, "source_id": sid(d.source)}
        for d in record.diagnoses
        if any(kw in d.description.lower() for kw in renal_kws)
    ]

    labs = [
        {
            "test": lab.test_name,
            "value": lab.value,
            "unit": lab.unit,
            "source_id": sid(lab.source),
        }
        for lab in record.labs
    ]

    implants_or_devices = [
        {"device": i.description, "source_id": sid(i.source)}
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


class ExtractRequest(BaseModel):
    texts: list[str]
    patient_id: str | None = None


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/demo")
async def demo():
    texts = [t for _, t in DEMO_TEXTS]
    record = await run_patient(texts=texts, patient_id="demo_patient")
    doc_id_map = {doc_id: i for i, doc_id in enumerate(record.document_timeline.keys())}
    state = record_to_pre_anesthesia_state(record, doc_id_map)
    return {"state": state, "warnings": record.warnings, "confidence": record.overall_confidence}


@app.post("/api/extract")
async def extract(req: ExtractRequest):
    if not req.texts:
        raise HTTPException(status_code=400, detail="No texts provided")
    record = await run_patient(texts=req.texts, patient_id=req.patient_id)
    doc_id_map = {doc_id: i for i, doc_id in enumerate(record.document_timeline.keys())}
    state = record_to_pre_anesthesia_state(record, doc_id_map)
    return {"state": state, "warnings": record.warnings, "confidence": record.overall_confidence}


@app.post("/api/upload")
async def upload(files: list[UploadFile] = File(...)):
    pdf_bytes: list[bytes] = []
    wearable_bytes: bytes | None = None

    for f in files:
        content = await f.read()
        name = (f.filename or "").lower()
        if name.endswith(".zip"):
            wearable_bytes = content
        else:
            pdf_bytes.append(content)

    if not pdf_bytes and wearable_bytes is None:
        raise HTTPException(status_code=400, detail="No files uploaded")

    record = await run_patient(
        sources=pdf_bytes or None,
        wearable_path=wearable_bytes,
    )

    doc_id_map = {doc_id: i for i, doc_id in enumerate(record.document_timeline.keys())}
    state = record_to_pre_anesthesia_state(record, doc_id_map)
    return {"state": state, "warnings": record.warnings, "confidence": record.overall_confidence}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
