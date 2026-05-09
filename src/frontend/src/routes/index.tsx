import { createFileRoute } from "@tanstack/react-router";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  checkHealth,
  downloadSummaryPdf,
  extractTexts,
  fetchDemo,
  uploadFiles,
} from "@/lib/anasafe/api";
import type {
  BackendResult,
  PatientForm,
  PatientEnriched,
  ValidationStep,
  Verdict,
  VerdictFactor,
} from "@/lib/anasafe/api";

export const Route = createFileRoute("/")({
  component: AnaSafe,
  head: () => ({
    meta: [
      { title: "AnaSafe — Pre-anesthesia decision support" },
      {
        name: "description",
        content:
          "AnaSafe synthesizes a source-grounded anesthesia verdict from uploaded patient documents.",
      },
    ],
  }),
});

// ───────────────────────────────────────────────────────────────────────────
// Top-level component
// ───────────────────────────────────────────────────────────────────────────

type Stage = "landing" | "patient_form" | "analysis";
type RightView = "verdict" | "documents" | "validity" | "plan";

function AnaSafe() {
  const [stage, setStage] = useState<Stage>("landing");
  const [rightView, setRightView] = useState<RightView>("verdict");

  const [patient, setPatient] = useState<PatientForm>({
    name: "",
    age: undefined,
    sex: "M",
    blood_type: "",
    surgery_type: "",
    urgency: "elective",
  });

  const [bundle, setBundle] = useState<BackendResult | null>(null);
  const [extracting, setExtracting] = useState(false);
  const [backendOnline, setBackendOnline] = useState<boolean | null>(null);
  const [backendError, setBackendError] = useState<string | null>(null);
  const [pendingFiles, setPendingFiles] = useState<File[]>([]);
  const [toast, setToast] = useState<string | null>(null);
  const [showSummary, setShowSummary] = useState(false);
  const [showAgent, setShowAgent] = useState(false);

  const refreshBackendHealth = useCallback(() => {
    checkHealth().then(setBackendOnline);
  }, []);

  useEffect(() => {
    refreshBackendHealth();
  }, [refreshBackendHealth]);

  useEffect(() => {
    if (backendOnline !== false) return;
    const id = window.setInterval(refreshBackendHealth, 6000);
    return () => window.clearInterval(id);
  }, [backendOnline, refreshBackendHealth]);

  useEffect(() => {
    if (!toast) return;
    const id = window.setTimeout(() => setToast(null), 2400);
    return () => window.clearTimeout(id);
  }, [toast]);

  // ── Actions ──
  function newCase() {
    setStage("landing");
    setBundle(null);
    setPatient({ name: "", age: undefined, sex: "M", blood_type: "", surgery_type: "", urgency: "elective" });
    setPendingFiles([]);
    setBackendError(null);
    setRightView("verdict");
  }

  async function runDemo() {
    if (backendOnline !== true) {
      setToast("Start the backend first (./run-backend.sh).");
      return;
    }
    setExtracting(true);
    setBackendError(null);
    setStage("analysis");
    try {
      const res = await fetchDemo();
      setBundle(res);
      if (res.patient) setPatient(res.patient);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setBackendError(msg);
      setStage("landing");
    } finally {
      setExtracting(false);
    }
  }

  async function submitPatientForm(files: File[]) {
    if (!files.length) {
      setToast("Add at least one document (PDF / JSON / text) before continuing.");
      return;
    }
    if (backendOnline !== true) {
      setToast("Start the backend first (./run-backend.sh).");
      return;
    }
    setExtracting(true);
    setBackendError(null);
    setStage("analysis");
    try {
      const res = await uploadFiles(files, patient);
      setBundle(res);
      if (res.patient) setPatient(res.patient);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setBackendError(msg);
      setStage("patient_form");
    } finally {
      setExtracting(false);
    }
  }

  async function addMoreDocuments(files: File[]) {
    if (!files.length || !bundle) return;
    setExtracting(true);
    try {
      const newTexts: string[] = [];
      for (const f of files) {
        if (f.type === "application/pdf" || f.name.toLowerCase().endsWith(".pdf")) {
          // PDFs need to round-trip through /api/upload; fall back to that endpoint
          const res = await uploadFiles([f], patient);
          setBundle(res);
          continue;
        }
        if (f.name.toLowerCase().endsWith(".json")) {
          newTexts.push(await f.text());
          continue;
        }
        newTexts.push(await f.text());
      }
      if (newTexts.length) {
        const existingTexts = (bundle.documents ?? []).map((d) => d.text);
        const res = await extractTexts([...existingTexts, ...newTexts], patient);
        setBundle(res);
      }
      setToast(`Added ${files.length} document${files.length > 1 ? "s" : ""}.`);
    } catch (err) {
      setToast(err instanceof Error ? err.message : String(err));
    } finally {
      setExtracting(false);
    }
  }

  async function exportSummaryPdf() {
    if (!bundle?.verdict || !bundle?.patient) return;
    try {
      const blob = await downloadSummaryPdf({
        patient: bundle.patient,
        verdict: bundle.verdict,
        state: bundle.state,
        risk_scores: bundle.risk_scores,
      });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      const safe = (bundle.patient.name || "patient").toLowerCase().replace(/\s+/g, "_");
      a.download = `anasafe-summary-${safe}.pdf`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      setToast(err instanceof Error ? err.message : String(err));
    }
  }

  return (
    <div className="min-h-screen bg-background text-foreground">
      <AppHeader
        backendOnline={backendOnline}
        patient={patient}
        showPatient={stage === "analysis" && !!bundle?.patient}
        onNewCase={newCase}
        onRetry={refreshBackendHealth}
      />

      {stage === "landing" && (
        <Landing
          backendOnline={backendOnline}
          onRunDemo={runDemo}
          onPickUpload={() => setStage("patient_form")}
          backendError={backendError}
        />
      )}

      {stage === "patient_form" && (
        <PatientFormScreen
          patient={patient}
          setPatient={setPatient}
          pendingFiles={pendingFiles}
          setPendingFiles={setPendingFiles}
          onSubmit={() => submitPatientForm(pendingFiles)}
          onBack={() => setStage("landing")}
          backendOnline={backendOnline}
        />
      )}

      {stage === "analysis" && (
        <AnalysisScreen
          bundle={bundle}
          extracting={extracting}
          rightView={rightView}
          setRightView={setRightView}
          onAddDocuments={addMoreDocuments}
          onOpenSummary={() => setShowSummary(true)}
          onExportSummary={exportSummaryPdf}
          onOpenAgent={() => setShowAgent(true)}
        />
      )}

      {extracting && <AnalysisOverlay />}

      {showSummary && bundle?.patient && bundle?.verdict && (
        <SummaryDrawer
          patient={bundle.patient}
          verdict={bundle.verdict}
          state={bundle.state}
          onClose={() => setShowSummary(false)}
          onExport={exportSummaryPdf}
        />
      )}

      {showAgent && <AgentDrawer onClose={() => setShowAgent(false)} />}

      {toast && (
        <div className="fixed bottom-6 left-1/2 z-50 -translate-x-1/2 rounded-full border border-border bg-foreground px-4 py-2 text-xs font-medium text-background shadow-lg">
          {toast}
        </div>
      )}

      <footer className="border-t border-border">
        <div className="mx-auto max-w-[1320px] px-6 py-3 text-[11px] leading-relaxed text-muted-foreground">
          <span className="font-semibold text-foreground/80">AnaSafe</span> is decision support — every output requires independent clinician verification.
        </div>
      </footer>
    </div>
  );
}

// ───────────────────────────────────────────────────────────────────────────
// Header
// ───────────────────────────────────────────────────────────────────────────

function AppHeader({
  backendOnline,
  patient,
  showPatient,
  onNewCase,
  onRetry,
}: {
  backendOnline: boolean | null;
  patient: PatientForm;
  showPatient: boolean;
  onNewCase: () => void;
  onRetry: () => void;
}) {
  const urgencyColor =
    patient.urgency === "emergent" || patient.urgency === "life_saving"
      ? "bg-risk-critical-bg text-risk-critical"
      : patient.urgency === "urgent"
        ? "bg-risk-moderate-bg text-risk-moderate"
        : "bg-muted text-muted-foreground";

  return (
    <header className="border-b border-border bg-background">
      <div className="mx-auto flex max-w-[1320px] items-center justify-between gap-3 px-6 py-3">
        <div className="flex items-center gap-3">
          <div
            className="flex h-8 w-8 items-center justify-center rounded-md text-white"
            style={{ background: "var(--gradient-primary)" }}
          >
            <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2.4">
              <path d="M12 3 5 6v6c0 4.5 3 8.4 7 9 4-.6 7-4.5 7-9V6l-7-3Z" />
              <path d="M9 12h6M12 9v6" />
            </svg>
          </div>
          {showPatient ? (
            <div className="flex items-center gap-2.5">
              <div className="leading-tight">
                <div className="text-[10px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">
                  Patient
                </div>
                <div className="text-[14px] font-semibold tracking-tight text-foreground">
                  {patient.name || "Unknown"}
                </div>
                <div className="text-[11.5px] text-muted-foreground">
                  {[patient.age && patient.sex && `${patient.age}${patient.sex}`, patient.surgery_type]
                    .filter(Boolean)
                    .join(" · ") || "—"}
                </div>
              </div>
              {patient.urgency && (
                <span
                  className={`rounded-full px-2.5 py-1 text-[10.5px] font-semibold uppercase tracking-[0.14em] ${urgencyColor}`}
                >
                  {patient.urgency.replace("_", " ")}
                </span>
              )}
            </div>
          ) : (
            <div className="leading-tight">
              <h1 className="text-[15px] font-semibold tracking-tight">AnaSafe</h1>
              <p className="text-[10.5px] text-muted-foreground">Pre-anesthesia decision support</p>
            </div>
          )}
        </div>

        <div className="flex items-center gap-2">
          {backendOnline !== null && (
            <span
              title={
                backendOnline
                  ? "Analysis API reachable"
                  : "Analysis API unreachable — start ./run-backend.sh"
              }
              className={`flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-medium ${
                backendOnline ? "bg-risk-low-bg text-risk-low" : "bg-risk-moderate-bg text-risk-moderate"
              }`}
            >
              <span className={`h-1.5 w-1.5 rounded-full ${backendOnline ? "bg-risk-low" : "bg-risk-moderate"}`} />
              {backendOnline ? "API online" : "API offline"}
            </span>
          )}
          {backendOnline === false && (
            <button
              type="button"
              onClick={onRetry}
              className="rounded-md border border-border px-2 py-1 text-[11px] font-medium text-muted-foreground hover:border-primary hover:text-primary"
            >
              Retry
            </button>
          )}
          {showPatient && (
            <button
              onClick={onNewCase}
              className="rounded-md border border-border bg-background px-3 py-1.5 text-[11.5px] font-medium text-foreground transition hover:bg-accent"
            >
              New case
            </button>
          )}
        </div>
      </div>
    </header>
  );
}

// ───────────────────────────────────────────────────────────────────────────
// Landing
// ───────────────────────────────────────────────────────────────────────────

function Landing({
  backendOnline,
  onRunDemo,
  onPickUpload,
  backendError,
}: {
  backendOnline: boolean | null;
  onRunDemo: () => void;
  onPickUpload: () => void;
  backendError: string | null;
}) {
  const disabled = backendOnline !== true;
  return (
    <main className="mx-auto flex max-w-3xl flex-col items-center gap-10 px-6 py-20 text-center md:py-28">
      <div className="space-y-3">
        <h2 className="text-2xl font-semibold tracking-tight text-foreground md:text-3xl">
          What would you like to do?
        </h2>
        <p className="text-[14px] leading-relaxed text-muted-foreground">
          Upload patient documents to start a new case, or run the scripted demo.
        </p>
      </div>

      <div className="grid w-full gap-4 sm:grid-cols-2">
        <button
          type="button"
          onClick={onPickUpload}
          disabled={disabled}
          className="group relative flex flex-col items-start gap-3 rounded-2xl border-2 border-border bg-card px-6 py-7 text-left shadow-sm transition hover:-translate-y-0.5 hover:border-primary hover:shadow-lg disabled:cursor-not-allowed disabled:opacity-50"
        >
          <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary/10 text-primary">
            <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M12 4v12M12 4l-4 4M12 4l4 4" strokeLinecap="round" />
              <path d="M4 16v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2" strokeLinecap="round" />
            </svg>
          </span>
          <div>
            <div className="text-[16px] font-semibold tracking-tight text-foreground">Upload patient documents</div>
            <p className="mt-1 text-[12.5px] leading-relaxed text-muted-foreground">
              PDFs, JSON, plain text. Add patient name, age, sex, and reason for visit before analysis runs.
            </p>
          </div>
          <span className="mt-1 text-[12px] font-semibold text-primary">Continue →</span>
        </button>

        <button
          type="button"
          onClick={onRunDemo}
          disabled={disabled}
          className="group relative flex flex-col items-start gap-3 overflow-hidden rounded-2xl bg-primary px-6 py-7 text-left text-primary-foreground shadow-xl ring-4 ring-primary/15 transition hover:-translate-y-0.5 hover:ring-primary/25 disabled:cursor-not-allowed disabled:opacity-50"
        >
          <span
            className="pointer-events-none absolute inset-0 opacity-25"
            style={{ background: "var(--gradient-primary)" }}
          />
          <span className="relative flex h-10 w-10 items-center justify-center rounded-lg bg-white/20">
            <svg viewBox="0 0 24 24" className="h-5 w-5" fill="currentColor">
              <polygon points="6 4 20 12 6 20 6 4" />
            </svg>
          </span>
          <div className="relative">
            <div className="text-[16px] font-semibold tracking-tight">Run demo case</div>
            <p className="mt-1 text-[12.5px] leading-relaxed text-primary-foreground/80">
              67M, hip fracture, anticoagulated. Six clinical documents, full analysis.
            </p>
          </div>
          <span className="relative mt-1 inline-flex items-center gap-1 rounded-full bg-white/20 px-2.5 py-0.5 text-[11px] font-semibold uppercase tracking-[0.16em]">
            1-click
          </span>
        </button>
      </div>

      {backendOnline === false && (
        <p className="text-[12px] text-risk-moderate">
          Backend unreachable on <span className="font-mono text-[11px]">127.0.0.1:8010</span>. Start it with{" "}
          <span className="font-mono">./run-backend.sh</span>.
        </p>
      )}
      {backendError && <p className="max-w-md text-[12px] text-risk-high">{backendError}</p>}
    </main>
  );
}

// ───────────────────────────────────────────────────────────────────────────
// Patient form (between landing and analysis)
// ───────────────────────────────────────────────────────────────────────────

function PatientFormScreen({
  patient,
  setPatient,
  pendingFiles,
  setPendingFiles,
  onSubmit,
  onBack,
  backendOnline,
}: {
  patient: PatientForm;
  setPatient: (p: PatientForm) => void;
  pendingFiles: File[];
  setPendingFiles: (fs: File[]) => void;
  onSubmit: () => void;
  onBack: () => void;
  backendOnline: boolean | null;
}) {
  const inputRef = useRef<HTMLInputElement>(null);

  const valid =
    !!patient.name?.trim() &&
    typeof patient.age === "number" &&
    patient.age > 0 &&
    !!patient.surgery_type?.trim() &&
    pendingFiles.length > 0 &&
    backendOnline === true;

  function addFiles(fl: FileList | null) {
    if (!fl) return;
    setPendingFiles([...pendingFiles, ...Array.from(fl)]);
  }
  function removeFile(i: number) {
    setPendingFiles(pendingFiles.filter((_, j) => j !== i));
  }

  return (
    <main className="mx-auto flex max-w-3xl flex-col gap-6 px-6 py-12">
      <div className="flex items-center gap-2 text-[12px] text-muted-foreground">
        <button onClick={onBack} className="hover:text-primary">← Back</button>
        <span>·</span>
        <span>New case</span>
      </div>

      <div className="rounded-2xl border border-border bg-card p-6 shadow-sm">
        <h2 className="text-[18px] font-semibold tracking-tight text-foreground">Patient details</h2>
        <p className="mt-1 text-[12.5px] text-muted-foreground">
          These values appear in the top-left corner during analysis and on the exported PDF summary.
        </p>

        <div className="mt-5 grid gap-4 sm:grid-cols-2">
          <Field label="Full name *">
            <input
              type="text"
              autoFocus
              value={patient.name ?? ""}
              onChange={(e) => setPatient({ ...patient, name: e.target.value })}
              placeholder="e.g. Robert Hayes"
              className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground outline-none focus:border-primary"
            />
          </Field>

          <Field label="Age *">
            <input
              type="number"
              min={0}
              max={120}
              value={patient.age ?? ""}
              onChange={(e) => setPatient({ ...patient, age: e.target.value ? Number(e.target.value) : undefined })}
              placeholder="67"
              className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground outline-none focus:border-primary"
            />
          </Field>

          <Field label="Sex">
            <select
              value={patient.sex ?? "M"}
              onChange={(e) => setPatient({ ...patient, sex: e.target.value as "M" | "F" | "X" })}
              className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground outline-none focus:border-primary"
            >
              <option value="M">Male</option>
              <option value="F">Female</option>
              <option value="X">Other</option>
            </select>
          </Field>

          <Field label="Blood type">
            <select
              value={patient.blood_type ?? ""}
              onChange={(e) => setPatient({ ...patient, blood_type: e.target.value })}
              className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground outline-none focus:border-primary"
            >
              <option value="">Unknown</option>
              {["A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"].map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </Field>

          <Field label="Reason for visit / surgery *" full>
            <input
              type="text"
              value={patient.surgery_type ?? ""}
              onChange={(e) => setPatient({ ...patient, surgery_type: e.target.value })}
              placeholder="e.g. Hip fracture ORIF"
              className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground outline-none focus:border-primary"
            />
          </Field>

          <Field label="Urgency" full>
            <div className="flex flex-wrap gap-2">
              {(["elective", "urgent", "emergent", "life_saving"] as const).map((u) => {
                const active = patient.urgency === u;
                return (
                  <button
                    key={u}
                    type="button"
                    onClick={() => setPatient({ ...patient, urgency: u })}
                    className={`rounded-full px-3 py-1 text-[11.5px] font-semibold uppercase tracking-[0.12em] transition ${
                      active
                        ? "bg-primary text-primary-foreground shadow-sm"
                        : "border border-border bg-background text-muted-foreground hover:border-primary hover:text-primary"
                    }`}
                  >
                    {u.replace("_", " ")}
                  </button>
                );
              })}
            </div>
          </Field>
        </div>
      </div>

      <div className="rounded-2xl border border-border bg-card p-6 shadow-sm">
        <div className="flex items-center justify-between">
          <h3 className="text-[16px] font-semibold tracking-tight">Patient documents</h3>
          <span className="rounded-full bg-muted px-2 py-0.5 font-mono text-[11px] tabular-nums text-muted-foreground">
            {pendingFiles.length}
          </span>
        </div>
        <p className="mt-1 text-[12.5px] text-muted-foreground">
          PDFs, JSON, or plain text. The pipeline reads everything before producing a verdict.
        </p>

        <label
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => {
            e.preventDefault();
            addFiles(e.dataTransfer.files);
          }}
          className="mt-4 flex cursor-pointer flex-col items-center gap-2 rounded-xl border-2 border-dashed border-border bg-background py-8 text-center transition hover:border-primary"
        >
          <svg viewBox="0 0 24 24" className="h-8 w-8 text-primary" fill="none" stroke="currentColor" strokeWidth="1.8">
            <path d="M12 16V4M12 4l-4 4M12 4l4 4" strokeLinecap="round" />
            <path d="M4 16v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2" strokeLinecap="round" />
          </svg>
          <span className="font-semibold text-foreground">Drop files here or click to browse</span>
          <span className="text-[11.5px] text-muted-foreground">PDF · JSON · TXT · MD</span>
          <input
            ref={inputRef}
            type="file"
            multiple
            accept=".pdf,.json,.txt,.md,application/pdf,application/json,text/plain"
            className="hidden"
            onChange={(e) => addFiles(e.target.files)}
          />
        </label>

        {pendingFiles.length > 0 && (
          <ul className="mt-3 space-y-1.5">
            {pendingFiles.map((f, i) => (
              <li
                key={`${f.name}-${i}`}
                className="flex items-center justify-between rounded-md border border-border bg-background px-3 py-1.5 text-[12px]"
              >
                <span className="truncate font-medium text-foreground">{f.name}</span>
                <button
                  onClick={() => removeFile(i)}
                  className="text-muted-foreground hover:text-risk-high"
                  title="Remove"
                >
                  ✕
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="flex items-center justify-end gap-3">
        <button
          onClick={onBack}
          className="rounded-md border border-border px-4 py-2 text-[13px] font-medium text-foreground hover:bg-accent"
        >
          Cancel
        </button>
        <button
          onClick={onSubmit}
          disabled={!valid}
          className="rounded-lg bg-primary px-5 py-2.5 text-[13px] font-semibold text-primary-foreground shadow-sm transition hover:bg-primary/90 disabled:opacity-50"
        >
          Run analysis →
        </button>
      </div>
    </main>
  );
}

function Field({
  label,
  children,
  full,
}: {
  label: string;
  children: React.ReactNode;
  full?: boolean;
}) {
  return (
    <label className={`flex flex-col gap-1.5 ${full ? "sm:col-span-2" : ""}`}>
      <span className="text-[10.5px] font-semibold uppercase tracking-[0.16em] text-muted-foreground">
        {label}
      </span>
      {children}
    </label>
  );
}

// ───────────────────────────────────────────────────────────────────────────
// Analysis screen — left sidebar + right pane
// ───────────────────────────────────────────────────────────────────────────

function AnalysisScreen({
  bundle,
  extracting,
  rightView,
  setRightView,
  onAddDocuments,
  onOpenSummary,
  onExportSummary,
  onOpenAgent,
}: {
  bundle: BackendResult | null;
  extracting: boolean;
  rightView: RightView;
  setRightView: (v: RightView) => void;
  onAddDocuments: (files: File[]) => void;
  onOpenSummary: () => void;
  onExportSummary: () => void;
  onOpenAgent: () => void;
}) {
  if (!bundle && !extracting) {
    return (
      <main className="mx-auto max-w-2xl px-6 py-12 text-center text-[13px] text-muted-foreground">
        Waiting for analysis to start…
      </main>
    );
  }

  return (
    <main className="mx-auto grid max-w-[1320px] gap-6 px-6 py-6 lg:grid-cols-[260px_minmax(0,1fr)]">
      <Sidebar
        bundle={bundle}
        rightView={rightView}
        setRightView={setRightView}
        onAddDocuments={onAddDocuments}
      />
      <section className="min-w-0 space-y-5">
        {bundle && rightView === "verdict" && (
          <VerdictPane
            bundle={bundle}
            onOpenSummary={onOpenSummary}
            onExportSummary={onExportSummary}
            onOpenAgent={onOpenAgent}
          />
        )}
        {bundle && rightView === "documents" && <DocumentsPane bundle={bundle} />}
        {bundle && rightView === "validity" && <ValidityPane steps={bundle.validation_steps ?? []} />}
        {bundle && rightView === "plan" && <PlanPane bundle={bundle} />}
      </section>
    </main>
  );
}

// ───────────────────────────────────────────────────────────────────────────
// Sidebar
// ───────────────────────────────────────────────────────────────────────────

function Sidebar({
  bundle,
  rightView,
  setRightView,
  onAddDocuments,
}: {
  bundle: BackendResult | null;
  rightView: RightView;
  setRightView: (v: RightView) => void;
  onAddDocuments: (files: File[]) => void;
}) {
  const inputRef = useRef<HTMLInputElement>(null);

  return (
    <aside className="flex flex-col gap-3">
      <div className="rounded-2xl border border-border bg-card p-4 shadow-sm">
        <div className="flex items-center justify-between">
          <h3 className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">
            Patient documents
          </h3>
          <span className="rounded-full bg-muted px-2 py-0.5 font-mono text-[10px] tabular-nums text-muted-foreground">
            {bundle?.documents?.length ?? 0}
          </span>
        </div>

        <label
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => {
            e.preventDefault();
            onAddDocuments(Array.from(e.dataTransfer.files));
          }}
          className="mt-3 flex cursor-pointer flex-col items-center gap-1 rounded-md border border-dashed border-border bg-background px-3 py-3 text-center transition hover:border-primary"
        >
          <svg viewBox="0 0 24 24" className="h-4 w-4 text-primary" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M12 16V4M12 4l-4 4M12 4l4 4" strokeLinecap="round" />
            <path d="M4 16v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2" strokeLinecap="round" />
          </svg>
          <span className="text-[11.5px] font-semibold text-foreground">Drop more documents</span>
          <span className="text-[10px] text-muted-foreground">PDF · JSON · TXT</span>
          <input
            ref={inputRef}
            type="file"
            multiple
            accept=".pdf,.json,.txt,.md,application/pdf,application/json,text/plain"
            className="hidden"
            onChange={(e) => {
              if (e.target.files) onAddDocuments(Array.from(e.target.files));
              if (inputRef.current) inputRef.current.value = "";
            }}
          />
        </label>

        <SidebarButton
          active={rightView === "documents"}
          onClick={() => setRightView("documents")}
          label="See documents"
          count={bundle?.documents?.length ?? 0}
        />
      </div>

      <SidebarButton
        active={rightView === "validity"}
        onClick={() => setRightView("validity")}
        label="Check validity"
        accent="info"
        count={bundle?.validation_steps?.length ?? 0}
      />
      <SidebarButton
        active={rightView === "plan"}
        onClick={() => setRightView("plan")}
        label="See anesthesia plan"
        accent="primary"
      />
      <SidebarButton
        active={rightView === "verdict"}
        onClick={() => setRightView("verdict")}
        label="← Back to verdict"
        accent="muted"
      />
    </aside>
  );
}

function SidebarButton({
  active,
  onClick,
  label,
  count,
  accent = "default",
}: {
  active: boolean;
  onClick: () => void;
  label: string;
  count?: number;
  accent?: "primary" | "info" | "muted" | "default";
}) {
  const base =
    "flex w-full items-center justify-between rounded-xl border px-4 py-3 text-[12.5px] font-semibold transition";
  const variant = active
    ? "border-primary bg-primary text-primary-foreground shadow-sm"
    : accent === "primary"
      ? "border-border bg-card text-foreground hover:border-primary hover:text-primary"
      : accent === "info"
        ? "border-border bg-card text-foreground hover:border-primary hover:text-primary"
        : accent === "muted"
          ? "border-dashed border-border bg-transparent text-muted-foreground hover:text-foreground"
          : "border-border bg-card text-foreground hover:border-primary hover:text-primary";
  return (
    <button onClick={onClick} className={`${base} ${variant}`}>
      <span>{label}</span>
      {typeof count === "number" && count > 0 && (
        <span
          className={`rounded-full px-2 py-0.5 font-mono text-[10px] tabular-nums ${
            active ? "bg-white/20 text-white" : "bg-muted text-muted-foreground"
          }`}
        >
          {count}
        </span>
      )}
    </button>
  );
}

// ───────────────────────────────────────────────────────────────────────────
// Verdict pane
// ───────────────────────────────────────────────────────────────────────────

function VerdictPane({
  bundle,
  onOpenSummary,
  onExportSummary,
  onOpenAgent,
}: {
  bundle: BackendResult;
  onOpenSummary: () => void;
  onExportSummary: () => void;
  onOpenAgent: () => void;
}) {
  const verdict = bundle.verdict;
  if (!verdict) {
    return (
      <div className="rounded-2xl border border-dashed border-border bg-muted/20 p-8 text-center text-[13px] text-muted-foreground">
        No verdict computed.
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <VerdictCard verdict={verdict} />
      <FactorRow title="Cautions" factors={verdict.cautions} accent="strong" />
      <FactorRow title="Important info" factors={verdict.important_info} accent="soft" />
      <PatientSummaryCard onView={onOpenSummary} onExport={onExportSummary} />
      <AgentCard onOpen={onOpenAgent} />
    </div>
  );
}

function VerdictCard({ verdict }: { verdict: Verdict }) {
  const ok = verdict.label === "OK";
  const tint = ok
    ? { bg: "bg-risk-low-bg",       text: "text-risk-low",       ring: "ring-risk-low/30",       circle: "stroke-risk-low" }
    : { bg: "bg-risk-critical-bg", text: "text-risk-critical", ring: "ring-risk-critical/30", circle: "stroke-risk-critical" };

  return (
    <div
      className={`relative flex flex-col gap-4 rounded-3xl border border-border ${tint.bg} px-7 py-6 shadow-sm sm:flex-row sm:items-center sm:justify-between`}
      style={{ boxShadow: "var(--shadow-card)" }}
    >
      <div className="min-w-0 flex-1">
        <div className={`text-[11px] font-semibold uppercase tracking-[0.18em] ${tint.text}`}>
          Verdict
        </div>
        <h2 className={`mt-1 text-[26px] font-semibold leading-tight tracking-tight ${tint.text}`}>
          {ok ? "Anesthesia: cleared to proceed" : "Anesthesia: hold for review"}
        </h2>
        <p className="mt-2 max-w-xl text-[13px] leading-relaxed text-foreground/85">
          {verdict.subtitle}
        </p>
        <div className="mt-3 inline-flex items-center gap-2 rounded-md bg-background/60 px-2.5 py-1 text-[11px] text-muted-foreground">
          <span>Threshold</span>
          <span className="font-mono font-semibold text-foreground">≥ {verdict.threshold_pct}%</span>
          <span className="text-muted-foreground/60">to proceed</span>
        </div>
      </div>
      <ConfidenceCircle pct={verdict.confidence_pct} className={tint.circle} ok={ok} />
    </div>
  );
}

function ConfidenceCircle({
  pct,
  className,
  ok,
}: {
  pct: number;
  className: string;
  ok: boolean;
}) {
  const r = 44;
  const c = 2 * Math.PI * r;
  const filled = c * (pct / 100);
  return (
    <div className="relative flex h-28 w-28 shrink-0 items-center justify-center">
      <svg viewBox="0 0 100 100" className="h-full w-full -rotate-90">
        <circle cx="50" cy="50" r={r} className="stroke-border" strokeWidth="6" fill="none" />
        <circle
          cx="50"
          cy="50"
          r={r}
          className={`${className} transition-[stroke-dasharray] duration-700`}
          strokeWidth="6"
          fill="none"
          strokeLinecap="round"
          strokeDasharray={`${filled} ${c}`}
        />
      </svg>
      <div className="absolute flex flex-col items-center leading-none">
        <span className={`font-mono text-[24px] font-semibold tabular-nums ${ok ? "text-risk-low" : "text-risk-critical"}`}>
          {pct}%
        </span>
        <span className="mt-0.5 text-[9.5px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">
          confidence
        </span>
      </div>
    </div>
  );
}

function FactorRow({
  title,
  factors,
  accent,
}: {
  title: string;
  factors: VerdictFactor[];
  accent: "strong" | "soft";
}) {
  if (factors.length === 0) {
    return (
      <div>
        <h4 className="mb-2 text-[10.5px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">
          {title}
        </h4>
        <p className="rounded-xl border border-dashed border-border px-4 py-5 text-center text-[12px] text-muted-foreground">
          None surfaced.
        </p>
      </div>
    );
  }
  return (
    <div>
      <h4 className="mb-2 flex items-center gap-2 text-[10.5px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">
        {accent === "strong" ? (
          <svg viewBox="0 0 24 24" className="h-3.5 w-3.5 text-risk-high" fill="none" stroke="currentColor" strokeWidth="2.4">
            <path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
            <line x1="12" y1="9" x2="12" y2="13" strokeLinecap="round" />
            <line x1="12" y1="17" x2="12.01" y2="17" strokeLinecap="round" />
          </svg>
        ) : (
          <svg viewBox="0 0 24 24" className="h-3.5 w-3.5 text-muted-foreground" fill="none" stroke="currentColor" strokeWidth="2.4">
            <circle cx="12" cy="12" r="9" />
            <path d="M12 8v4M12 16h.01" strokeLinecap="round" />
          </svg>
        )}
        {title}
      </h4>
      <div className="grid gap-3 sm:grid-cols-3">
        {factors.map((f, i) => (
          <FactorCard key={i} factor={f} accent={accent} />
        ))}
      </div>
    </div>
  );
}

function FactorCard({ factor, accent }: { factor: VerdictFactor; accent: "strong" | "soft" }) {
  const sevColor =
    factor.severity === "critical"
      ? "border-l-risk-critical"
      : factor.severity === "high"
        ? "border-l-risk-high"
        : factor.severity === "moderate"
          ? "border-l-risk-moderate"
          : "border-l-border";
  const chipBg =
    factor.severity === "critical"
      ? "bg-risk-critical-bg text-risk-critical"
      : factor.severity === "high"
        ? "bg-risk-high-bg text-risk-high"
        : factor.severity === "moderate"
          ? "bg-risk-moderate-bg text-risk-moderate"
          : "bg-muted text-muted-foreground";
  return (
    <div
      className={`flex h-full flex-col rounded-xl border bg-card px-3.5 py-3 shadow-sm border-l-[3px] ${sevColor} ${
        accent === "strong" ? "border-border" : "border-border"
      }`}
    >
      <div className="flex flex-wrap items-center gap-1.5">
        <span className={`rounded-full px-2 py-0.5 text-[9.5px] font-semibold uppercase tracking-[0.12em] ${chipBg}`}>
          {factor.severity}
        </span>
        <span className="text-[10px] font-mono text-muted-foreground">w {Math.round(factor.weight * 100)}%</span>
      </div>
      <div className="mt-1.5 text-[13px] font-semibold leading-snug text-foreground">{factor.title}</div>
      <p className="mt-1 text-[11.5px] leading-relaxed text-muted-foreground">{factor.detail}</p>
      {factor.source_snippet && (
        <div className="mt-2 rounded-md border border-dashed border-border bg-muted/20 px-2 py-1.5 text-[10.5px] leading-relaxed text-foreground/80">
          <span className="font-semibold text-muted-foreground">Excerpt: </span>
          <q>{factor.source_snippet}</q>
        </div>
      )}
    </div>
  );
}

// ───────────────────────────────────────────────────────────────────────────
// Patient summary card (clickable: View / Export PDF)
// ───────────────────────────────────────────────────────────────────────────

function PatientSummaryCard({
  onView,
  onExport,
}: {
  onView: () => void;
  onExport: () => void;
}) {
  return (
    <div className="flex items-center justify-between rounded-2xl border border-border bg-card px-5 py-4 shadow-sm">
      <div>
        <div className="text-[10.5px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">
          Patient summary
        </div>
        <div className="mt-0.5 text-[14px] font-semibold tracking-tight text-foreground">
          One-page recap of the case for handoff
        </div>
      </div>
      <div className="flex gap-2">
        <button
          onClick={onView}
          className="rounded-md border border-border bg-background px-3 py-1.5 text-[12px] font-medium text-foreground hover:border-primary hover:text-primary"
        >
          View
        </button>
        <button
          onClick={onExport}
          className="rounded-md bg-foreground px-3 py-1.5 text-[12px] font-semibold text-background hover:opacity-90"
        >
          Export as PDF
        </button>
      </div>
    </div>
  );
}

// ───────────────────────────────────────────────────────────────────────────
// Robot Ana agent placeholder
// ───────────────────────────────────────────────────────────────────────────

function AgentCard({ onOpen }: { onOpen: () => void }) {
  return (
    <div className="flex items-center gap-4 rounded-2xl border border-dashed border-border bg-muted/20 px-5 py-4">
      <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-full bg-primary/15 text-primary">
        <svg viewBox="0 0 24 24" className="h-6 w-6" fill="none" stroke="currentColor" strokeWidth="1.8">
          <rect x="4" y="7" width="16" height="12" rx="3" />
          <circle cx="9" cy="13" r="1.2" fill="currentColor" />
          <circle cx="15" cy="13" r="1.2" fill="currentColor" />
          <path d="M12 4v3M9 19v2M15 19v2" strokeLinecap="round" />
        </svg>
      </div>
      <div className="flex-1">
        <div className="text-[10.5px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">
          Robot Ana
        </div>
        <div className="text-[13.5px] font-semibold text-foreground">Operations agent (coming soon)</div>
        <p className="mt-0.5 text-[11.5px] text-muted-foreground">
          Will book theatre rooms, schedule pre-op blood draws, and check anesthesia availability.
        </p>
      </div>
      <button
        onClick={onOpen}
        className="rounded-md border border-border bg-background px-3 py-1.5 text-[12px] font-medium text-foreground hover:border-primary hover:text-primary"
      >
        Start a chat
      </button>
    </div>
  );
}

function AgentDrawer({ onClose }: { onClose: () => void }) {
  const suggestions = [
    "See available operating rooms now / in 1h",
    "Book a meeting to draw blood for INR & coag panel",
    "Check anesthesia consultant availability for the next 2h",
    "Schedule a senior anaesthesiologist review for this case",
  ];
  return (
    <>
      <div className="fixed inset-0 z-30 bg-foreground/30" onClick={onClose} />
      <aside className="fixed right-0 top-0 z-40 flex h-full w-full max-w-md flex-col border-l border-border bg-card shadow-2xl">
        <div className="flex items-center justify-between border-b border-border px-5 py-3">
          <div className="leading-tight">
            <div className="text-[10.5px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">
              Robot Ana
            </div>
            <div className="text-[14px] font-semibold tracking-tight text-foreground">
              Operations chat (placeholder)
            </div>
          </div>
          <button onClick={onClose} className="rounded-md p-1 text-muted-foreground hover:bg-muted">
            ✕
          </button>
        </div>
        <div className="flex-1 space-y-3 overflow-y-auto px-5 py-4">
          <p className="rounded-lg border border-dashed border-border bg-muted/30 px-3 py-2 text-[12px] text-muted-foreground">
            This is a demo placeholder — the live integration with hospital scheduling is not wired yet.
            Below are example tasks Robot Ana will eventually handle.
          </p>
          <ul className="space-y-2">
            {suggestions.map((s) => (
              <li
                key={s}
                className="rounded-lg border border-border bg-background px-3 py-2 text-[12.5px] text-foreground"
              >
                {s}
              </li>
            ))}
          </ul>
        </div>
        <div className="border-t border-border px-5 py-3">
          <input
            disabled
            placeholder="Chat with Ana (disabled in this prototype)"
            className="w-full rounded-md border border-input bg-muted px-3 py-2 text-[12px] text-muted-foreground"
          />
        </div>
      </aside>
    </>
  );
}

// ───────────────────────────────────────────────────────────────────────────
// Documents pane
// ───────────────────────────────────────────────────────────────────────────

function DocumentsPane({ bundle }: { bundle: BackendResult }) {
  const docs = bundle.documents ?? [];
  return (
    <div className="space-y-3">
      <h3 className="text-[16px] font-semibold tracking-tight">Documents in the case</h3>
      {docs.length === 0 ? (
        <p className="rounded-md border border-dashed border-border px-3 py-6 text-center text-[12px] text-muted-foreground">
          No documents in the case.
        </p>
      ) : (
        docs.map((d) => (
          <div key={d.id} className="rounded-2xl border border-border bg-card p-4">
            <div className="flex items-center gap-2">
              <span className="font-mono text-[10px] tabular-nums text-muted-foreground">{d.id}</span>
              <span className="text-[13.5px] font-semibold text-foreground">{d.title}</span>
              {d.document_date && (
                <span className="ml-auto text-[10.5px] text-muted-foreground">{d.document_date}</span>
              )}
            </div>
            <p className="mt-2 whitespace-pre-line text-[12.5px] leading-relaxed text-foreground/90">
              {d.text}
            </p>
          </div>
        ))
      )}
    </div>
  );
}

// ───────────────────────────────────────────────────────────────────────────
// Validity pane
// ───────────────────────────────────────────────────────────────────────────

function ValidityPane({ steps }: { steps: ValidationStep[] }) {
  if (steps.length === 0) {
    return (
      <p className="rounded-md border border-dashed border-border px-3 py-6 text-center text-[12px] text-muted-foreground">
        No validation steps recorded.
      </p>
    );
  }
  const tone = (s: ValidationStep["status"]) =>
    s === "pass"
      ? "bg-risk-low text-white"
      : s === "warn"
        ? "bg-risk-moderate text-white"
        : s === "fail"
          ? "bg-risk-high text-white"
          : "bg-muted text-muted-foreground";
  return (
    <div className="space-y-3">
      <h3 className="text-[16px] font-semibold tracking-tight">Pipeline validity</h3>
      <p className="text-[12px] text-muted-foreground">
        Each step that ran during analysis, whether it passed, and how it shaped the verdict.
      </p>
      <ol className="space-y-2">
        {steps.map((s, i) => (
          <li key={s.id} className="rounded-2xl border border-border bg-card px-4 py-3">
            <div className="flex items-center gap-3">
              <span
                className={`flex h-7 w-7 items-center justify-center rounded-full font-mono text-[11px] font-semibold ${tone(s.status)}`}
              >
                {i + 1}
              </span>
              <span className="text-[13.5px] font-semibold text-foreground">{s.title}</span>
              <span
                className={`ml-auto rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.14em] ${tone(s.status)}`}
              >
                {s.status === "pass" ? "passed" : s.status === "warn" ? "caution" : s.status === "fail" ? "blocking" : "info"}
              </span>
            </div>
            <p className="mt-1.5 text-[12px] leading-relaxed text-foreground/80">{s.summary}</p>
            <p className="mt-1 border-l-2 border-primary/30 pl-2 text-[11.5px] leading-relaxed text-muted-foreground">
              Decision impact — {s.impact}
            </p>
          </li>
        ))}
      </ol>
    </div>
  );
}

// ───────────────────────────────────────────────────────────────────────────
// Plan pane
// ───────────────────────────────────────────────────────────────────────────

function PlanPane({ bundle }: { bundle: BackendResult }) {
  const factors = bundle.verdict?.all_factors ?? [];
  const state = bundle.state;
  return (
    <div className="space-y-4">
      <h3 className="text-[16px] font-semibold tracking-tight">Anesthesia plan</h3>
      <PlanGroup
        title="Drugs to AVOID"
        items={[
          ...state.allergies.map((a) => `${cap(a.substance)}${a.reaction ? ` — ${a.reaction}` : ""}`),
          ...factors
            .filter((f) => /succinyl/i.test(f.detail) || /contraindicated/i.test(f.detail))
            .map((f) => f.detail),
        ]}
      />
      <PlanGroup
        title="Required setup"
        items={(() => {
          const out: string[] = [];
          if (state.airway_flags.length > 0)
            out.push("Difficult airway cart, video laryngoscopy, awake fibreoptic backup.");
          if (state.implants_or_devices.some((d) => /pacemaker|icd/i.test(d.device)))
            out.push("Magnet & bipolar cautery; confirm last device interrogation.");
          if (state.anticoagulants.length > 0)
            out.push("Reversal agent on standby (4F-PCC / andexanet alfa).");
          if (state.labs.some((l) => l.test === "potassium" && l.value > 5.5))
            out.push("Avoid succinylcholine; use rocuronium with sugammadex on standby.");
          if (out.length === 0) out.push("Standard setup is sufficient.");
          return out;
        })()}
      />
      <PlanGroup
        title="Recommended monitoring"
        items={[
          "Standard ASA monitors + arterial line for high-risk cases.",
          state.cardiac_risks.length > 0 ? "Continuous 5-lead ECG with ST analysis." : "5-lead ECG, baseline rhythm strip.",
          state.renal_metabolic_risks.length > 0 ? "Hourly urine output via Foley." : "Standard temperature & urine output.",
        ]}
      />
      <PlanGroup
        title="Lab/data gaps to close before induction"
        items={[
          ...(bundle.warnings ?? []).map((w) => w.replace(/^\[[^\]]+\]\s*/, "")),
          ...(state.anticoagulants.some((a) => !a.last_dose_hours_ago) ? ["Confirm exact time of last anticoagulant dose."] : []),
        ].slice(0, 6)}
      />
    </div>
  );
}

function PlanGroup({ title, items }: { title: string; items: string[] }) {
  if (items.length === 0) return null;
  return (
    <div className="rounded-2xl border border-border bg-card p-4">
      <h4 className="text-[10.5px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">{title}</h4>
      <ul className="mt-2 space-y-1.5">
        {items.map((it, i) => (
          <li key={i} className="flex gap-2 text-[12.5px] leading-relaxed text-foreground/90">
            <span className="text-primary">•</span>
            <span>{it}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

// ───────────────────────────────────────────────────────────────────────────
// Patient summary drawer
// ───────────────────────────────────────────────────────────────────────────

function SummaryDrawer({
  patient,
  verdict,
  state,
  onClose,
  onExport,
}: {
  patient: PatientEnriched;
  verdict: Verdict;
  state: BackendResult["state"];
  onClose: () => void;
  onExport: () => void;
}) {
  const rows = useMemo(
    () => [
      ["Name", patient.name || "—"],
      ["Age", patient.age != null ? String(patient.age) : "—"],
      ["Sex", patient.sex || "—"],
      ["Blood type", patient.blood_type || "Unknown"],
      ["Surgery", patient.surgery_type || "—"],
      ["Urgency", patient.urgency || "—"],
      ["Allergies", patient.allergies_summary || "None on record"],
      ["Patient ID", patient.id || "—"],
    ],
    [patient],
  );
  return (
    <>
      <div className="fixed inset-0 z-30 bg-foreground/30" onClick={onClose} />
      <aside className="fixed right-0 top-0 z-40 flex h-full w-full max-w-lg flex-col border-l border-border bg-card shadow-2xl">
        <div className="flex items-center justify-between border-b border-border px-5 py-3">
          <div className="leading-tight">
            <div className="text-[10.5px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">
              Patient summary
            </div>
            <div className="text-[15px] font-semibold tracking-tight text-foreground">
              {patient.name || "—"}
            </div>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={onExport}
              className="rounded-md bg-foreground px-3 py-1.5 text-[12px] font-semibold text-background hover:opacity-90"
            >
              Export PDF
            </button>
            <button onClick={onClose} className="rounded-md p-1 text-muted-foreground hover:bg-muted">
              ✕
            </button>
          </div>
        </div>
        <div className="flex-1 space-y-4 overflow-y-auto px-5 py-4 text-[13px]">
          <div
            className={`rounded-xl px-4 py-3 ${
              verdict.label === "OK" ? "bg-risk-low-bg text-risk-low" : "bg-risk-critical-bg text-risk-critical"
            }`}
          >
            <div className="text-[10.5px] font-semibold uppercase tracking-[0.18em]">Verdict</div>
            <div className="mt-0.5 text-[16px] font-semibold tracking-tight">
              {verdict.label === "OK" ? "Cleared to proceed" : "Hold for review"} · {verdict.confidence_pct}%
            </div>
            <p className="mt-1 text-[12px] leading-relaxed">{verdict.subtitle}</p>
          </div>

          <div>
            <h4 className="text-[10.5px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">
              Demographics
            </h4>
            <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-2">
              {rows.map(([k, v]) => (
                <div key={k}>
                  <dt className="text-[10.5px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
                    {k}
                  </dt>
                  <dd className="text-[12.5px] font-medium text-foreground">{v}</dd>
                </div>
              ))}
            </dl>
          </div>

          <div>
            <h4 className="text-[10.5px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">
              Clinical findings
            </h4>
            <ul className="mt-2 space-y-1">
              {state.allergies.map((a, i) => (
                <li key={`al-${i}`} className="text-[12.5px] text-foreground/90">
                  • Allergy — {a.substance}
                  {a.reaction ? ` (${a.reaction})` : ""}
                </li>
              ))}
              {state.anticoagulants.map((ac, i) => (
                <li key={`ac-${i}`} className="text-[12.5px] text-foreground/90">
                  • Anticoagulant — {ac.drug}
                  {ac.last_dose_hours_ago != null ? ` (~${ac.last_dose_hours_ago}h ago)` : " (timing unknown)"}
                </li>
              ))}
              {state.labs.map((l, i) => (
                <li key={`l-${i}`} className="text-[12.5px] text-foreground/90">
                  • {cap(l.test)} — {l.value} {l.unit}
                </li>
              ))}
              {state.airway_flags.map((af, i) => (
                <li key={`a-${i}`} className="text-[12.5px] text-foreground/90">
                  • Airway — {af.flag}
                </li>
              ))}
              {state.implants_or_devices.map((d, i) => (
                <li key={`d-${i}`} className="text-[12.5px] text-foreground/90">
                  • Device — {d.device}
                </li>
              ))}
            </ul>
          </div>

          <p className="rounded-md border border-dashed border-border bg-muted/30 px-3 py-2 text-[11px] italic text-muted-foreground">
            Decision-support only. Requires independent clinician verification before any anesthesia or surgical action.
          </p>
        </div>
      </aside>
    </>
  );
}

// ───────────────────────────────────────────────────────────────────────────
// Loading overlay
// ───────────────────────────────────────────────────────────────────────────

const ANALYSIS_PIPELINE_STEPS = [
  "Ingesting all documents",
  "Extracting structured facts (Claude)",
  "Bayesian validation across documents",
  "Risk scoring (RCRI, HAS-BLED, ASA, DOAC)",
  "Computing verdict + confidence",
];

function AnalysisOverlay() {
  const steps = ANALYSIS_PIPELINE_STEPS;
  const [activeIdx, setActiveIdx] = useState(0);

  useEffect(() => {
    const id = window.setInterval(() => {
      setActiveIdx((i) => (i + 1) % steps.length);
    }, 1100);
    return () => window.clearInterval(id);
  }, [steps.length]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-foreground/45 backdrop-blur-sm">
      <div className="w-[420px] max-w-[92vw] rounded-2xl border border-border bg-card p-7 shadow-2xl">
        <div className="flex items-center gap-2 text-[10.5px] font-semibold uppercase tracking-[0.18em] text-primary">
          <span className="inline-block h-2 w-2 animate-pulse rounded-full bg-primary" />
          Analyzing
        </div>
        <h3 className="mt-1.5 text-[18px] font-semibold tracking-tight text-foreground">
          Reading every document before answering
        </h3>
        <p className="mt-2 text-[12.5px] leading-relaxed text-muted-foreground">
          Nothing is shown until ingestion, extraction, validation, risk scoring, and verdict computation
          finish.
        </p>
        <ul className="mt-5 space-y-2.5">
          {steps.map((s, i) => {
            const active = i === activeIdx;
            return (
              <li key={s} className="flex items-center gap-3">
                <span
                  className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[11px] font-semibold transition ${
                    active ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground"
                  }`}
                >
                  {active ? <span className="inline-block h-2 w-2 animate-pulse rounded-full bg-white" /> : i + 1}
                </span>
                <span className={`text-[13px] ${active ? "font-medium text-foreground" : "text-muted-foreground"}`}>
                  {s}
                </span>
              </li>
            );
          })}
        </ul>
        <div className="mt-5 h-1 w-full overflow-hidden rounded-full bg-muted">
          <div
            className="h-full animate-[anasafe-bar_1.6s_ease-in-out_infinite] rounded-full"
            style={{ background: "var(--gradient-primary)", width: "40%" }}
          />
        </div>
      </div>
    </div>
  );
}

// ───────────────────────────────────────────────────────────────────────────
// Helpers
// ───────────────────────────────────────────────────────────────────────────

function cap(s: string) {
  return s.charAt(0).toUpperCase() + s.slice(1);
}
