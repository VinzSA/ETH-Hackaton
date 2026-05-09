# AnaSafe v5 — Simple, elegant, single-screen

A focused redesign that strips the page to its essence. No more dense 4-column grids, no Family Q&A, no JSON viewer, no traffic lights. One clean two-column layout that fits on a laptop screen.

## Layout

```text
┌─ AnaSafe ───────────────────────  67 M · Hip ORIF · Emergent ─ [Run demo] [Reset] ─┐
├──────────────────────────────────┬─────────────────────────────────────────────────┤
│  PATIENT DOCUMENTS               │  DECISION                                       │
│  ┌─ drop files / paste ────────┐ │  ╎ Requires senior review                       │
│  │  Drop here or click         │ │  ╎ Apixaban on board, K+ 5.8, prior difficult   │
│  └────────────────────────────┘ │  ╎ intubation                                    │
│                                  │  ────────────────────────────────────────────── │
│  D1  ED triage note         ›   │  ANESTHESIA PLAN                                │
│  D2  Outpatient meds        ›   │                                                 │
│  P1  Airway photo           ›   │  Induction                                      │
│  W1  Family chat            ›   │   • Reduce IV dose — renal (Cr 1.9 · D4)        │
│                                  │   • Avoid succinylcholine (K+ 5.8 · D4)         │
│                                  │                                                 │
│                                  │  Airway                                         │
│                                  │   • Awake video laryngoscopy, two intubators    │
│                                  │     (Mallampati IV · P1)                        │
│                                  │                                                 │
│                                  │  Anticoagulation                                │
│                                  │   • Neuraxial deferred — apixaban (D2)          │
│                                  │                                                 │
│                                  │  ────────────────────────────────────────────── │
│                                  │  CRITICAL UNKNOWNS  3                           │
│                                  │   – INR / coagulation panel                     │
│                                  │   – NPO status                                  │
│                                  │   – Current vitals                              │
└──────────────────────────────────┴─────────────────────────────────────────────────┘
                          AnaSafe is decision support · disclaimer
```

## What gets removed

From `src/routes/index.tsx`:
- **Family Q&A panel** (`FamilyQAPanel`, suggested-questions logic, reply drafts, `appendFamilyMessage`)
- **Extracted safety state column** (`CategoryCard` rows for allergies, anticoagulants, meds, airway, cardiac, renal, labs, NPO, devices)
- **Pre-anesthesia safety agent column** (`AgentPanel`, `TrafficLight`, `CounterfactualCard`, anticoag-timing card, airway plan card, drugs-to-avoid card, recommended-actions card)
- **Why-changed standalone panel** (`WhyChangedPanel`)
- **Brief.json copy-to-clipboard panel**
- **Stopwatch chip** in the header
- **Multi-field Case Context bar** — collapsed to a single one-line summary `67 M · Hip fracture ORIF · Emergent` with a small "Edit" popover (clicking opens a compact form)
- All numeric panel-index badges (1, 2, 3, 4) and `PanelHeader`

The agent / extraction / synthesis libraries (`agent.ts`, `extract.ts`, `plan.ts`, `diff.ts`, `questions.ts`, `timing.ts`, `counterfactual.ts`) stay untouched. The page just stops surfacing the intermediate panels — the synthesis still runs and feeds the Living Plan.

## What stays (and gets polished)

1. **Header**: brand, one-line case summary with edit, demo + reset buttons.
2. **Left column — Patient documents**:
   - One drop zone (already built)
   - Compact paste textarea below it (collapsed by default behind a "Paste text" toggle to reduce visual noise)
   - Source list as a clean vertical list. Each row: mono ID badge (D1, P1…), title, source-kind icon. Click expands the row inline to show extracted sentences/messages/findings (accordion). No nested cards.
3. **Right column — Decision + Plan**:
   - **Decision banner**: white, 3px left border in the decision color, single navy headline, one-line reason. No confidence meter, no "evidence completeness" widget, no generated-at timestamp.
   - **Plan**, grouped by section in plain typography:
     - Section label in small caps + faint hairline underline
     - Each item: a single line of text. A small grey caption beneath reads `because <cause> · <D-ids>`. No chips, no colored backgrounds. A 4px colored left edge appears only when emphasis is `warn` or `danger`.
     - Items remain clickable to scroll the linked source into view; source-row click still highlights matching plan items with a subtle primary underline.
   - **Critical unknowns**: a hairline-bordered list at the bottom of the plan, no warning-red background. Just the field name + one-line reason in muted text.
4. **Footer**: short disclaimer in muted small caps, one line.

## Visual rules

- White background everywhere; no `bg-muted` or `bg-card` backgrounds on inner cards. Use hairline borders (`border-border`) and whitespace instead.
- Single accent: medical blue, used only for the active source link, the upload-zone hover state, and the primary "Add as source" / "Run demo" buttons.
- Risk colors only on: decision banner left edge, the 4px left edge of warn/danger plan items, the small dot before a critical unknown.
- Type scale: 22px headline (decision), 13px body, 11px captions. Inter, tabular-nums on numbers.
- Generous spacing: `gap-6` between major blocks, `py-3` between plan items, `py-2` between source rows.
- Max content width 1200px, centered.
- No emoji, no icons in plan items, only the upload arrow icon and chevrons on source rows.

## Files touched

- `src/routes/index.tsx` — remove ~700 lines of panel UI; rebuild the JSX around the two-column layout. Keep `LivingPlanPanel`, `PlanItemRow`, `SourceCard`, `NoteBody`, `WhatsAppBody`, `PhotoBody`, `UploadZone`, `synthesizePlan` wiring. Replace `CaseContextBar` with a one-line summary + popover.
- `src/styles.css` — minor: tighten `--border` and add a `--surface` token if needed for hover states. No palette change beyond what's already medical white/blue.

## Out of scope

- Real PDF/image OCR (still stubbed — file appears as a source row with placeholder text)
- Restoring any removed panel
- New features beyond the redesign
