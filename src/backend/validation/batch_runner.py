"""
Batch validator — runs the analysis pipeline on a directory of ground-truth
patient cases and reports how many cases it agrees with.

Layout expected on disk (each case is one folder):

    cases/
      patient_001/
        ground_truth.json
        documents/
          ed_triage.txt
          medlist.json
          labs.pdf
        ...
      patient_002/
        ...

`ground_truth.json` keys:

    {
      "patient": { "name": "...", "age": 67, "sex": "M", "surgery_type": "..." },
      "expected_verdict": "OK" | "NOT OK",
      "expected_cautions": ["anticoagulation", "hyperkalemia"]   // optional, free-text tags
    }

Run from the repo root:

    .venv/bin/python -m validation.batch_runner cases/
    .venv/bin/python -m validation.batch_runner cases/ --threshold 70 --json out.json

A case is *validated* if the predicted verdict matches `expected_verdict` and
each expected caution tag is found (case-insensitive) inside one of the
returned cautions / important_info titles.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Same import resolution as main.py — src/backend acts as the package root, and
# its self-referential `src` symlink lets `from src.x...` imports work.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_BACKEND   = _REPO_ROOT / "src" / "backend"
for p in (str(_REPO_ROOT), str(_BACKEND)):
    if p not in sys.path:
        sys.path.insert(0, p)

from ingestion.pipeline import process_patient  # noqa: E402
from risk.verdict import compute_verdict  # noqa: E402, F401  (keeps import cost cached)


SUPPORTED_TEXT_EXTS = {".txt", ".md"}
SUPPORTED_JSON_EXTS = {".json"}
SUPPORTED_PDF_EXTS  = {".pdf"}


def _flatten_json(payload, prefix: str = "") -> list[str]:
    lines: list[str] = []
    if isinstance(payload, dict):
        for k, v in payload.items():
            lines.extend(_flatten_json(v, f"{prefix}.{k}" if prefix else str(k)))
    elif isinstance(payload, list):
        for i, item in enumerate(payload):
            lines.extend(_flatten_json(item, f"{prefix}[{i}]"))
    elif payload not in (None, ""):
        label = prefix.replace(".", " · ")
        lines.append(f"{label}: {payload}")
    return lines


def _load_case_inputs(case_dir: Path) -> tuple[list[bytes], list[str]]:
    pdfs: list[bytes] = []
    texts: list[str] = []
    docs_dir = case_dir / "documents"
    if not docs_dir.exists():
        return pdfs, texts
    for f in sorted(docs_dir.iterdir()):
        if not f.is_file():
            continue
        ext = f.suffix.lower()
        if ext in SUPPORTED_PDF_EXTS:
            pdfs.append(f.read_bytes())
        elif ext in SUPPORTED_JSON_EXTS:
            texts.append("\n".join(_flatten_json(json.loads(f.read_text()))))
        elif ext in SUPPORTED_TEXT_EXTS:
            texts.append(f.read_text())
    return pdfs, texts


def _run_case(case_dir: Path, threshold_pct: int) -> dict:
    gt_path = case_dir / "ground_truth.json"
    if not gt_path.exists():
        raise FileNotFoundError(f"missing ground_truth.json in {case_dir}")
    gt = json.loads(gt_path.read_text())
    patient = gt.get("patient", {}) or {}

    pdfs, texts = _load_case_inputs(case_dir)
    if not pdfs and not texts:
        raise FileNotFoundError(f"no documents found under {case_dir}/documents/")

    record = process_patient(
        sources=pdfs or None,
        texts=texts or None,
        patient_id=case_dir.name,
    )

    # Build the same shape the API returns
    from main import _api_bundle  # noqa: WPS433 — reuse the API logic verbatim
    bundle = _api_bundle(record, patient={**patient, "threshold_pct": threshold_pct})
    verdict = bundle["verdict"]

    expected_verdict = (gt.get("expected_verdict") or "").strip().upper()
    actual_verdict   = verdict["label"].strip().upper()

    expected_cautions = [c.lower() for c in gt.get("expected_cautions", [])]
    surfaced = " · ".join(
        f["title"].lower()
        for f in (verdict.get("cautions", []) + verdict.get("important_info", []))
    )
    missed_cautions = [c for c in expected_cautions if c not in surfaced]

    matched_verdict = expected_verdict == "" or expected_verdict == actual_verdict
    validated = matched_verdict and not missed_cautions

    return {
        "case": case_dir.name,
        "expected_verdict": expected_verdict or None,
        "actual_verdict": actual_verdict,
        "confidence_pct": verdict["confidence_pct"],
        "validated": validated,
        "missed_cautions": missed_cautions,
        "surfaced_factor_titles": [
            f["title"]
            for f in verdict.get("cautions", []) + verdict.get("important_info", [])
        ],
    }


def run_batch(root: Path, threshold_pct: int = 70) -> dict:
    cases = [p for p in sorted(root.iterdir()) if p.is_dir()]
    if not cases:
        raise SystemExit(f"no case folders under {root}")
    results: list[dict] = []
    for case in cases:
        try:
            results.append(_run_case(case, threshold_pct))
        except Exception as exc:  # noqa: BLE001 — broad catch is intentional in a batch runner
            results.append({
                "case": case.name,
                "validated": False,
                "error": f"{type(exc).__name__}: {exc}",
            })
    n = len(results)
    passed = sum(1 for r in results if r.get("validated"))
    summary = {
        "n_cases": n,
        "n_validated": passed,
        "pass_rate": round(passed / n, 3) if n else 0.0,
        "threshold_pct": threshold_pct,
        "results": results,
    }
    return summary


def _print_human(summary: dict) -> None:
    print(f"\nBatch validation — {summary['n_validated']}/{summary['n_cases']} validated "
          f"({summary['pass_rate'] * 100:.0f}%) at threshold {summary['threshold_pct']}%\n")
    for r in summary["results"]:
        ok = "✓" if r.get("validated") else "✗"
        if "error" in r:
            print(f"  {ok}  {r['case']}: ERROR — {r['error']}")
            continue
        line = (
            f"  {ok}  {r['case']}: "
            f"expected={r.get('expected_verdict') or '?'} → actual={r['actual_verdict']} "
            f"({r['confidence_pct']}%)"
        )
        if r.get("missed_cautions"):
            line += f"  missed_cautions={r['missed_cautions']}"
        print(line)


def _cli() -> None:
    p = argparse.ArgumentParser(description="Run AnaSafe across a directory of patient cases.")
    p.add_argument("root", type=Path, help="folder containing one subfolder per patient case")
    p.add_argument("--threshold", type=int, default=70, help="green-verdict confidence threshold")
    p.add_argument("--json", type=Path, default=None, help="optional output file for the full report")
    args = p.parse_args()

    summary = run_batch(args.root, threshold_pct=args.threshold)
    _print_human(summary)
    if args.json:
        args.json.write_text(json.dumps(summary, indent=2))
        print(f"\nWrote {args.json}")


if __name__ == "__main__":
    _cli()
