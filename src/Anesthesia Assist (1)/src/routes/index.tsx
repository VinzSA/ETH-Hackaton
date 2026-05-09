import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useMemo, useRef, useState } from "react";
import { runPreAnesthesiaAgent } from "@/lib/anasafe/agent";
import { demoSources } from "@/lib/anasafe/demo";
import { runExtraction, tokenizeSources } from "@/lib/anasafe/extract";
import { synthesizePlan } from "@/lib/anasafe/plan";
import type {
  AgentOutput,
  CaseContext,
  LivingPlan,
  PlanDecision,
  PlanItem,
  PlanSection,
  PreAnesthesiaState,
  RawSource,
  SourceId,
  Urgency,
} from "@/lib/anasafe/types";

export const Route = createFileRoute("/")({
  component: AnaSafe,
  head: () => ({
    meta: [
      { title: "AnaSafe — Pre-anesthesia decision support" },
      {
        name: "description",
        content:
          "AnaSafe synthesizes a source-grounded anesthesia plan from uploaded patient documents.",
      },
    ],
  }),
});

const SECTION_ORDER: PlanSection[] = [
  "Induction",
  "Airway",
  "Anesthesia type",
  "Lines & Monitoring",
  "NPO",
  "Drugs to AVOID",
  "Reversal on standby",
  "Devices",
];

const URGENCY_OPTS: { value: Urgency; label: string }[] = [
  { value: "elective", label: "Elective" },
  { value: "urgent", label: "Urgent" },
  { value: "emergent", label: "Emergent" },
  { value: "life_saving", label: "Life-saving" },
];

const DECISION_LABEL: Record<PlanDecision, string> = {
  pending_evidence: "Pending evidence",
  requires_senior_review: "Requires senior review",
  proceed_with_caution: "Proceed with caution",
  delay_reverse_anticoag: "Delay or reverse anticoagulation",
  critical_risk: "Critical risk found",
  proceed: "Proceed",
  proceed_with_modifications: "Proceed with modifications",
  delay: "Delay",
  cancel: "Cancel",
};

function decisionTone(d: PlanDecision): "neutral" | "warn" | "danger" {
  if (d === "critical_risk" || d === "cancel") return "danger";
  if (
    d === "requires_senior_review" ||
    d === "delay_reverse_anticoag" ||
    d === "delay" ||
    d === "proceed_with_caution" ||
    d === "proceed_with_modifications" ||
    d === "pending_evidence"
  )
    return "warn";
  return "neutral";
}

function AnaSafe() {
  const [sources, setSources] = useState<RawSource[]>([]);
  const [activeSource, setActiveSource] = useState<SourceId | null>(null);
  const [pasteOpen, setPasteOpen] = useState(false);
  const [pasteValue, setPasteValue] = useState("");
  const [editCase, setEditCase] = useState(false);
  const [expandedSource, setExpandedSource] = useState<string | null>(null);

  const [caseContext, setCaseContext] = useState<CaseContext>(() => ({
    age: 67,
    sex: "M",
    surgery_type: "Hip fracture ORIF",
    urgency: "emergent",
    case_opened_at: Date.now(),
  }));

  const documents = useMemo(() => tokenizeSources(sources), [sources]);
  const state: PreAnesthesiaState | null = useMemo(
    () => (documents.length ? runExtraction(documents) : null),
    [documents],
  );
  const agent: AgentOutput | null = useMemo(
    () => (state ? runPreAnesthesiaAgent(state) : null),
    [state],
  );
  const plan: LivingPlan = useMemo(
    () => synthesizePlan(caseContext, state, agent),
    [caseContext, state, agent],
  );

  const sentenceRefs = useRef<Record<string, HTMLElement | null>>({});

  useEffect(() => {
    if (activeSource && sentenceRefs.current[activeSource]) {
      // Auto-expand the parent source so the highlighted sentence is visible.
      const parent = activeSource.split(":")[0];
      setExpandedSource(parent);
      requestAnimationFrame(() => {
        sentenceRefs.current[activeSource]?.scrollIntoView({
          behavior: "smooth",
          block: "center",
        });
      });
    }
  }, [activeSource]);

  function nextId(prefix: string) {
    const used = sources.filter((s) => s.id.startsWith(prefix)).length;
    return `${prefix}${used + 1}`;
  }

  function loadDemo() {
    setSources(demoSources);
    setActiveSource(null);
    setExpandedSource(null);
  }

  function clearAll() {
    setSources([]);
    setActiveSource(null);
    setExpandedSource(null);
    setPasteValue("");
    setPasteOpen(false);
  }

  function addPasted() {
    if (!pasteValue.trim()) return;
    const id = nextId("D");
    setSources((s) => [
      ...s,
      { kind: "note", id, title: `Pasted note ${id}`, text: pasteValue.trim() },
    ]);
    setPasteValue("");
    setPasteOpen(false);
  }

  async function handleFiles(files: FileList | null) {
    if (!files || files.length === 0) return;
    const next: RawSource[] = [];
    let i = 0;
    for (const f of Array.from(files)) {
      const id = `D${sources.length + next.length + 1 + i}`;
      i = 0; // ids resolved via length below
      const isText = /\.(txt|md)$/i.test(f.name) || f.type.startsWith("text/");
      const text = isText
        ? await f.text()
        : `[${f.name} received — ${(f.size / 1024).toFixed(1)} KB. PDF/image content extraction is not wired in this prototype.]`;
      next.push({ kind: "note", id, title: f.name, text });
    }
    setSources((s) => [...s, ...next]);
  }

  function removeSource(id: string) {
    setSources((s) => s.filter((x) => x.id !== id));
    if (expandedSource === id) setExpandedSource(null);
  }

  const tone = decisionTone(plan.decision);
  const decisionEdge =
    tone === "danger"
      ? "border-l-risk-critical"
      : tone === "warn"
        ? "border-l-risk-high"
        : "border-l-risk-low";

  const grouped = useMemo(() => {
    const g: Partial<Record<PlanSection, PlanItem[]>> = {};
    for (const item of plan.items) {
      if (item.section === "Critical unknowns") continue;
      (g[item.section] ??= []).push(item);
    }
    return g;
  }, [plan]);

  const unknowns = plan.items.filter((i) => i.section === "Critical unknowns");

  return (
    <div className="min-h-screen bg-background text-foreground">
      {/* ── Header ─────────────────────────────────────────────────────── */}
      <header className="border-b border-border">
        <div className="mx-auto flex max-w-[1200px] flex-wrap items-center justify-between gap-3 px-6 py-4">
          <div className="flex items-center gap-3">
            <div className="flex h-8 w-8 items-center justify-center rounded-md bg-primary text-primary-foreground">
              <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2.4">
                <path d="M12 3 5 6v6c0 4.5 3 8.4 7 9 4-.6 7-4.5 7-9V6l-7-3Z" />
                <path d="M9 12h6M12 9v6" />
              </svg>
            </div>
            <div>
              <h1 className="text-base font-semibold tracking-tight">AnaSafe</h1>
              <p className="text-[11px] text-muted-foreground">
                Pre-anesthesia decision support · source-grounded
              </p>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <CaseSummary
              ctx={caseContext}
              editing={editCase}
              onToggle={() => setEditCase((v) => !v)}
              onChange={setCaseContext}
            />
            <button
              onClick={loadDemo}
              className="rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground transition hover:bg-primary/90"
            >
              Run demo
            </button>
            <button
              onClick={clearAll}
              className="rounded-md border border-border bg-background px-3 py-1.5 text-xs font-medium text-foreground transition hover:bg-accent"
            >
              Reset
            </button>
          </div>
        </div>
      </header>

      {/* ── Main two-column layout ─────────────────────────────────────── */}
      <main className="mx-auto grid max-w-[1200px] gap-8 px-6 py-8 lg:grid-cols-[minmax(0,360px)_1fr]">
        {/* Documents column */}
        <section className="space-y-5">
          <SectionLabel>Patient documents</SectionLabel>

          <UploadZone onFiles={handleFiles} />

          <div>
            <button
              onClick={() => setPasteOpen((v) => !v)}
              className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground transition hover:text-primary"
            >
              {pasteOpen ? "− Hide paste" : "+ Paste text"}
            </button>
            {pasteOpen && (
              <div className="mt-2 space-y-2">
                <textarea
                  value={pasteValue}
                  onChange={(e) => setPasteValue(e.target.value)}
                  placeholder="Paste a chart note, lab printout, or med list…"
                  className="h-24 w-full resize-none rounded-md border border-input bg-background px-3 py-2 text-sm leading-relaxed outline-none focus:border-primary"
                />
                <button
                  onClick={addPasted}
                  disabled={!pasteValue.trim()}
                  className="rounded-md bg-foreground px-3 py-1.5 text-xs font-medium text-background transition hover:opacity-90 disabled:opacity-40"
                >
                  Add as source
                </button>
              </div>
            )}
          </div>

          <div>
            {sources.length === 0 ? (
              <p className="rounded-md border border-dashed border-border px-4 py-8 text-center text-xs text-muted-foreground">
                No documents yet. Drop a file or click{" "}
                <span className="font-medium text-primary">Run demo</span>.
              </p>
            ) : (
              <ul className="divide-y divide-border border-t border-border">
                {sources.map((src) => (
                  <SourceRow
                    key={src.id}
                    source={src}
                    expanded={expandedSource === src.id}
                    onToggle={() =>
                      setExpandedSource((id) => (id === src.id ? null : src.id))
                    }
                    onRemove={() => removeSource(src.id)}
                    activeSource={activeSource}
                    setActiveSource={setActiveSource}
                    sentenceRefs={sentenceRefs}
                  />
                ))}
              </ul>
            )}
          </div>
        </section>

        {/* Decision + Plan column */}
        <section className="space-y-8">
          {/* Decision banner */}
          <div className={`border-l-[3px] ${decisionEdge} pl-5`}>
            <div className="text-[10px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">
              Decision
            </div>
            <h2 className="mt-1 text-2xl font-semibold tracking-tight text-foreground">
              {DECISION_LABEL[plan.decision]}
            </h2>
            <p className="mt-1.5 max-w-2xl text-sm leading-relaxed text-muted-foreground">
              {plan.decision_reason}
            </p>
          </div>

          {/* Plan */}
          <div className="space-y-6">
            <SectionLabel>Anesthesia plan</SectionLabel>
            {SECTION_ORDER.filter((s) => grouped[s] && grouped[s]!.length).map((s) => (
              <PlanGroup
                key={s}
                title={s}
                items={grouped[s]!}
                activeSource={activeSource}
                setActiveSource={setActiveSource}
              />
            ))}
          </div>

          {/* Critical unknowns */}
          {unknowns.length > 0 && (
            <div className="space-y-3 border-t border-border pt-6">
              <div className="flex items-baseline gap-2">
                <SectionLabel>Critical unknowns</SectionLabel>
                <span className="font-mono text-[11px] tabular-nums text-muted-foreground">
                  {unknowns.length}
                </span>
              </div>
              <ul className="space-y-2.5">
                {unknowns.map((u) => (
                  <li key={u.id} className="flex items-start gap-3 text-sm">
                    <span
                      className={`mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full ${
                        u.emphasis === "danger" ? "bg-risk-critical" : "bg-risk-high"
                      }`}
                    />
                    <div className="min-w-0">
                      <div className="text-foreground">{u.text}</div>
                      {u.caused_by && (
                        <div className="text-[12px] text-muted-foreground">
                          {u.caused_by}
                        </div>
                      )}
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </section>
      </main>

      <footer className="border-t border-border">
        <div className="mx-auto max-w-[1200px] px-6 py-4 text-[11px] leading-relaxed text-muted-foreground">
          AnaSafe is a clinical decision-support prototype. It does not clear patients for
          anesthesia, does not prescribe medications, and does not replace anesthesiologist
          judgment. All outputs require independent clinician verification.
        </div>
      </footer>
    </div>
  );
}

// ─── Subcomponents ──────────────────────────────────────────────────────

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <h3 className="text-[10px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">
      {children}
    </h3>
  );
}

function CaseSummary({
  ctx,
  editing,
  onToggle,
  onChange,
}: {
  ctx: CaseContext;
  editing: boolean;
  onToggle: () => void;
  onChange: (next: CaseContext) => void;
}) {
  const summary = `${ctx.age ?? "?"} ${ctx.sex ?? ""} · ${ctx.surgery_type} · ${
    URGENCY_OPTS.find((o) => o.value === ctx.urgency)?.label
  }`;
  return (
    <div className="relative">
      <button
        onClick={onToggle}
        className="flex items-center gap-1.5 rounded-md border border-border bg-background px-3 py-1.5 text-xs text-foreground transition hover:border-primary/50 hover:text-primary"
      >
        <span className="tabular-nums">{summary}</span>
        <svg viewBox="0 0 24 24" className="h-3 w-3 opacity-60" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M12 4v16M4 12h16" strokeLinecap="round" />
        </svg>
      </button>
      {editing && (
        <div className="absolute right-0 top-full z-10 mt-2 w-72 space-y-2.5 rounded-md border border-border bg-card p-3 shadow-lg">
          <div className="grid grid-cols-2 gap-2">
            <label className="text-[11px] text-muted-foreground">
              Age
              <input
                type="number"
                value={ctx.age ?? ""}
                onChange={(e) =>
                  onChange({ ...ctx, age: e.target.value ? Number(e.target.value) : undefined })
                }
                className="mt-1 w-full rounded border border-input bg-background px-2 py-1 text-xs text-foreground"
              />
            </label>
            <label className="text-[11px] text-muted-foreground">
              Sex
              <select
                value={ctx.sex ?? "X"}
                onChange={(e) => onChange({ ...ctx, sex: e.target.value as "M" | "F" | "X" })}
                className="mt-1 w-full rounded border border-input bg-background px-2 py-1 text-xs text-foreground"
              >
                <option value="M">M</option>
                <option value="F">F</option>
                <option value="X">X</option>
              </select>
            </label>
          </div>
          <label className="block text-[11px] text-muted-foreground">
            Surgery
            <input
              value={ctx.surgery_type}
              onChange={(e) => onChange({ ...ctx, surgery_type: e.target.value })}
              className="mt-1 w-full rounded border border-input bg-background px-2 py-1 text-xs text-foreground"
            />
          </label>
          <label className="block text-[11px] text-muted-foreground">
            Urgency
            <select
              value={ctx.urgency}
              onChange={(e) => onChange({ ...ctx, urgency: e.target.value as Urgency })}
              className="mt-1 w-full rounded border border-input bg-background px-2 py-1 text-xs text-foreground"
            >
              {URGENCY_OPTS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </label>
          <button
            onClick={onToggle}
            className="w-full rounded-md bg-foreground px-2.5 py-1.5 text-[11px] font-medium text-background hover:opacity-90"
          >
            Done
          </button>
        </div>
      )}
    </div>
  );
}

function UploadZone({ onFiles }: { onFiles: (files: FileList | null) => void }) {
  const [drag, setDrag] = useState(false);
  return (
    <label
      onDragOver={(e) => {
        e.preventDefault();
        setDrag(true);
      }}
      onDragLeave={() => setDrag(false)}
      onDrop={(e) => {
        e.preventDefault();
        setDrag(false);
        onFiles(e.dataTransfer.files);
      }}
      className={`flex cursor-pointer flex-col items-center justify-center gap-1.5 rounded-md border border-dashed px-4 py-8 text-center transition-colors ${
        drag
          ? "border-primary bg-primary/5"
          : "border-border bg-background hover:border-primary/50"
      }`}
    >
      <svg viewBox="0 0 24 24" className="h-5 w-5 text-primary" fill="none" stroke="currentColor" strokeWidth="1.8">
        <path d="M12 16V4M12 4l-4 4M12 4l4 4" strokeLinecap="round" strokeLinejoin="round" />
        <path d="M4 16v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      <div className="text-sm font-medium text-foreground">Drop documents here</div>
      <div className="text-[11px] text-muted-foreground">
        Notes · labs · med list · airway photo
      </div>
      <input
        type="file"
        multiple
        accept=".txt,.md,.pdf,.png,.jpg,.jpeg,text/plain,application/pdf,image/*"
        className="hidden"
        onChange={(e) => onFiles(e.target.files)}
      />
    </label>
  );
}

function SourceRow({
  source,
  expanded,
  onToggle,
  onRemove,
  activeSource,
  setActiveSource,
  sentenceRefs,
}: {
  source: RawSource;
  expanded: boolean;
  onToggle: () => void;
  onRemove: () => void;
  activeSource: SourceId | null;
  setActiveSource: (id: SourceId | null) => void;
  sentenceRefs: React.MutableRefObject<Record<string, HTMLElement | null>>;
}) {
  const kindLabel =
    source.kind === "note" ? "note" : source.kind === "whatsapp" ? "chat" : "photo";
  const linked =
    activeSource && activeSource.startsWith(source.id + ":");
  return (
    <li className={`group ${linked ? "bg-primary/5" : ""}`}>
      <div className="flex items-center gap-3 px-1 py-3">
        <button onClick={onToggle} className="flex flex-1 items-center gap-3 text-left">
          <span className="font-mono text-[11px] tabular-nums text-muted-foreground">
            {source.id}
          </span>
          <span className="flex-1 truncate text-sm text-foreground">{source.title}</span>
          <span className="text-[10px] uppercase tracking-wider text-muted-foreground">
            {kindLabel}
          </span>
          <svg
            viewBox="0 0 24 24"
            className={`h-3.5 w-3.5 text-muted-foreground transition-transform ${expanded ? "rotate-90" : ""}`}
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
          >
            <path d="m9 6 6 6-6 6" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>
        <button
          onClick={onRemove}
          className="opacity-0 transition group-hover:opacity-100"
          title="Remove"
        >
          <svg viewBox="0 0 24 24" className="h-3.5 w-3.5 text-muted-foreground hover:text-risk-critical" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M6 6l12 12M18 6 6 18" strokeLinecap="round" />
          </svg>
        </button>
      </div>
      {expanded && (
        <div className="px-1 pb-3 text-[13px] leading-relaxed">
          <SourceBody
            source={source}
            activeSource={activeSource}
            setActiveSource={setActiveSource}
            sentenceRefs={sentenceRefs}
          />
        </div>
      )}
    </li>
  );
}

function SourceBody({
  source,
  activeSource,
  setActiveSource,
  sentenceRefs,
}: {
  source: RawSource;
  activeSource: SourceId | null;
  setActiveSource: (id: SourceId | null) => void;
  sentenceRefs: React.MutableRefObject<Record<string, HTMLElement | null>>;
}) {
  if (source.kind === "note") {
    const sentences = source.text
      .replace(/\s+/g, " ")
      .trim()
      .split(/(?<=[.!?])\s+(?=[A-Z0-9])/g)
      .filter(Boolean)
      .map((text, si) => ({ id: `${source.id}:S${si + 1}`, text }));
    return (
      <p className="text-foreground/90">
        {sentences.map((s) => {
          const isActive = activeSource === s.id;
          return (
            <span
              key={s.id}
              ref={(el) => {
                sentenceRefs.current[s.id] = el;
              }}
              onClick={() => setActiveSource(s.id)}
              className={`cursor-pointer transition-colors ${
                isActive ? "rounded-sm bg-highlight/60 px-0.5" : "hover:bg-primary/5"
              }`}
            >
              {s.text}{" "}
            </span>
          );
        })}
      </p>
    );
  }
  if (source.kind === "whatsapp") {
    return (
      <ul className="space-y-1.5">
        {source.messages.map((m) => {
          const isActive = activeSource === m.id;
          return (
            <li
              key={m.id}
              ref={(el) => {
                sentenceRefs.current[m.id] = el;
              }}
              onClick={() => setActiveSource(m.id)}
              className={`cursor-pointer rounded-md border border-border px-3 py-1.5 transition ${
                isActive ? "border-primary bg-primary/5" : "hover:border-primary/40"
              }`}
            >
              <div className="text-[10px] uppercase tracking-wider text-muted-foreground">
                {m.sender}
                {m.timestamp ? ` · ${m.timestamp}` : ""}
              </div>
              <div className="text-foreground">{m.text}</div>
            </li>
          );
        })}
      </ul>
    );
  }
  // photo
  return (
    <ul className="space-y-1.5">
      {source.findings.map((f) => {
        const isActive = activeSource === f.id;
        return (
          <li
            key={f.id}
            ref={(el) => {
              sentenceRefs.current[f.id] = el;
            }}
            onClick={() => setActiveSource(f.id)}
            className={`cursor-pointer rounded-md border border-border px-3 py-1.5 transition ${
              isActive ? "border-primary bg-primary/5" : "hover:border-primary/40"
            }`}
          >
            <div className="font-medium text-foreground">{f.label}</div>
            {f.detail && <div className="text-muted-foreground">{f.detail}</div>}
          </li>
        );
      })}
    </ul>
  );
}

function PlanGroup({
  title,
  items,
  activeSource,
  setActiveSource,
}: {
  title: PlanSection;
  items: PlanItem[];
  activeSource: SourceId | null;
  setActiveSource: (id: SourceId | null) => void;
}) {
  return (
    <div>
      <h4 className="mb-2 border-b border-border pb-1.5 text-sm font-medium tracking-tight text-foreground">
        {title}
      </h4>
      <ul className="space-y-2.5">
        {items.map((item) => {
          const linked =
            activeSource && item.source_ids.includes(activeSource);
          const edge =
            item.emphasis === "danger"
              ? "border-l-risk-critical"
              : item.emphasis === "warn"
                ? "border-l-risk-high"
                : "border-l-transparent";
          return (
            <li
              key={item.id}
              onClick={() => item.source_ids[0] && setActiveSource(item.source_ids[0])}
              className={`cursor-pointer border-l-2 ${edge} pl-3 transition ${
                linked ? "bg-primary/5" : ""
              }`}
            >
              <div className="text-sm leading-snug text-foreground">{item.text}</div>
              {(item.caused_by || item.source_ids.length > 0) && (
                <div className="mt-0.5 text-[12px] text-muted-foreground">
                  {item.caused_by && <span>because {item.caused_by}</span>}
                  {item.caused_by && item.source_ids.length > 0 && <span> · </span>}
                  {item.source_ids.map((sid, i) => (
                    <span key={sid}>
                      {i > 0 && ", "}
                      <span
                        onClick={(e) => {
                          e.stopPropagation();
                          setActiveSource(sid);
                        }}
                        className={`font-mono tabular-nums transition ${
                          activeSource === sid
                            ? "text-primary underline"
                            : "hover:text-primary"
                        }`}
                      >
                        {sid}
                      </span>
                    </span>
                  ))}
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
