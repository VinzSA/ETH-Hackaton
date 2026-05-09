import type { RawSource } from "./types";

// Legacy export, kept for backward compat in tests / older callers.
export const demoDocuments: { title: string; text: string }[] = [
  {
    title: "ED Triage Note · 02:14",
    text: "67-year-old male brought in after mechanical fall at home. Patient is confused, GCS 13, unable to provide reliable history. Past history per chart includes atrial fibrillation. Family reports a known penicillin allergy with rash.",
  },
  {
    title: "Outpatient Medication List",
    text: "Active medications reconciled from pharmacy refill records. Apixaban 5 mg orally twice daily for atrial fibrillation; last documented dose at 18:00 the prior evening. Metoprolol succinate 50 mg orally once daily. Atorvastatin 40 mg nightly.",
  },
  {
    title: "Anesthesia Record — Prior Admission 2022",
    text: "Prior difficult intubation documented during cholecystectomy in 2022, required video laryngoscopy and bougie. Postoperative nausea and vomiting noted in PACU. No malignant hyperthermia history reported.",
  },
  {
    title: "Pulmonology Clinic Letter",
    text: "Patient followed for moderate COPD on tiotropium inhaler. Baseline oxygen saturation 93% on room air. No recent exacerbations. Smoking history 40 pack-years, quit 5 years ago.",
  },
  {
    title: "Recent Laboratory Results",
    text: "Chronic kidney disease stage 3 documented on prior nephrology notes. Creatinine 1.9 mg/dL today, up from baseline 1.4. Potassium 5.8 mmol/L today, repeat pending. Hemoglobin 11.2 g/dL. No INR or coagulation panel resulted.",
  },
  {
    title: "Cardiology Device Card",
    text: "Dual-chamber pacemaker implanted 2019 for sick sinus syndrome, Medtronic model. Last interrogation 4 months ago, normal function.",
  },
];

// Rich demo: the same case, but in the messy multi-source form a real on-call
// anesthesiologist would actually receive at 2 a.m.
export const demoSources: RawSource[] = [
  {
    kind: "note",
    id: "D1",
    title: "ED Triage Note · 02:14",
    text: demoDocuments[0].text,
  },
  {
    kind: "note",
    id: "D2",
    title: "Outpatient Medication List",
    text: demoDocuments[1].text,
  },
  {
    kind: "note",
    id: "D3",
    title: "Anesthesia Record — 2022",
    text: demoDocuments[2].text,
  },
  {
    kind: "note",
    id: "D4",
    title: "Recent Laboratory Results",
    text: demoDocuments[4].text,
  },
  {
    kind: "note",
    id: "D5",
    title: "Cardiology Device Card",
    text: demoDocuments[5].text,
  },
  {
    kind: "whatsapp",
    id: "W1",
    title: "Family chat — Daughter",
    messages: [
      {
        id: "W1:M1",
        sender: "Daughter",
        timestamp: "02:31",
        text: "Hi doctor, this is Sarah, his daughter. I was told you needed info about Dad before surgery.",
      },
      {
        id: "W1:M2",
        sender: "Daughter",
        timestamp: "02:32",
        text: "He has the irregular heartbeat thing and takes a blood thinner every morning with breakfast.",
      },
      {
        id: "W1:M3",
        sender: "Daughter",
        timestamp: "02:33",
        text: "Last one was this morning around 7am I think.",
      },
      {
        id: "W1:M4",
        sender: "Daughter",
        timestamp: "02:34",
        text: "He’s allergic to penicillin — gets a really bad rash and his lips swell.",
      },
      {
        id: "W1:M5",
        sender: "Daughter",
        timestamp: "02:35",
        text: "He also wears a heart device, a pacemaker I think, put in a few years ago.",
      },
      {
        id: "W1:M6",
        sender: "Daughter",
        timestamp: "02:36",
        text: "He ate a sandwich at 19:30 yesterday evening. Hasn’t had anything since, just a sip of water around 22:00.",
      },
    ],
  },
  {
    kind: "photo",
    id: "P1",
    title: "Airway photo (mouth opening)",
    subtype: "airway",
    caption: "Phone photo taken by the ED resident in resus bay 3.",
    findings: [
      {
        id: "P1:F1",
        label: "Mallampati IV",
        detail: "Only the hard palate visible.",
        severity: "concerning",
      },
      {
        id: "P1:F2",
        label: "Limited mouth opening",
        detail: "Interincisor distance < 3 cm.",
        severity: "concerning",
      },
      {
        id: "P1:F3",
        label: "Loose upper incisors",
        detail: "Two upper central incisors visibly mobile.",
        severity: "concerning",
      },
    ],
  },
  {
    kind: "photo",
    id: "P2",
    title: "Pill bottle photo",
    subtype: "pill_bottle",
    caption: "Brought in by family, photographed in the ED.",
    findings: [
      {
        id: "P2:F1",
        label: "Apixaban 5 mg",
        detail:
          "twice daily. Refilled 12 days ago, 22 of 28 tablets left → last dose ~6h ago.",
        severity: "concerning",
      },
      {
        id: "P2:F2",
        label: "Metoprolol 50 mg",
        detail: "once daily.",
      },
    ],
  },
];
