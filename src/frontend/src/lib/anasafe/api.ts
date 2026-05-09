import type { PreAnesthesiaState } from "./types";

const BASE =
  (import.meta.env?.VITE_BACKEND_URL as string | undefined) ?? "http://127.0.0.1:8010";

export interface RCRIResult {
  score: number;
  criteria_met: string[];
  criteria_absent: string[];
  mace_risk_pct: number;
  risk_label: "low" | "intermediate" | "high";
  missing_data: string[];
}

export interface HASBLEDResult {
  score: number;
  criteria_met: string[];
  criteria_absent: string[];
  bleed_risk_pct: number;
  risk_label: "low" | "moderate" | "high";
  missing_data: string[];
}

export interface ASAResult {
  estimated_class: number;
  rationale: string[];
  upgrades_applied: string[];
  caveats: string[];
}

export interface DOACWashoutResult {
  drug: string;
  last_dose: string | null;
  half_life_hours: number;
  renal_fraction: number;
  estimated_crcl: number | null;
  washout_hours_low_risk: number;
  washout_hours_high_risk: number;
  washout_hours_neuraxial: number;
  recommendation: string;
  missing_data: string[];
}

export interface RiskScores {
  rcri: RCRIResult;
  hasbled: HASBLEDResult;
  asa: ASAResult;
  doac_washout: DOACWashoutResult[];
  overall_risk_label: "low" | "intermediate" | "high" | "critical";
  headline_warnings: string[];
}

export interface UIDocument {
  id: string;
  title: string;
  text: string;
  document_type?: string;
  document_date?: string | null;
}

export interface ScoredFact {
  category: string;
  name: string;
  n_confirmations: number;
  n_contradictions: number;
  posterior: number;
  label: string;
}

export interface FactConfidenceReport {
  patient_id: string;
  facts: ScoredFact[];
}

export type ValidationStatus = "pass" | "warn" | "fail" | "info";

export interface ValidationStep {
  id: string;
  title: string;
  status: ValidationStatus;
  summary: string;
  impact: string;
}

export type Severity = "critical" | "high" | "moderate" | "info";

export interface VerdictFactor {
  title: string;
  detail: string;
  weight: number;
  direction: "block" | "support";
  severity: Severity;
  source_ids: string[];
  source_snippet?: string | null;
}

export interface Verdict {
  label: "OK" | "NOT OK";
  headline: string;
  subtitle: string;
  confidence_pct: number;
  threshold_pct: number;
  score: number;
  cautions: VerdictFactor[];
  important_info: VerdictFactor[];
  all_factors: VerdictFactor[];
  surgery_type?: string | null;
}

export interface PatientForm {
  name?: string;
  age?: number;
  sex?: "M" | "F" | "X";
  blood_type?: string;
  surgery_type?: string;
  urgency?: "elective" | "urgent" | "emergent" | "life_saving";
  threshold_pct?: number;
}

export interface PatientEnriched extends PatientForm {
  id?: string;
  allergies_summary?: string;
}

export interface BackendResult {
  state: PreAnesthesiaState;
  warnings: string[];
  confidence: number;
  risk_scores?: RiskScores;
  documents?: UIDocument[];
  fact_confidence?: FactConfidenceReport;
  validation_steps?: ValidationStep[];
  verdict?: Verdict;
  patient?: PatientEnriched;
}

export async function fetchDemo(): Promise<BackendResult> {
  const res = await fetch(`${BASE}/api/demo`);
  if (!res.ok) throw new Error(`Backend /api/demo error: ${res.status}`);
  return res.json() as Promise<BackendResult>;
}

export async function extractTexts(
  texts: string[],
  patient?: PatientForm,
  patientId?: string,
): Promise<BackendResult> {
  const res = await fetch(`${BASE}/api/extract`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ texts, patient: patient ?? null, patient_id: patientId ?? null }),
  });
  if (!res.ok) throw new Error(`Backend /api/extract error: ${res.status}`);
  return res.json() as Promise<BackendResult>;
}

export async function uploadFiles(
  files: File[],
  patient?: PatientForm,
  idOffset = 0,
): Promise<BackendResult> {
  const form = new FormData();
  for (const f of files) form.append("files", f);
  if (patient?.name) form.append("patient_name", patient.name);
  if (patient?.age != null) form.append("patient_age", String(patient.age));
  if (patient?.sex) form.append("patient_sex", patient.sex);
  if (patient?.blood_type) form.append("patient_blood_type", patient.blood_type);
  if (patient?.surgery_type) form.append("surgery_type", patient.surgery_type);
  if (patient?.urgency) form.append("urgency", patient.urgency);
  const q = idOffset > 0 ? `?id_offset=${idOffset}` : "";
  const res = await fetch(`${BASE}/api/upload${q}`, {
    method: "POST",
    body: form,
  });
  if (!res.ok) throw new Error(`Backend /api/upload error: ${res.status}`);
  return res.json() as Promise<BackendResult>;
}

export async function downloadSummaryPdf(bundle: {
  patient: PatientEnriched;
  verdict: Verdict;
  state: PreAnesthesiaState;
  risk_scores?: RiskScores;
}): Promise<Blob> {
  const res = await fetch(`${BASE}/api/summary.pdf`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(bundle),
  });
  if (!res.ok) throw new Error(`Backend /api/summary.pdf error: ${res.status}`);
  return res.blob();
}

export async function checkHealth(): Promise<boolean> {
  try {
    const res = await fetch(`${BASE}/api/health`, { signal: AbortSignal.timeout(2000) });
    return res.ok;
  } catch {
    return false;
  }
}
