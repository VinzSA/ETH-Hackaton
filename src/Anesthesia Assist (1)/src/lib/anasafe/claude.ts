// Single boundary for all "AI" calls. Today every kind returns a deterministic
// mock; later, swap the body of `callClaude` for a real Anthropic request and
// keep all callers unchanged.
//
// Every kind has a typed input and a typed output, so when the mock is
// replaced, TypeScript will guide the migration.

import type { PhotoFinding, WhatsAppMessage } from "./types";

export type ClaudeCallKind =
  | "vision_airway"
  | "vision_pill_bottle"
  | "transcribe_call_turn"
  | "parse_whatsapp"
  | "rank_gap_value"
  | "counterfactual_plan";

export interface ClaudeRequest<K extends ClaudeCallKind, P> {
  kind: K;
  payload: P;
}

export interface VisionAirwayInput {
  image_hint?: string;
}
export interface VisionAirwayOutput {
  findings: PhotoFinding[];
}

export interface VisionPillBottleInput {
  image_hint?: string;
}
export interface VisionPillBottleOutput {
  findings: PhotoFinding[];
}

export interface TranscribeCallTurnInput {
  speaker: "Doctor" | "Family";
  // In production: an audio chunk URL. Here: the next planned line.
  utterance_hint?: string;
}
export interface TranscribeCallTurnOutput {
  message: WhatsAppMessage;
}

// Mock implementation. Returns canned outputs that match the demo case so the
// rest of the pipeline (rule extractor, agent, counterfactual) lights up
// without an API key. Replace the inside of this function with a real
// Anthropic call when ready; signatures stay the same.
export async function callClaude<K extends ClaudeCallKind>(
  req: ClaudeRequest<K, unknown>,
): Promise<unknown> {
  // Tiny delay to simulate a network call so the UI loading states are visible.
  await new Promise((r) => setTimeout(r, 120));

  switch (req.kind) {
    case "vision_airway":
      return {
        findings: [
          { id: "F1", label: "Mallampati IV", detail: "Only the hard palate visible.", severity: "concerning" },
          { id: "F2", label: "Limited mouth opening", detail: "Interincisor distance < 3 cm.", severity: "concerning" },
          { id: "F3", label: "Loose upper incisors", detail: "Two upper central incisors visibly mobile.", severity: "concerning" },
        ],
      } satisfies VisionAirwayOutput;

    case "vision_pill_bottle":
      return {
        findings: [
          {
            id: "F1",
            label: "Apixaban 5 mg",
            // The "last dose ~Xh ago" suffix is the contract the rule
            // extractor uses to fill anticoagulant timing.
            detail:
              "twice daily. Refilled 12 days ago, 22 of 28 tablets left → last dose ~6h ago.",
            severity: "concerning",
          },
          { id: "F2", label: "Metoprolol 50 mg", detail: "once daily." },
        ],
      } satisfies VisionPillBottleOutput;

    case "transcribe_call_turn": {
      const p = req.payload as TranscribeCallTurnInput;
      return {
        message: {
          id: "pending",
          sender: p.speaker,
          timestamp: new Date().toLocaleTimeString(),
          text: p.utterance_hint ?? "",
        },
      } satisfies TranscribeCallTurnOutput;
    }
  }

  return null;
}
