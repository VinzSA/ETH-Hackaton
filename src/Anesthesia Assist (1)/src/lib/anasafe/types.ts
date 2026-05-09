export type SourceId = string; // "D1:S2" | "W1:M3" | "P1:F2"

export type SourceKind = "note" | "whatsapp" | "photo";

export interface NoteSource {
  kind: "note";
  id: string; // "D1"
  title: string;
  text: string;
}

export interface WhatsAppMessage {
  id: SourceId; // "W1:M3"
  sender: string;
  timestamp?: string;
  text: string;
}

export interface WhatsAppSource {
  kind: "whatsapp";
  id: string; // "W1"
  title: string; // "Family chat — Daughter"
  messages: WhatsAppMessage[];
}

export type PhotoSubtype = "airway" | "pill_bottle" | "handwritten";

export interface PhotoFinding {
  id: SourceId; // "P1:F2"
  label: string;
  detail?: string;
  severity?: "info" | "concerning" | "critical";
}

export interface PhotoSource {
  kind: "photo";
  id: string; // "P1"
  title: string;
  subtype: PhotoSubtype;
  imageUrl?: string; // optional preview
  caption: string;
  findings: PhotoFinding[];
}

export type RawSource = NoteSource | WhatsAppSource | PhotoSource;

// Flattened for the rule extractor and UI highlighting.
export interface SourceDocument {
  id: string;
  title: string;
  kind: SourceKind;
  sentences: { id: SourceId; text: string }[];
}

export interface PreAnesthesiaState {
  allergies: { substance: string; reaction?: string; severity?: string; source_id: SourceId }[];
  anticoagulants: {
    drug: string;
    dose?: string;
    frequency?: string;
    last_dose?: string;
    last_dose_hours_ago?: number;
    source_id: SourceId;
  }[];
  current_medications: { drug: string; dose?: string; frequency?: string; source_id: SourceId }[];
  airway_flags: { flag: string; source_id: SourceId }[];
  prior_anesthesia_complications: { event: string; source_id: SourceId }[];
  cardiac_risks: { condition: string; source_id: SourceId }[];
  pulmonary_risks: { condition: string; source_id: SourceId }[];
  renal_metabolic_risks: { condition: string; source_id: SourceId }[];
  labs: { test: string; value: number; unit: string; source_id: SourceId }[];
  implants_or_devices: { device: string; source_id: SourceId }[];
  npo_status?: { last_intake: string; substance?: string; source_id: SourceId };
}

export type RiskLevel = "low" | "moderate" | "high" | "critical";

export interface CriticalFlag {
  category: string;
  severity: RiskLevel;
  message: string;
  source_ids: SourceId[];
}

export interface MissingField {
  field: string;
  reason: string;
  priority: RiskLevel; // drives Q&A ranking
}

export interface AnticoagTimingPlan {
  drug: string;
  dose?: string;
  last_dose?: string;
  hours_since?: number;
  earliest_neuraxial?: string;
  earliest_elective_surgery?: string;
  emergency_reversal: string[];
  notes: string;
  source_ids: SourceId[];
}

export interface AirwayPlan {
  score: number; // 0-10
  level: RiskLevel;
  recommended_setup: string[];
  source_ids: SourceId[];
}

export interface CounterfactualBranch {
  if: string;
  plan_delta: string[];
  risk_shift: RiskLevel;
}

export interface Counterfactual {
  field: string;
  label: string;
  value_score: number; // 0-100
  priority: RiskLevel;
  branches: CounterfactualBranch[];
}

export interface AgentOutput {
  overall_risk: RiskLevel;
  risk_score: number;
  summary: string;
  critical_flags: CriticalFlag[];
  missing_information: MissingField[];
  recommended_actions: string[];
  anticoag_plans: AnticoagTimingPlan[];
  airway_plan: AirwayPlan;
  drugs_to_avoid: { drug: string; reason: string; source_ids: SourceId[] }[];
  counterfactuals: Counterfactual[];
}

export interface FamilyQATurn {
  id: string;
  question: string;
  rationale: string;
  resolves_field?: string;
  value_score?: number;
  asked_at?: string;
  reply?: string;
  reply_at?: string;
}

export type Urgency = "elective" | "urgent" | "emergent" | "life_saving";

export interface CaseContext {
  age?: number;
  sex?: "M" | "F" | "X";
  surgery_type: string;
  urgency: Urgency;
  case_opened_at: number; // epoch ms
}

export type PlanDecision =
  | "pending_evidence"
  | "requires_senior_review"
  | "proceed_with_caution"
  | "delay_reverse_anticoag"
  | "critical_risk"
  | "proceed"
  | "proceed_with_modifications"
  | "delay"
  | "cancel";

export type PlanEmphasis = "default" | "warn" | "danger";

export type PlanSection =
  | "Decision"
  | "Induction"
  | "Airway"
  | "Lines & Monitoring"
  | "Anesthesia type"
  | "NPO"
  | "Drugs to AVOID"
  | "Reversal on standby"
  | "Devices"
  | "Critical unknowns";

export interface PlanItem {
  id: string; // stable across renders so diff engine can match
  section: PlanSection;
  text: string;
  source_ids: SourceId[];
  caused_by?: string;
  emphasis?: PlanEmphasis;
}

export interface LivingPlan {
  decision: PlanDecision;
  decision_reason: string;
  confidence: number; // 0-100
  critical_unknowns: number;
  items: PlanItem[];
  generated_at: number;
}

export interface PlanDelta {
  kind: "added" | "removed" | "changed";
  item: PlanItem;
  previous?: PlanItem;
  at: number;
}

export interface BriefOutput {
  patient_id: string;
  case_context: {
    scenario: string;
    surgery_type: string;
    patient_status: string;
  };
  pre_anesthesia_state: PreAnesthesiaState;
  agent_output: AgentOutput;
  family_dialogue: FamilyQATurn[];
}
