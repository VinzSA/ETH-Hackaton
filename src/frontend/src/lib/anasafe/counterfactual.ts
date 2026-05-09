// Value-ranked gaps + counterfactual plan diffs.
//
// For each missing fact, we encode (a) how much the plan would change if
// that fact were known, and (b) the two branches a clinician would take.
// The "value_score" drives Q&A ordering and the rendered "ask this first"
// hierarchy.

import type {
  AgentOutput,
  Counterfactual,
  MissingField,
  PreAnesthesiaState,
  RiskLevel,
} from "./types";

interface Rule {
  // Human-readable label of the question this resolves.
  label: string;
  // 0–100. Higher = answering this changes the plan more.
  value_score: number;
  branches: { if: string; plan_delta: string[]; risk_shift: RiskLevel }[];
}

const RULES: Record<string, Rule> = {
  "last anticoagulant dose timing": {
    label: "Time since last anticoagulant dose",
    value_score: 95,
    branches: [
      {
        if: "Last dose < 24 h ago",
        plan_delta: [
          "Avoid neuraxial anesthesia",
          "Plan GA with ETT",
          "Have 4F-PCC and andexanet alfa available",
          "Cross-match 2 units packed cells",
        ],
        risk_shift: "high",
      },
      {
        if: "Last dose ≥ washout window",
        plan_delta: [
          "Neuraxial anesthesia is on the table",
          "Standard GA induction acceptable",
          "Routine type & screen",
        ],
        risk_shift: "moderate",
      },
    ],
  },
  "recent coagulation status": {
    label: "Recent INR / coagulation panel",
    value_score: 78,
    branches: [
      {
        if: "INR > 1.5 or aPTT prolonged",
        plan_delta: [
          "Reverse before induction (vit K + PCC for warfarin)",
          "No neuraxial",
          "Defer non-emergent surgery",
        ],
        risk_shift: "high",
      },
      {
        if: "Coagulation within range",
        plan_delta: ["Proceed per anticoagulant timing rule", "Neuraxial reconsidered"],
        risk_shift: "moderate",
      },
    ],
  },
  "allergy history": {
    label: "Documented drug / latex / contrast reactions",
    value_score: 70,
    branches: [
      {
        if: "Severe reaction confirmed (anaphylaxis, swelling)",
        plan_delta: [
          "Avoid named class entirely",
          "Pre-draw epinephrine and steroids",
          "Latex-free room if applicable",
        ],
        risk_shift: "high",
      },
      {
        if: "Mild rash or no reaction history",
        plan_delta: ["Proceed with standard induction", "Document de-labeling rationale"],
        risk_shift: "low",
      },
    ],
  },
  "recent potassium": {
    label: "Most recent serum potassium",
    value_score: 82,
    branches: [
      {
        if: "K+ > 5.5 mmol/L",
        plan_delta: [
          "Absolutely avoid succinylcholine",
          "Treat hyperkalemia before induction (insulin/dextrose, calcium)",
          "Consider rocuronium with sugammadex",
        ],
        risk_shift: "critical",
      },
      {
        if: "K+ within range",
        plan_delta: ["Standard NMB choice available", "RSI agent unrestricted"],
        risk_shift: "low",
      },
    ],
  },
  "last oral intake": {
    label: "NPO time / last food or drink",
    value_score: 85,
    branches: [
      {
        if: "Solids < 6 h or fluids < 2 h",
        plan_delta: [
          "Rapid sequence induction with cricoid pressure",
          "Suction at the head of bed",
          "Gastric ultrasound if available",
        ],
        risk_shift: "high",
      },
      {
        if: "Adequately fasted",
        plan_delta: ["Standard induction technique"],
        risk_shift: "low",
      },
    ],
  },
  "airway exam": {
    label: "Prior airway / intubation history",
    value_score: 75,
    branches: [
      {
        if: "Prior difficult intubation or known airway anatomy concern",
        plan_delta: [
          "Awake fiberoptic or awake video laryngoscopy",
          "Surgical airway backup at the bedside",
          "Two intubators present",
        ],
        risk_shift: "critical",
      },
      {
        if: "Uneventful prior intubation",
        plan_delta: ["Direct or video laryngoscopy as planned"],
        risk_shift: "low",
      },
    ],
  },
  "current medication list": {
    label: "Complete current medication list",
    value_score: 55,
    branches: [
      {
        if: "Hidden interacting drug found (e.g. linezolid, lithium, MAOI)",
        plan_delta: [
          "Switch pressor choice (phenylephrine over ephedrine)",
          "Re-screen for serotonergic agents",
        ],
        risk_shift: "moderate",
      },
      {
        if: "List confirmed complete and unremarkable",
        plan_delta: ["Proceed with planned agents"],
        risk_shift: "low",
      },
    ],
  },
};

export function computeCounterfactuals(
  _state: PreAnesthesiaState,
  agent: AgentOutput,
): Counterfactual[] {
  const seen = new Set<string>();
  const out: Counterfactual[] = [];
  for (const m of agent.missing_information) {
    if (seen.has(m.field)) continue;
    const rule = RULES[m.field];
    if (!rule) continue;
    seen.add(m.field);
    out.push({
      field: m.field,
      label: rule.label,
      value_score: rule.value_score,
      priority: m.priority,
      branches: rule.branches,
    });
  }
  return out.sort((a, b) => b.value_score - a.value_score);
}

// Re-exposed helper for the questions panel so suggested questions inherit
// the same value score (drives ordering and the "ask this first" badge).
export function valueScoreFor(field: MissingField["field"]): number {
  return RULES[field]?.value_score ?? 30;
}
