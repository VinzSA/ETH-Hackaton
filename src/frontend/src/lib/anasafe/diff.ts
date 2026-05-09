// Per-item plan diff. Items are matched by stable id so we can tell whether
// a section was added, removed, or had its text/emphasis change — which the
// UI uses to flash "↻ updated Xs ago because Y".

import type { LivingPlan, PlanDelta } from "./types";

export function diffPlans(prev: LivingPlan | null, next: LivingPlan): PlanDelta[] {
  const out: PlanDelta[] = [];
  if (!prev) {
    for (const item of next.items) {
      out.push({ kind: "added", item, at: next.generated_at });
    }
    return out;
  }
  const prevById = new Map(prev.items.map((i) => [i.id, i]));
  const nextById = new Map(next.items.map((i) => [i.id, i]));
  for (const item of next.items) {
    const p = prevById.get(item.id);
    if (!p) {
      out.push({ kind: "added", item, at: next.generated_at });
    } else if (p.text !== item.text || p.emphasis !== item.emphasis) {
      out.push({ kind: "changed", item, previous: p, at: next.generated_at });
    }
  }
  for (const item of prev.items) {
    if (!nextById.has(item.id)) {
      out.push({ kind: "removed", item, at: next.generated_at });
    }
  }
  return out;
}
