import { computeAnticoagPlans } from "./timing";
import { computeCounterfactuals } from "./counterfactual";
import type {
  AgentOutput,
  AirwayPlan,
  CriticalFlag,
  MissingField,
  PreAnesthesiaState,
  RiskLevel,
  SourceId,
} from "./types";

const HIGH_RISK_ALLERGENS = ["penicillin", "latex", "succinylcholine", "rocuronium", "morphine"];

export function runPreAnesthesiaAgent(state: PreAnesthesiaState): AgentOutput {
  const flags: CriticalFlag[] = [];
  const missing: MissingField[] = [];
  const actions: string[] = [];
  const drugsToAvoid: { drug: string; reason: string; source_ids: SourceId[] }[] = [];

  // ---- Anticoagulants ------------------------------------------------------
  for (const a of state.anticoagulants) {
    flags.push({
      category: "bleeding_risk",
      severity: "high",
      message: `Active anticoagulant: ${a.drug}${a.dose ? " " + a.dose : ""}${a.frequency ? ", " + a.frequency : ""}.`,
      source_ids: [a.source_id],
    });
    if (!a.last_dose) {
      missing.push({
        field: "last anticoagulant dose timing",
        reason: `Last ${a.drug} dose timing is missing.`,
        priority: "critical",
      });
    }
    actions.push("Verify anticoagulant timing and reversal availability.");
  }
  if (state.anticoagulants.length > 0) {
    const hasCoag = state.labs.some((l) => ["inr", "ptt", "aptt"].includes(l.test.toLowerCase()));
    if (!hasCoag) {
      missing.push({
        field: "recent coagulation status",
        reason: "Anticoagulant documented but no INR or coagulation lab found.",
        priority: "high",
      });
    }
  }

  // ---- Airway --------------------------------------------------------------
  for (const a of state.airway_flags) {
    flags.push({
      category: "airway_risk",
      severity: "high",
      message: `Airway concern: ${a.flag}.`,
      source_ids: [a.source_id],
    });
  }

  // ---- Allergies -----------------------------------------------------------
  for (const al of state.allergies) {
    const high = HIGH_RISK_ALLERGENS.includes(al.substance.toLowerCase());
    flags.push({
      category: "allergy",
      severity: high ? "high" : "moderate",
      message: `${high ? "High risk allergy" : "Allergy"}: ${al.substance}${al.reaction ? " (" + al.reaction + ")" : ""}.`,
      source_ids: [al.source_id],
    });
    if (al.substance.toLowerCase() === "penicillin") {
      drugsToAvoid.push({
        drug: "penicillin / beta-lactams",
        reason: `Documented penicillin allergy${al.reaction ? " — " + al.reaction : ""}.`,
        source_ids: [al.source_id],
      });
    }
  }

  for (const c of state.cardiac_risks) {
    flags.push({
      category: "cardiac",
      severity: "moderate",
      message: `Cardiac disease: ${c.condition}.`,
      source_ids: [c.source_id],
    });
  }
  for (const p of state.pulmonary_risks) {
    flags.push({
      category: "pulmonary",
      severity: "moderate",
      message: `Pulmonary disease: ${p.condition}.`,
      source_ids: [p.source_id],
    });
  }
  for (const r of state.renal_metabolic_risks) {
    flags.push({
      category: "renal_metabolic",
      severity: "moderate",
      message: `Renal or metabolic risk: ${r.condition}.`,
      source_ids: [r.source_id],
    });
  }

  // ---- Labs & derived "drugs to avoid" -------------------------------------
  for (const l of state.labs) {
    if (l.test === "creatinine" && l.value > 1.5) {
      flags.push({
        category: "renal_metabolic",
        severity: l.value > 3 ? "high" : "moderate",
        message: `Creatinine elevated at ${l.value} ${l.unit}.`,
        source_ids: [l.source_id],
      });
      drugsToAvoid.push({
        drug: "morphine, gabapentin, NSAIDs",
        reason: `Creatinine ${l.value} ${l.unit} — accumulation risk.`,
        source_ids: [l.source_id],
      });
    }
    if (l.test === "potassium" && l.value > 5.5) {
      flags.push({
        category: "metabolic",
        severity: l.value > 6.0 ? "critical" : "high",
        message: `Potassium elevated at ${l.value} ${l.unit}. Avoid succinylcholine.`,
        source_ids: [l.source_id],
      });
      drugsToAvoid.push({
        drug: "succinylcholine",
        reason: `Potassium ${l.value} ${l.unit} — risk of further rise.`,
        source_ids: [l.source_id],
      });
    }
    if (l.test === "hemoglobin" && l.value < 8) {
      flags.push({
        category: "hematology",
        severity: "high",
        message: `Hemoglobin low at ${l.value} ${l.unit}.`,
        source_ids: [l.source_id],
      });
    }
  }

  for (const d of state.implants_or_devices) {
    flags.push({
      category: "device",
      severity: "moderate",
      message: `Implant: ${d.device}. Confirm peri-operative plan.`,
      source_ids: [d.source_id],
    });
    if (/pacemaker|defibrillator/i.test(d.device)) {
      actions.push("Obtain recent device interrogation and apply magnet plan.");
    }
  }

  for (const c of state.prior_anesthesia_complications) {
    flags.push({
      category: "prior_anesthesia",
      severity: c.event.includes("malignant") ? "critical" : "moderate",
      message: `Prior anesthesia event: ${c.event}.`,
      source_ids: [c.source_id],
    });
    if (c.event.includes("malignant")) {
      drugsToAvoid.push({
        drug: "all volatile agents, succinylcholine",
        reason: "Reported malignant hyperthermia history.",
        source_ids: [c.source_id],
      });
    }
  }

  // ---- Missing essentials --------------------------------------------------
  if (state.allergies.length === 0) {
    missing.push({
      field: "allergy history",
      reason: "No allergies documented; patient unable to confirm.",
      priority: "high",
    });
  }
  if (!state.labs.some((l) => l.test === "potassium")) {
    missing.push({
      field: "recent potassium",
      reason: "No potassium value documented prior to induction.",
      priority: "high",
    });
  }
  if (!state.npo_status) {
    missing.push({
      field: "last oral intake",
      reason: "No NPO / last meal time documented.",
      priority: "high",
    });
  }

  // ---- Airway plan ---------------------------------------------------------
  const airway_plan = computeAirwayPlan(state);
  if (airway_plan.level === "high" || airway_plan.level === "critical") {
    actions.push("Set up difficult airway cart: video laryngoscope, bougie, supraglottic, surgical backup.");
  }

  // ---- Score & overall -----------------------------------------------------
  const weight: Record<RiskLevel, number> = { low: 0, moderate: 1, high: 2, critical: 4 };
  const risk_score = flags.reduce((acc, f) => acc + weight[f.severity], 0) + airway_plan.score;
  let overall: RiskLevel = "low";
  if (flags.some((f) => f.severity === "critical")) overall = "critical";
  else if (risk_score >= 7) overall = "high";
  else if (risk_score >= 3) overall = "moderate";

  actions.unshift("Request senior anesthesia review before induction.");

  // De-dup drugs-to-avoid
  const seenAvoid = new Set<string>();
  const drugs_to_avoid = drugsToAvoid.filter((d) => {
    if (seenAvoid.has(d.drug)) return false;
    seenAvoid.add(d.drug);
    return true;
  });

  const draft: AgentOutput = {
    overall_risk: overall,
    risk_score,
    summary:
      overall === "critical"
        ? "Critical findings present. Do not induce until reviewed by senior anesthesia."
        : overall === "high"
          ? "Pre anesthesia review required before induction."
          : overall === "moderate"
            ? "Moderate risk. Confirm flagged items prior to induction."
            : "No major flags identified from available documents.",
    critical_flags: flags,
    missing_information: missing,
    recommended_actions: Array.from(new Set(actions)),
    anticoag_plans: computeAnticoagPlans(state),
    airway_plan,
    drugs_to_avoid,
    counterfactuals: [],
  };
  draft.counterfactuals = computeCounterfactuals(state, draft);
  return draft;
}

function computeAirwayPlan(state: PreAnesthesiaState): AirwayPlan {
  const sources: SourceId[] = state.airway_flags.map((f) => f.source_id);
  let score = 0;
  for (const f of state.airway_flags) {
    if (/difficult intubation|failed/.test(f.flag)) score += 4;
    else if (/mallampati/i.test(f.flag)) score += 3;
    else if (/limited mouth/.test(f.flag)) score += 2;
    else if (/loose dentition/.test(f.flag)) score += 1;
    else if (/anatomic|beard/.test(f.flag)) score += 1;
  }
  const level: RiskLevel =
    score >= 6 ? "critical" : score >= 4 ? "high" : score >= 2 ? "moderate" : "low";
  const setup: string[] = ["Standard induction setup."];
  if (score >= 2) setup.unshift("Have video laryngoscope at the bedside.");
  if (score >= 4) {
    setup.unshift("Plan awake fiberoptic or awake video laryngoscopy.");
    setup.push("Surgical airway backup ready.");
  }
  return { score, level, recommended_setup: setup, source_ids: sources };
}
