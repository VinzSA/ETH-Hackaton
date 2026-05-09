// Living Plan synthesizer.
//
// Safety posture: this engine NEVER claims to clear a patient for anesthesia.
// With zero evidence we emit a generic baseline template flagged as
// "PENDING EVIDENCE". With evidence we surface planning considerations and
// escalate to "REQUIRES SENIOR ANESTHESIA REVIEW" / "DELAY OR REVERSE
// ANTICOAGULATION" / "CRITICAL RISK FOUND" rather than autonomous decisions.

import type {
  AgentOutput,
  CaseContext,
  LivingPlan,
  PlanDecision,
  PlanItem,
  PreAnesthesiaState,
} from "./types";

const VERIFY_TAG = "Planning consideration — requires clinician verification.";

function baseSkeleton(ctx: CaseContext): PlanItem[] {
  const items: PlanItem[] = [
    {
      id: "induction.agent",
      section: "Induction",
      text: "Consider IV induction agent titrated to effect (clinician to choose drug and dose).",
      source_ids: [],
    },
    {
      id: "induction.nmb",
      section: "Induction",
      text: "Consider non-depolarising paralytic strategy with reversal available.",
      source_ids: [],
    },
    {
      id: "induction.pressor",
      section: "Induction",
      text: "Have vasopressor (e.g. phenylephrine) prepared for induction hypotension.",
      source_ids: [],
    },
    {
      id: "airway.technique",
      section: "Airway",
      text: "Standard airway plan with backup adjuncts available.",
      source_ids: [],
    },
    {
      id: "lines.iv",
      section: "Lines & Monitoring",
      text: "Adequate IV access prior to induction.",
      source_ids: [],
    },
    {
      id: "lines.monitoring",
      section: "Lines & Monitoring",
      text: "Standard ASA monitors (SpO2, NIBP, ECG, EtCO2, T).",
      source_ids: [],
    },
    {
      id: "neuraxial.option",
      section: "Anesthesia type",
      text: "Anesthesia type to be selected by clinician based on surgery and patient factors.",
      source_ids: [],
    },
    {
      id: "npo.plan",
      section: "NPO",
      text: "Confirm NPO status before induction.",
      source_ids: [],
    },
  ];
  if (ctx.urgency === "emergent" || ctx.urgency === "life_saving") {
    const npo = items.find((i) => i.id === "npo.plan");
    if (npo) {
      npo.text = "Emergency case — assume full stomach until proven otherwise; consider RSI with cricoid pressure.";
      npo.emphasis = "warn";
      npo.caused_by = `Urgency: ${ctx.urgency}`;
    }
  }
  return items;
}

const MISSING_CATEGORIES: { id: string; field: string; reason: string }[] = [
  { id: "unknown.anticoag", field: "Anticoagulant history", reason: "Affects neuraxial timing and bleeding management." },
  { id: "unknown.allergy", field: "Allergy history", reason: "Affects antibiotic and drug selection." },
  { id: "unknown.airway", field: "Airway history", reason: "Affects airway equipment and personnel needs." },
  { id: "unknown.renal", field: "Renal labs", reason: "Affects drug dosing and reversal choices." },
  { id: "unknown.cardiac", field: "Cardiac history", reason: "Affects monitoring and induction strategy." },
  { id: "unknown.npo", field: "NPO status", reason: "Affects aspiration risk and induction technique." },
];

export function synthesizePlan(
  ctx: CaseContext,
  state: PreAnesthesiaState | null,
  agent: AgentOutput | null,
): LivingPlan {
  const items = baseSkeleton(ctx);
  const byId = new Map(items.map((i) => [i.id, i]));
  const upsert = (item: PlanItem) => {
    byId.set(item.id, item);
    const idx = items.findIndex((i) => i.id === item.id);
    if (idx === -1) items.push(item);
    else items[idx] = item;
  };
  const get = (id: string) => byId.get(id)!;

  let decision: PlanDecision = "proceed_with_caution";
  let decisionReason = "Source-grounded evidence integrated. Clinician review required.";
  let confidence = ctx.urgency === "life_saving" ? 35 : 55;

  if (!state || !agent) {
    decision = "pending_evidence";
    decisionReason =
      "Generic baseline plan only. No patient-specific safety evidence has been integrated yet. Not cleared for anesthesia.";
    confidence = 0;
    for (const m of MISSING_CATEGORIES) {
      upsert({
        id: m.id,
        section: "Critical unknowns",
        text: `Missing: ${m.field}`,
        source_ids: [],
        emphasis: "warn",
        caused_by: m.reason,
      });
    }
    return {
      decision,
      decision_reason: decisionReason,
      confidence,
      critical_unknowns: MISSING_CATEGORIES.length,
      items,
      generated_at: Date.now(),
    };
  }

  // ── Anticoagulants ────────────────────────────────────────────────────
  let anticoagUnknownTiming = false;
  let anticoagOnBoard = false;
  for (const ac of state.anticoagulants) {
    anticoagOnBoard = true;
    const plan = agent.anticoag_plans.find((p) => p.drug === ac.drug);
    const cleared = plan?.earliest_neuraxial === "window cleared";
    const neu = get("neuraxial.option");
    if (ac.last_dose_hours_ago == null) {
      anticoagUnknownTiming = true;
      neu.text = `Neuraxial likely contraindicated — ${ac.drug} on board, last dose unknown. ${VERIFY_TAG}`;
      neu.source_ids = [ac.source_id];
      neu.emphasis = "danger";
      neu.caused_by = `${ac.drug} with no documented timing`;
    } else if (!cleared && plan) {
      neu.text = `Neuraxial earliest ${plan.earliest_neuraxial} (washout). ${VERIFY_TAG}`;
      neu.source_ids = [ac.source_id];
      neu.emphasis = "warn";
      neu.caused_by = `${ac.drug} ${ac.last_dose_hours_ago}h ago`;
    }
    if (plan) {
      upsert({
        id: `reversal.${ac.drug}`,
        section: "Reversal on standby",
        text: `Have ${plan.emergency_reversal.join(" or ")} available for ${ac.drug} bleeding. ${VERIFY_TAG}`,
        source_ids: [ac.source_id],
        caused_by: `${ac.drug} active anticoagulation`,
        emphasis: "warn",
      });
    }
    const lines = get("lines.iv");
    lines.text = `Consider large-bore IV access (e.g. two 16G) and arterial line; type & screen / cross-match as appropriate. ${VERIFY_TAG}`;
    lines.source_ids = [ac.source_id];
    lines.emphasis = "warn";
    lines.caused_by = `${ac.drug} bleeding risk`;
  }

  // ── Drugs to avoid ────────────────────────────────────────────────────
  for (const avoid of agent.drugs_to_avoid) {
    upsert({
      id: `avoid.${avoid.drug}`,
      section: "Drugs to AVOID",
      text: avoid.drug,
      source_ids: avoid.source_ids,
      caused_by: avoid.reason,
      emphasis: "danger",
    });
  }

  // ── Hyperkalemia → swap NMB ───────────────────────────────────────────
  const k = state.labs.find((l) => l.test === "potassium");
  let severeHyperK = false;
  if (k && k.value > 5.5) {
    const nmb = get("induction.nmb");
    nmb.text = `Avoid succinylcholine given K+ ${k.value} ${k.unit}; consider non-depolarising paralytic with reversal. ${VERIFY_TAG}`;
    nmb.source_ids = [k.source_id];
    nmb.emphasis = "warn";
    nmb.caused_by = `K+ ${k.value} ${k.unit}`;
    if (k.value > 6.0) severeHyperK = true;
  }

  // ── Renal → induction dose adjustment ─────────────────────────────────
  const cr = state.labs.find((l) => l.test === "creatinine");
  if (cr && cr.value > 1.5) {
    const ag = get("induction.agent");
    ag.text = `Renal dosing caution — reduce IV induction agent dose; reassess for renally cleared drugs. ${VERIFY_TAG}`;
    ag.source_ids = [cr.source_id];
    ag.emphasis = "warn";
    ag.caused_by = `Creatinine ${cr.value} ${cr.unit}`;
  }

  // ── Airway ────────────────────────────────────────────────────────────
  const airwayHigh =
    agent.airway_plan.level === "critical" || agent.airway_plan.level === "high";
  if (airwayHigh) {
    const a = get("airway.technique");
    a.text = `Escalate airway plan: consider awake fiberoptic / awake video laryngoscopy, surgical airway backup, two intubators present. ${VERIFY_TAG}`;
    a.source_ids = agent.airway_plan.source_ids;
    a.emphasis = "danger";
    a.caused_by = `Airway score ${agent.airway_plan.score} (${agent.airway_plan.level})`;
  } else if (agent.airway_plan.level === "moderate") {
    const a = get("airway.technique");
    a.text = `Have video laryngoscope and bougie immediately available. ${VERIFY_TAG}`;
    a.source_ids = agent.airway_plan.source_ids;
    a.emphasis = "warn";
    a.caused_by = `Airway score ${agent.airway_plan.score}`;
  }

  // ── NPO ───────────────────────────────────────────────────────────────
  if (state.npo_status) {
    const npo = get("npo.plan");
    npo.text = `Last intake ${state.npo_status.last_intake}${state.npo_status.substance ? " (" + state.npo_status.substance + ")" : ""} — verify aspiration risk and RSI need. ${VERIFY_TAG}`;
    npo.source_ids = [state.npo_status.source_id];
    npo.caused_by = "NPO status documented from family";
    npo.emphasis = "default";
  } else if (!(ctx.urgency === "emergent" || ctx.urgency === "life_saving")) {
    const npo = get("npo.plan");
    npo.text = `NPO time unknown — consider RSI with cricoid pressure until confirmed. ${VERIFY_TAG}`;
    npo.emphasis = "warn";
    npo.caused_by = "No NPO documented";
  }

  // ── Cardiac monitoring upgrade ────────────────────────────────────────
  if (state.cardiac_risks.length > 0) {
    const m = get("lines.monitoring");
    m.text = `Consider 5-lead ECG and arterial line for beat-to-beat BP. ${VERIFY_TAG}`;
    m.source_ids = state.cardiac_risks.map((c) => c.source_id);
    m.caused_by = state.cardiac_risks.map((c) => c.condition).join(", ");
    m.emphasis = "warn";
  }

  // ── Devices ───────────────────────────────────────────────────────────
  for (const d of state.implants_or_devices) {
    if (/pacemaker|defibrillator|cardioverter/i.test(d.device)) {
      upsert({
        id: `device.${d.device}`,
        section: "Devices",
        text: `${d.device} — confirm recent interrogation, plan magnet placement, prefer bipolar cautery. ${VERIFY_TAG}`,
        source_ids: [d.source_id],
        emphasis: "warn",
        caused_by: `Implant: ${d.device}`,
      });
    }
  }

  // ── Critical unknowns surface in the plan ─────────────────────────────
  const ranked = [...agent.missing_information]
    .filter((m) => m.priority === "critical" || m.priority === "high")
    .slice(0, 4);
  const unknowns = ranked.length;
  for (const m of ranked) {
    upsert({
      id: `unknown.${m.field}`,
      section: "Critical unknowns",
      text: m.field,
      source_ids: [],
      emphasis: m.priority === "critical" ? "danger" : "warn",
      caused_by: m.reason,
    });
  }

  // ── Decision selection ────────────────────────────────────────────────
  const hasCritical = agent.critical_flags.some((f) => f.severity === "critical");
  if (hasCritical || severeHyperK) {
    decision = "critical_risk";
    decisionReason =
      "Critical risk found — senior anesthesia review required and underlying issue should be addressed before induction.";
  } else if (anticoagUnknownTiming || (anticoagOnBoard && ctx.urgency === "elective")) {
    decision = "delay_reverse_anticoag";
    decisionReason = anticoagUnknownTiming
      ? "Anticoagulant on board with unknown timing — request coagulation status and consider reversal strategy before neuraxial or high-bleeding-risk surgery."
      : "Anticoagulant on board for elective case — delay until washout window cleared or plan reversal.";
  } else if (
    airwayHigh ||
    anticoagOnBoard ||
    agent.critical_flags.filter((f) => f.severity === "high").length >= 2
  ) {
    decision = "requires_senior_review";
    const causes: string[] = [];
    for (const ac of state.anticoagulants) {
      causes.push(`${ac.drug}${ac.last_dose_hours_ago != null ? ` last dose ~${ac.last_dose_hours_ago}h ago` : " timing unknown"}`);
    }
    if (airwayHigh) causes.push("prior difficult intubation / airway risk");
    if (k && k.value > 5.5) causes.push(`K+ ${k.value}`);
    if (cr && cr.value > 1.5) causes.push(`Cr ${cr.value}`);
    if (unknowns > 0) causes.push(`${unknowns} critical unknown${unknowns === 1 ? "" : "s"}`);
    decisionReason = `Reason: ${causes.join(", ")}.`;
  } else {
    decision = "proceed_with_caution";
    decisionReason = "Source-grounded evidence integrated; clinician verification required before induction.";
  }

  // Evidence completeness scoring
  let groundedFacts = 0;
  groundedFacts += state.allergies.length;
  groundedFacts += state.anticoagulants.length;
  groundedFacts += state.current_medications.length;
  groundedFacts += state.airway_flags.length;
  groundedFacts += state.cardiac_risks.length;
  groundedFacts += state.pulmonary_risks.length;
  groundedFacts += state.renal_metabolic_risks.length;
  groundedFacts += state.labs.length;
  groundedFacts += state.implants_or_devices.length;
  groundedFacts += state.npo_status ? 1 : 0;
  confidence = Math.max(20, Math.min(95, 40 + groundedFacts * 4 - unknowns * 8));

  return {
    decision,
    decision_reason: decisionReason,
    confidence,
    critical_unknowns: unknowns,
    items,
    generated_at: Date.now(),
  };
}
