import type { AnticoagTimingPlan, PreAnesthesiaState } from "./types";

// Conservative washout windows for normal renal function. These are
// teaching defaults — not a guideline. Always shown alongside source
// evidence and reviewed by a clinician.
const WASHOUT: Record<
  string,
  { neuraxial: number; surgery: number; reversal: string[]; notes: string }
> = {
  apixaban: {
    neuraxial: 72,
    surgery: 48,
    reversal: ["andexanet alfa", "4F-PCC 50 U/kg"],
    notes: "Extend to 96h neuraxial if CrCl < 30.",
  },
  rivaroxaban: {
    neuraxial: 72,
    surgery: 48,
    reversal: ["andexanet alfa", "4F-PCC 50 U/kg"],
    notes: "Extend to 96h neuraxial if CrCl < 30.",
  },
  edoxaban: {
    neuraxial: 72,
    surgery: 48,
    reversal: ["4F-PCC 50 U/kg"],
    notes: "No specific antidote available.",
  },
  dabigatran: {
    neuraxial: 96,
    surgery: 48,
    reversal: ["idarucizumab 5 g IV"],
    notes: "Renally cleared — extend if CrCl < 50.",
  },
  warfarin: {
    neuraxial: 120,
    surgery: 120,
    reversal: ["4F-PCC 25–50 U/kg", "vitamin K 10 mg IV"],
    notes: "Target INR < 1.4 before neuraxial; check INR.",
  },
  enoxaparin: {
    neuraxial: 24,
    surgery: 24,
    reversal: ["protamine (partial reversal)"],
    notes: "Therapeutic dose — 24h. Prophylactic — 12h.",
  },
  heparin: {
    neuraxial: 4,
    surgery: 4,
    reversal: ["protamine 1 mg per 100 U"],
    notes: "Verify normal aPTT before neuraxial.",
  },
};

function fmtHours(h?: number): string | undefined {
  if (h == null) return undefined;
  if (h < 1) return "now";
  if (h < 24) return `in ~${Math.round(h)} h`;
  return `in ~${Math.round(h / 24)} d`;
}

export function computeAnticoagPlans(state: PreAnesthesiaState): AnticoagTimingPlan[] {
  return state.anticoagulants.map((a) => {
    const rule = WASHOUT[a.drug.toLowerCase()];
    if (!rule) {
      return {
        drug: a.drug,
        dose: a.dose,
        last_dose: a.last_dose,
        hours_since: a.last_dose_hours_ago,
        emergency_reversal: ["specialist consultation"],
        notes: "No standard washout rule on file for this agent.",
        source_ids: [a.source_id],
      };
    }
    const hoursSince = a.last_dose_hours_ago;
    const remainingNeuraxial =
      hoursSince != null ? Math.max(0, rule.neuraxial - hoursSince) : undefined;
    const remainingSurgery =
      hoursSince != null ? Math.max(0, rule.surgery - hoursSince) : undefined;
    return {
      drug: a.drug,
      dose: a.dose,
      last_dose: a.last_dose,
      hours_since: hoursSince,
      earliest_neuraxial:
        remainingNeuraxial != null
          ? remainingNeuraxial === 0
            ? "window cleared"
            : fmtHours(remainingNeuraxial)
          : `unknown — needs ${rule.neuraxial}h washout`,
      earliest_elective_surgery:
        remainingSurgery != null
          ? remainingSurgery === 0
            ? "window cleared"
            : fmtHours(remainingSurgery)
          : `unknown — needs ${rule.surgery}h washout`,
      emergency_reversal: rule.reversal,
      notes: rule.notes,
      source_ids: [a.source_id],
    };
  });
}
