import type { PreAnesthesiaState, RawSource, SourceDocument } from "./types";

// ---- Source flattening ------------------------------------------------------
// Convert any RawSource into a flat list of {id, text} sentences so the
// rule extractor can scan them uniformly. WhatsApp messages and photo findings
// each become a "sentence" with their own typed source id.
export function tokenizeSources(sources: RawSource[]): SourceDocument[] {
  return sources.map((src) => {
    if (src.kind === "note") {
      const parts = src.text
        .replace(/\s+/g, " ")
        .trim()
        .split(/(?<=[.!?])\s+(?=[A-Z0-9])/g)
        .filter(Boolean);
      return {
        id: src.id,
        title: src.title,
        kind: "note" as const,
        sentences: parts.map((text, si) => ({ id: `${src.id}:S${si + 1}`, text })),
      };
    }
    if (src.kind === "whatsapp") {
      return {
        id: src.id,
        title: src.title,
        kind: "whatsapp" as const,
        sentences: src.messages.map((m) => ({
          id: m.id,
          text: `${m.sender}${m.timestamp ? " (" + m.timestamp + ")" : ""}: ${m.text}`,
        })),
      };
    }
    // photo: one sentence per finding
    return {
      id: src.id,
      title: src.title,
      kind: "photo" as const,
      sentences: src.findings.map((f) => ({
        id: f.id,
        text: f.detail ? `${f.label}: ${f.detail}` : f.label,
      })),
    };
  });
}

// Backwards compatible helper if a caller still has plain text docs.
export function tokenizeDocuments(docs: { title: string; text: string }[]): SourceDocument[] {
  return tokenizeSources(
    docs.map((d, i) => ({ kind: "note" as const, id: `D${i + 1}`, title: d.title, text: d.text })),
  );
}

// ---- Mock extraction --------------------------------------------------------
// Replace this with a Claude API call later — same input, same output shape.
// The function below intentionally stays deterministic and source-grounded.
export function runExtraction(documents: SourceDocument[]): PreAnesthesiaState {
  const state: PreAnesthesiaState = {
    allergies: [],
    anticoagulants: [],
    current_medications: [],
    airway_flags: [],
    prior_anesthesia_complications: [],
    cardiac_risks: [],
    pulmonary_risks: [],
    renal_metabolic_risks: [],
    labs: [],
    implants_or_devices: [],
  };

  const ANTICOAGULANTS = [
    "apixaban",
    "rivaroxaban",
    "dabigatran",
    "edoxaban",
    "warfarin",
    "heparin",
    "enoxaparin",
    "blood thinner",
    "blood-thinner",
  ];
  const NORMALIZE_DRUG: Record<string, string> = {
    "blood thinner": "apixaban",
    "blood-thinner": "apixaban",
  };
  const CARDIAC = [
    { kw: "atrial fibrillation", cond: "atrial fibrillation" },
    { kw: "heart failure", cond: "heart failure" },
    { kw: "coronary artery", cond: "coronary artery disease" },
    { kw: "myocardial infarction", cond: "prior myocardial infarction" },
    { kw: "sick sinus", cond: "sick sinus syndrome" },
  ];
  const PULMONARY = [
    { kw: "copd", cond: "COPD" },
    { kw: "asthma", cond: "asthma" },
    { kw: "pulmonary hypertension", cond: "pulmonary hypertension" },
    { kw: "obstructive sleep apnea", cond: "obstructive sleep apnea" },
  ];
  const RENAL = [
    { kw: "chronic kidney disease", cond: "chronic kidney disease" },
    { kw: "ckd", cond: "chronic kidney disease" },
    { kw: "dialysis", cond: "dialysis dependence" },
    { kw: "diabetes", cond: "diabetes mellitus" },
  ];
  const DEVICES = [
    { kw: "pacemaker", dev: "pacemaker" },
    { kw: "icd", dev: "implantable cardioverter defibrillator" },
    { kw: "defibrillator", dev: "implantable cardioverter defibrillator" },
    { kw: "stent", dev: "coronary stent" },
  ];
  const AIRWAY_PHRASES = [
    { kw: /difficult intubation|difficult airway|failed intubation/, flag: "prior difficult intubation" },
    { kw: /mallampati (iii|iv|3|4)/, flag: "Mallampati class III–IV on exam" },
    { kw: /limited mouth opening|interincisor.*<\s*3/, flag: "limited mouth opening" },
    { kw: /loose (upper|lower)? ?incisors|loose teeth/, flag: "loose dentition" },
    { kw: /short thyromental|short neck|micrognathia|receding chin/, flag: "anatomic airway concern" },
    { kw: /full beard|thick beard/, flag: "full beard (mask seal risk)" },
  ];

  for (const doc of documents) {
    for (const s of doc.sentences) {
      const t = s.text.toLowerCase();

      // Allergies — also catch "allergic to X" phrasing from family chats
      const allergyMatch =
        t.match(/([a-z]+)\s+allergy(?:\s+with\s+([a-z ]+?))?(?=[\.,]|$)/) ||
        t.match(/allergic to ([a-z]+)(?:\s+(?:with|—|-)\s+([a-z ]+?))?(?=[\.,!]|$)/);
      if (allergyMatch) {
        const sub = allergyMatch[1];
        const reaction = allergyMatch[2]?.trim();
        const severity = reaction && /anaphyl|swell|throat/.test(reaction) ? "severe" : "moderate";
        if (!state.allergies.some((a) => a.substance === sub)) {
          state.allergies.push({ substance: sub, reaction, severity, source_id: s.id });
        }
      }

      // Anticoagulants
      for (const drug of ANTICOAGULANTS) {
        if (t.includes(drug)) {
          const canonical = NORMALIZE_DRUG[drug] ?? drug;
          const doseM = t.match(new RegExp(`${drug}\\s+(\\d+(?:\\.\\d+)?\\s*mg)`));
          const freqM = t.match(/(once daily|twice daily|daily|every \d+ hours|qid|bid|tid|morning|evening)/);
          const lastM =
            t.match(/last (?:documented )?dose(?:\s+at)?\s+(\d{1,2}:\d{2})/) ||
            t.match(/took (?:it|the [a-z ]+) (?:at )?(\d{1,2}:\d{2})/) ||
            t.match(/last (?:one|dose) (?:was )?(this morning|this evening|today|yesterday)/);
          const hoursM =
            lastM?.[1] === "this morning"
              ? 6
              : lastM?.[1] === "this evening"
                ? 1
                : lastM?.[1] === "today"
                  ? 8
                  : lastM?.[1] === "yesterday"
                    ? 18
                    : undefined;
          if (!state.anticoagulants.some((a) => a.drug === canonical)) {
            state.anticoagulants.push({
              drug: canonical,
              dose: doseM?.[1],
              frequency: freqM?.[1],
              last_dose: lastM?.[1],
              last_dose_hours_ago: hoursM,
              source_id: s.id,
            });
          }
        }
      }

      // Other current medications (simple match for known meds in demo)
      const meds = [
        { kw: "metoprolol", drug: "metoprolol" },
        { kw: "atorvastatin", drug: "atorvastatin" },
        { kw: "tiotropium", drug: "tiotropium" },
        { kw: "metformin", drug: "metformin" },
        { kw: "insulin", drug: "insulin" },
      ];
      for (const m of meds) {
        if (t.includes(m.kw) && !state.current_medications.some((x) => x.drug === m.drug)) {
          const doseM = t.match(new RegExp(`${m.kw}[a-z ]*?(\\d+\\s*mg)`));
          const freqM = t.match(/(once daily|twice daily|daily|nightly|bid|tid)/);
          state.current_medications.push({
            drug: m.drug,
            dose: doseM?.[1],
            frequency: freqM?.[1],
            source_id: s.id,
          });
        }
      }

      // Airway
      for (const a of AIRWAY_PHRASES) {
        if (a.kw.test(t) && !state.airway_flags.some((x) => x.flag === a.flag)) {
          state.airway_flags.push({ flag: a.flag, source_id: s.id });
        }
      }

      // Prior anesthesia complications
      if (/postoperative nausea|ponv|nausea and vomiting/.test(t)) {
        state.prior_anesthesia_complications.push({
          event: "post operative nausea and vomiting",
          source_id: s.id,
        });
      }
      if (/malignant hyperthermia/.test(t) && !/no malignant hyperthermia/.test(t)) {
        state.prior_anesthesia_complications.push({
          event: "malignant hyperthermia history",
          source_id: s.id,
        });
      }

      for (const c of CARDIAC) {
        if (t.includes(c.kw) && !state.cardiac_risks.some((x) => x.condition === c.cond)) {
          state.cardiac_risks.push({ condition: c.cond, source_id: s.id });
        }
      }
      for (const p of PULMONARY) {
        if (t.includes(p.kw) && !state.pulmonary_risks.some((x) => x.condition === p.cond)) {
          state.pulmonary_risks.push({ condition: p.cond, source_id: s.id });
        }
      }
      for (const r of RENAL) {
        if (t.includes(r.kw) && !state.renal_metabolic_risks.some((x) => x.condition === r.cond)) {
          state.renal_metabolic_risks.push({ condition: r.cond, source_id: s.id });
        }
      }
      for (const d of DEVICES) {
        if (t.includes(d.kw) && !state.implants_or_devices.some((x) => x.device === d.dev)) {
          state.implants_or_devices.push({ device: d.dev, source_id: s.id });
        }
      }

      // Labs
      const creat = t.match(/creatinine\s+(\d+(?:\.\d+)?)\s*mg\/dl/);
      if (creat)
        state.labs.push({ test: "creatinine", value: parseFloat(creat[1]), unit: "mg/dL", source_id: s.id });
      const k = t.match(/potassium\s+(\d+(?:\.\d+)?)\s*mmol\/l/);
      if (k) state.labs.push({ test: "potassium", value: parseFloat(k[1]), unit: "mmol/L", source_id: s.id });
      const hb = t.match(/hemoglobin\s+(\d+(?:\.\d+)?)\s*g\/dl/);
      if (hb)
        state.labs.push({ test: "hemoglobin", value: parseFloat(hb[1]), unit: "g/dL", source_id: s.id });

      // NPO / last meal — common family-chat fact
      const ate =
        t.match(/(?:he|she|they|patient) (?:ate|had|drank) ([^\.\!,]+?) (?:at )?(\d{1,2}:\d{2})/) ||
        t.match(/last (?:meal|food|drink) (?:was )?(?:at )?(\d{1,2}:\d{2})/);
      if (ate && !state.npo_status) {
        state.npo_status = {
          last_intake: ate[2] ?? ate[1],
          substance: ate[2] ? ate[1] : undefined,
          source_id: s.id,
        };
      }
    }
  }

  // ---- Post-pass: dose reconstruction from pill bottle photos ---------------
  // Photo findings can carry "... → last dose ~Nh ago" or "last dose Xh ago".
  // If we know the drug name on the same finding line, hydrate the matching
  // anticoagulant entry's last_dose_hours_ago. This is what powers the live
  // neuraxial countdown when the family only brings the bottle, not a dose
  // log.
  for (const doc of documents) {
    if (doc.kind !== "photo") continue;
    for (const s of doc.sentences) {
      const t = s.text.toLowerCase();
      const hoursM = t.match(/last dose[^0-9]{0,8}(\d+)\s*h(?:ours?)?\s*ago/);
      if (!hoursM) continue;
      const hrs = parseInt(hoursM[1], 10);
      for (const ac of state.anticoagulants) {
        if (t.includes(ac.drug.toLowerCase()) && ac.last_dose_hours_ago == null) {
          ac.last_dose_hours_ago = hrs;
          if (!ac.last_dose) ac.last_dose = `~${hrs}h ago (per pill count)`;
        }
      }
      // If the bottle names a drug we haven't yet recorded, add it.
      const known = ["apixaban", "rivaroxaban", "warfarin", "dabigatran", "edoxaban", "enoxaparin"];
      for (const drug of known) {
        if (t.includes(drug) && !state.anticoagulants.some((a) => a.drug === drug)) {
          state.anticoagulants.push({
            drug,
            last_dose: `~${hrs}h ago (per pill count)`,
            last_dose_hours_ago: hrs,
            source_id: s.id,
          });
        }
      }
    }
  }

  return state;
}
