"""
Validation CLI — runs the full extraction pipeline on annotated cases and
MT Samples, then reports precision/recall and Bayesian confidence scores.

Usage
-----
    # From the project root:
    export ANTHROPIC_API_KEY=sk-ant-...

    # Quick run — annotated cases only (no API cost from MT Samples):
    PYTHONPATH=src/backend er-preop-brief/.venv/bin/python \
        src/backend/validation/run_validation.py

    # Full run — also benchmark 20 surgery notes from MT Samples:
    PYTHONPATH=src/backend er-preop-brief/.venv/bin/python \
        src/backend/validation/run_validation.py --mtsamples --n 20

    # Save JSON report:
    PYTHONPATH=src/backend er-preop-brief/.venv/bin/python \
        src/backend/validation/run_validation.py --out data/validation_report.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

# ── Path setup ────────────────────────────────────────────────────────────────
_ROOT = Path(__file__).resolve().parents[3]          # hack/
_BACKEND = _ROOT / "src" / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))


def _check_api_key() -> None:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ERROR: ANTHROPIC_API_KEY is not set.")
        print("  export ANTHROPIC_API_KEY=sk-ant-...")
        sys.exit(1)


# ── Annotated case runner ─────────────────────────────────────────────────────

def run_annotated_cases(verbose: bool = True) -> tuple[dict, dict]:
    """
    Run the pipeline on all ANNOTATED_CASES and return (ground_truth, ai_output)
    in the format expected by grade_full_report.
    """
    from ingestion.pipeline import process_text
    from validation.ground_truth import ANNOTATED_CASES, CASE_TEXTS, normalise_ai_output

    ground_truth: dict[str, dict] = {}
    ai_output:    dict[str, dict] = {}

    for case_id, gt_facts in ANNOTATED_CASES.items():
        text = CASE_TEXTS[case_id]

        if verbose:
            print(f"  Processing: {case_id} ...", end=" ", flush=True)

        t0 = time.time()
        result = process_text(text, document_id=case_id)
        elapsed = time.time() - t0

        if verbose:
            print(f"({elapsed:.1f}s)  type={result.document_type}  conf={result.extraction_confidence}")

        ground_truth[case_id] = gt_facts
        ai_output[case_id]    = normalise_ai_output(result)

    return ground_truth, ai_output


# ── MT Samples benchmark runner ───────────────────────────────────────────────

def run_mtsamples_benchmark(n: int = 20, verbose: bool = True) -> tuple[dict, dict]:
    """
    Run the pipeline on N operative notes from MT Samples and compare against
    keyword-derived ground truth (partial — procedures only).
    """
    from ingestion.pipeline import process_text
    from utils.mtsamples import load_samples
    from validation.ground_truth import build_mtsamples_ground_truth, normalise_ai_output

    csv_path = _ROOT / "data" / "mtsamples.csv"
    if not csv_path.exists():
        print(
            f"\n  MT Samples CSV not found at {csv_path}.\n"
            "  Download from https://www.kaggle.com/datasets/tboyle10/medicaltranscriptions\n"
            "  Skipping MT Samples benchmark."
        )
        return {}, {}

    samples = load_samples(document_type="operative_note", limit=n * 3)
    samples = [s for s in samples if len(s["transcription"]) >= 300][:n]

    if verbose:
        print(f"\n  Running MT Samples benchmark on {len(samples)} operative notes...")

    gt_all = build_mtsamples_ground_truth(samples)
    ai_all: dict[str, dict] = {}

    for row in samples:
        sid = row["id"]
        if sid not in gt_all:
            continue   # no keywords → skip (no ground truth)

        if verbose:
            title = row["title"][:50]
            print(f"    [{sid}] {title} ...", end=" ", flush=True)

        t0 = time.time()
        result = process_text(
            row["transcription"],
            document_id=sid,
            document_type="operative_note",
        )
        elapsed = time.time() - t0

        if verbose:
            print(f"({elapsed:.1f}s)  procs={len(result.procedures)}")

        ai_all[sid] = normalise_ai_output(result)

    return gt_all, ai_all


# ── Bayesian confidence demo ──────────────────────────────────────────────────

def demo_bayesian(verbose: bool = True) -> None:
    """
    Show Bayesian confidence scores for the curated multi-document patient
    (same patient across discharge + lab + anesthesia + operative notes).
    """
    from ingestion.pipeline  import process_patient
    from validation.bayesian import score_patient_record
    from validation.ground_truth import CASE_TEXTS

    if verbose:
        print("\n" + "=" * 65)
        print("  BAYESIAN CONFIDENCE — multi-document patient demo")
        print("=" * 65)

    texts = [
        CASE_TEXTS["discharge_en"],
        CASE_TEXTS["lab_report"],
        CASE_TEXTS["anesthesia_record"],
        CASE_TEXTS["operative_note"],
    ]

    record      = process_patient(texts=texts, patient_id="demo_patient")
    # source_documents is populated by merge_documents — no need to re-process
    conf_report = score_patient_record(record)

    if verbose:
        by_cat = conf_report.by_category()
        for cat, facts in sorted(by_cat.items()):
            print(f"\n  [{cat.upper()}]")
            for f in facts:
                print(f"    {f.dashboard_label}")

    return conf_report


# ── Report serialiser ─────────────────────────────────────────────────────────

def build_json_report(
    annotated_metrics: dict,
    mtsamples_metrics: dict,
    conf_report,
) -> dict:
    def _serialise_metrics(metrics: dict) -> dict:
        out = {}
        for cat, m in metrics.items():
            out[cat] = {
                "recall":          round(m["recall"], 3)    if m["recall"]    is not None else None,
                "precision":       round(m["precision"], 3) if m["precision"] is not None else None,
                "recall_ci":       [round(v, 3) for v in m["recall_ci"]]    if m["recall_ci"][0]    is not None else None,
                "precision_ci":    [round(v, 3) for v in m["precision_ci"]] if m["precision_ci"][0] is not None else None,
                "false_negatives": sorted(m["false_negatives"]),
                "false_positives": sorted(m["false_positives"]),
            }
        return out

    return {
        "annotated_cases":      _serialise_metrics(annotated_metrics),
        "mtsamples_benchmark":  _serialise_metrics(mtsamples_metrics) if mtsamples_metrics else {},
        "bayesian_confidence":  conf_report.to_dict() if conf_report else {},
    }


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the pre-anesthesia extraction validation suite."
    )
    parser.add_argument(
        "--mtsamples", action="store_true",
        help="Also benchmark against MT Samples operative notes."
    )
    parser.add_argument(
        "--n", type=int, default=20,
        help="Number of MT Samples notes to benchmark (default: 20)."
    )
    parser.add_argument(
        "--out", type=str, default=None,
        help="Path to write the JSON report (optional)."
    )
    parser.add_argument(
        "--no-bayesian", action="store_true",
        help="Skip the Bayesian confidence demo (saves ~4 API calls)."
    )
    args = parser.parse_args()

    _check_api_key()

    # ── 1. Annotated cases ────────────────────────────────────────────────────
    from validation.grader import grade_full_report, print_evaluation_report

    print("\n" + "=" * 65)
    print("  STEP 1 — Annotated case evaluation")
    print("=" * 65)
    gt_ann, ai_ann = run_annotated_cases(verbose=True)
    ann_metrics    = grade_full_report(gt_ann, ai_ann)

    print()
    print_evaluation_report(ann_metrics)

    # ── 2. MT Samples benchmark (optional) ───────────────────────────────────
    mt_metrics: dict = {}
    if args.mtsamples:
        print("\n" + "=" * 65)
        print("  STEP 2 — MT Samples operative note benchmark")
        print("=" * 65)
        gt_mt, ai_mt = run_mtsamples_benchmark(n=args.n, verbose=True)
        if gt_mt:
            mt_metrics = grade_full_report(gt_mt, ai_mt, categories=["procedures"])
            print()
            print_evaluation_report(mt_metrics)
        else:
            print("  (skipped — no ground truth available)")

    # ── 3. Bayesian confidence demo ──────────────────────────────────────────
    conf_report = None
    if not args.no_bayesian:
        conf_report = demo_bayesian(verbose=True)

    # ── 4. Save JSON report ───────────────────────────────────────────────────
    if args.out:
        report = build_json_report(ann_metrics, mt_metrics, conf_report)
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w") as f:
            json.dump(report, f, indent=2)
        print(f"\n  Report saved → {out_path}")

    print("\n" + "=" * 65)
    print("  VALIDATION COMPLETE")
    print("=" * 65 + "\n")


if __name__ == "__main__":
    main()
