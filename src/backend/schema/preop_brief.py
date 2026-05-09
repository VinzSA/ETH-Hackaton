from pydantic import BaseModel, Field
from typing import Optional, Literal
from datetime import date

class SourceRef(BaseModel):
    """Every entity carries this — non-negotiable for source grounding."""
    document_id: str
    document_type: str
    page: int
    char_start: int
    char_end: int
    snippet: str  # sentence-bounded excerpt around the extraction (≤320 chars)

class Medication(BaseModel):
    name: str
    rxnorm_code: Optional[str] = None
    atc_code: Optional[str] = None
    dose: Optional[str] = None  # "5mg"
    frequency: Optional[str] = None  # "BID"
    route: Optional[str] = None
    last_dose_datetime: Optional[str] = None  # ISO 8601
    indication: Optional[str] = None
    is_anticoagulant: bool = False
    is_antiplatelet: bool = False
    source: SourceRef

class Diagnosis(BaseModel):
    description: str
    icd10_code: Optional[str] = None
    is_active: bool = True
    onset_date: Optional[str] = None
    source: SourceRef

class Allergy(BaseModel):
    substance: str
    reaction: Optional[str] = None
    severity: Optional[Literal["mild", "moderate", "severe", "anaphylaxis"]] = None
    source: SourceRef

class Procedure(BaseModel):
    name: str
    cpt_code: Optional[str] = None
    ops_code: Optional[str] = None  # German
    chop_code: Optional[str] = None  # Swiss
    procedure_date: Optional[str] = None
    surgeon: Optional[str] = None
    complications: Optional[str] = None
    source: SourceRef

class Implant(BaseModel):
    description: str  # "Right TKR, Zimmer NexGen"
    gmdn_code: Optional[str] = None
    manufacturer: Optional[str] = None
    model: Optional[str] = None
    implanted_date: Optional[str] = None
    body_site: Optional[str] = None
    source: SourceRef

class LabValue(BaseModel):
    test_name: str  # "creatinine", "INR", "HbA1c", "hemoglobin", "platelets", "EF"
    loinc_code: Optional[str] = None
    value: float
    unit: str
    reference_range: Optional[str] = None
    measured_date: Optional[str] = None
    source: SourceRef

class AnesthesiaHistory(BaseModel):
    asa_score: Optional[int] = None  # 1-5
    anesthesia_type: Optional[str] = None  # "general endotracheal"
    airway_notes: Optional[str] = None
    complications: Optional[str] = None
    procedure_date: Optional[str] = None
    source: SourceRef

class CardiacAssessment(BaseModel):
    ejection_fraction_pct: Optional[float] = None
    nyha_class: Optional[int] = None
    has_history_mi: bool = False
    has_stents: bool = False
    has_atrial_fibrillation: bool = False
    last_assessment_date: Optional[str] = None
    source: SourceRef

class ExtractedDocument(BaseModel):
    """Output of your extraction layer — what you hand to the backend team."""
    document_id: str
    document_type: Literal[
        "discharge_summary", "operative_note", "anesthesia_record",
        "cardiology_consult", "lab_report", "medication_list", "unknown"
    ]
    document_date: Optional[str] = None
    language_detected: str  # "en", "de", "fr", "it"
    
    medications: list[Medication] = []
    diagnoses: list[Diagnosis] = []
    allergies: list[Allergy] = []
    procedures: list[Procedure] = []
    implants: list[Implant] = []
    labs: list[LabValue] = []
    anesthesia_history: list[AnesthesiaHistory] = []
    cardiac: list[CardiacAssessment] = []
    
    extraction_confidence: float = Field(ge=0, le=1)
    extraction_warnings: list[str] = []
    raw_text: Optional[str] = None