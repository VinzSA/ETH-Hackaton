import { valueScoreFor } from "./counterfactual";
import type { AgentOutput, FamilyQATurn, MissingField, PreAnesthesiaState, RiskLevel } from "./types";

// Maps known information gaps to plain-language questions a clinician can
// read out loud or paste into the family chat. Ordered by safety priority.
const TEMPLATES: Record<
  string,
  { question: string; rationale: string; priority: RiskLevel }
> = {
  "last anticoagulant dose timing": {
    question:
      "When exactly did they take their last blood thinner today? Morning, lunch, or evening — and what time?",
    rationale:
      "Timing of the last anticoagulant dose drives reversal need and whether neuraxial anesthesia is even possible.",
    priority: "critical",
  },
  "recent coagulation status": {
    question:
      "Has anyone told you their INR or clotting test result in the last few days? A photo of the lab slip is fine.",
    rationale: "Coagulation status is required before neuraxial or major-bleeding-risk surgery.",
    priority: "high",
  },
  "allergy history": {
    question:
      "Has the patient ever had a bad reaction to a medication, anesthetic, latex, or contrast dye? Even a rash counts.",
    rationale: "An undocumented severe allergy can cause an intra-operative anaphylactic event.",
    priority: "high",
  },
  "recent potassium": {
    question:
      "Do they take any potassium pills, water pills, or have kidney problems? When was their last blood test?",
    rationale: "Hyperkalemia changes induction agent choice and contraindicates succinylcholine.",
    priority: "high",
  },
  "last oral intake": {
    question:
      "What is the last thing they ate or drank today, and at what time? Include water, coffee, candy.",
    rationale: "NPO status determines aspiration risk and whether rapid sequence induction is needed.",
    priority: "high",
  },
  "airway exam": {
    question:
      "Have they ever had trouble with anesthesia or a breathing tube? Any neck surgery, snoring, or sleep apnea?",
    rationale: "Prior difficult intubation strongly predicts future airway problems.",
    priority: "high",
  },
  "current medication list": {
    question:
      "Can you list every medication they take, including over-the-counter and supplements? A photo of the bottles works.",
    rationale: "Unrecognized drugs can interact with anesthetics or affect bleeding.",
    priority: "moderate",
  },
};

export function suggestNextQuestions(
  state: PreAnesthesiaState,
  agent: AgentOutput,
  alreadyAsked: FamilyQATurn[],
  limit = 3,
): FamilyQATurn[] {
  const askedFields = new Set(alreadyAsked.map((t) => t.resolves_field).filter(Boolean));
  const gaps: MissingField[] = [...agent.missing_information];

  // Synthesize gaps from state when fields are obviously missing
  if (state.anticoagulants.length > 0 && state.anticoagulants.some((a) => !a.last_dose)) {
    gaps.unshift({
      field: "last anticoagulant dose timing",
      reason: "Anticoagulant on board with no documented last dose.",
      priority: "critical",
    });
  }
  if (!state.npo_status) {
    gaps.push({
      field: "last oral intake",
      reason: "No NPO time documented.",
      priority: "high",
    });
  }
  if (state.airway_flags.length === 0) {
    gaps.push({
      field: "airway exam",
      reason: "No prior airway information.",
      priority: "moderate",
    });
  }

  const order: Record<RiskLevel, number> = { critical: 3, high: 2, moderate: 1, low: 0 };
  const ranked = gaps
    .filter((g) => !askedFields.has(g.field))
    .sort((a, b) => {
      const va = valueScoreFor(a.field);
      const vb = valueScoreFor(b.field);
      if (vb !== va) return vb - va;
      return order[b.priority] - order[a.priority];
    });

  const out: FamilyQATurn[] = [];
  const seen = new Set<string>();
  for (const g of ranked) {
    if (seen.has(g.field)) continue;
    seen.add(g.field);
    const tpl = TEMPLATES[g.field];
    if (!tpl) continue;
    out.push({
      id: `q_${out.length + 1}_${Date.now()}`,
      question: tpl.question,
      rationale: tpl.rationale,
      resolves_field: g.field,
      value_score: valueScoreFor(g.field),
    });
    if (out.length >= limit) break;
  }
  return out;
}
