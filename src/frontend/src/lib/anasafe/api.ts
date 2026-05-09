import type { PreAnesthesiaState } from "./types";

const BASE = (import.meta.env?.VITE_BACKEND_URL as string | undefined) ?? "http://localhost:8000";

export interface BackendResult {
  state: PreAnesthesiaState;
  warnings: string[];
  confidence: number;
}

export async function fetchDemo(): Promise<BackendResult> {
  const res = await fetch(`${BASE}/api/demo`);
  if (!res.ok) throw new Error(`Backend /api/demo error: ${res.status}`);
  return res.json() as Promise<BackendResult>;
}

export async function extractTexts(
  texts: string[],
  patientId?: string,
): Promise<BackendResult> {
  const res = await fetch(`${BASE}/api/extract`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ texts, patient_id: patientId ?? null }),
  });
  if (!res.ok) throw new Error(`Backend /api/extract error: ${res.status}`);
  return res.json() as Promise<BackendResult>;
}

export async function uploadFiles(files: File[]): Promise<BackendResult> {
  const form = new FormData();
  for (const f of files) form.append("files", f);
  const res = await fetch(`${BASE}/api/upload`, {
    method: "POST",
    body: form,
  });
  if (!res.ok) throw new Error(`Backend /api/upload error: ${res.status}`);
  return res.json() as Promise<BackendResult>;
}

export async function checkHealth(): Promise<boolean> {
  try {
    const res = await fetch(`${BASE}/api/health`, { signal: AbortSignal.timeout(2000) });
    return res.ok;
  } catch {
    return false;
  }
}
