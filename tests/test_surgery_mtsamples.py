"""
MT Samples surgery evaluation.

Tests the pipeline on real operative notes from MT Samples across 3 dimensions:
  1. Classifier accuracy  — does it correctly label surgery notes as operative_note?
  2. Extraction yield     — procedures, implants, warnings per document
  3. Speed               — seconds per document

Run with:
    export ANTHROPIC_API_KEY=sk-ant-...
    PYTHONPATH=. er-preop-brief/.venv/bin/python tests/test_surgery_mtsamples.py
"""
from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass, field

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

N_SAMPLES = 15      # number of surgery notes to test (keep low to manage API cost)
MIN_TEXT_LEN = 300  # skip very short/corrupt notes


@dataclass
class DocResult:
    idx: int
    title: str
    text_length: int

    # Classifier pass (no document_type hint)
    classified_as: str = ""
    classifier_correct: bool = False
    classify_seconds: float = 0.0

    # Extraction pass (forced operative_note)
    n_procedures: int = 0
    n_implants: int = 0
    confidence: float = 0.0
    warnings: list[str] = field(default_factory=list)
    extract_seconds: float = 0.0

    # Sample extractions for spot-checking
    procedure_names: list[str] = field(default_factory=list)
    implant_names: list[str] = field(default_factory=list)


def run():
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ERROR: Set ANTHROPIC_API_KEY first.")
        sys.exit(1)

    from src.utils.mtsamples import load_samples
    from src.classifier.classifier import classify
    from src.ingestion.pipeline import process_text

    # ── Load surgery samples ─────────────────────────────────────────────────
    print("Loading MT Samples (surgery specialty)...")
    all_surgery = load_samples(document_type="operative_note")
    # Filter out very short notes (likely corrupt or header-only)
    all_surgery = [r for r in all_surgery if len(r["transcription"]) >= MIN_TEXT_LEN]

    if not all_surgery:
        print("No surgery samples found. Is data/mtsamples.csv present?")
        sys.exit(1)

    # Spread sample across the dataset (not just the first N)
    step = max(1, len(all_surgery) // N_SAMPLES)
    samples = all_surgery[::step][:N_SAMPLES]
    print(f"Selected {len(samples)} surgery notes from {len(all_surgery)} available.\n")

    results: list[DocResult] = []

    for i, row in enumerate(samples, 1):
        text = row["transcription"]
        title = row["title"][:60]
        print(f"[{i:02d}/{len(samples)}] {title}...")

        result = DocResult(idx=i, title=title, text_length=len(text))

        # ── Pass 1: classifier (no hint) ─────────────────────────────────
        t0 = time.time()
        result.classified_as = classify(text)
        result.classify_seconds = round(time.time() - t0, 2)
        result.classifier_correct = (result.classified_as == "operative_note")

        # ── Pass 2: extraction (forced type) ─────────────────────────────
        t0 = time.time()
        doc = process_text(text, document_id=row["id"], document_type="operative_note")
        result.extract_seconds = round(time.time() - t0, 2)

        result.n_procedures = len(doc.procedures)
        result.n_implants   = len(doc.implants)
        result.confidence   = doc.extraction_confidence
        result.warnings     = doc.extraction_warnings
        result.procedure_names = [p.name for p in doc.procedures]
        result.implant_names   = [imp.description[:60] for imp in doc.implants]

        _print_doc_result(result)
        results.append(result)

    # ── Aggregate summary ────────────────────────────────────────────────────
    _print_summary(results)

    # ── Save full results ────────────────────────────────────────────────────
    out_path = os.path.join(os.path.dirname(__file__), "..", "data", "surgery_eval.json")
    with open(out_path, "w") as f:
        json.dump(
            [
                {
                    "idx": r.idx,
                    "title": r.title,
                    "text_length": r.text_length,
                    "classified_as": r.classified_as,
                    "classifier_correct": r.classifier_correct,
                    "classify_seconds": r.classify_seconds,
                    "n_procedures": r.n_procedures,
                    "n_implants": r.n_implants,
                    "confidence": r.confidence,
                    "warnings": r.warnings,
                    "procedure_names": r.procedure_names,
                    "implant_names": r.implant_names,
                    "extract_seconds": r.extract_seconds,
                }
                for r in results
            ],
            f,
            indent=2,
        )
    print(f"\nFull results saved → data/surgery_eval.json")


# ── Display helpers ───────────────────────────────────────────────────────────

def _print_doc_result(r: DocResult):
    clf_mark = "✓" if r.classifier_correct else f"✗ ({r.classified_as})"
    print(f"       Classifier:   {clf_mark}  ({r.classify_seconds}s)")
    print(f"       Procedures:   {r.n_procedures}  {r.procedure_names[:3]}")
    print(f"       Implants:     {r.n_implants}  {r.implant_names[:2]}")
    print(f"       Confidence:   {r.confidence}")
    if r.warnings:
        for w in r.warnings:
            print(f"       ⚠  {w}")
    print()


def _print_summary(results: list[DocResult]):
    n = len(results)
    correct = sum(1 for r in results if r.classifier_correct)
    misclassified = [r for r in results if not r.classifier_correct]
    avg_procs = sum(r.n_procedures for r in results) / n
    avg_implants = sum(r.n_implants for r in results) / n
    avg_conf = sum(r.confidence for r in results) / n
    avg_clf_s = sum(r.classify_seconds for r in results) / n
    avg_ext_s = sum(r.extract_seconds for r in results) / n
    docs_with_procs = sum(1 for r in results if r.n_procedures > 0)
    docs_with_implants = sum(1 for r in results if r.n_implants > 0)
    docs_with_warnings = sum(1 for r in results if r.warnings)

    # Warning frequency table
    from collections import Counter
    all_warnings = [w for r in results for w in r.warnings]
    warning_counts = Counter(all_warnings).most_common(5)

    print("=" * 65)
    print("  SURGERY EVALUATION SUMMARY")
    print("=" * 65)
    print(f"  Documents tested:          {n}")
    print()
    print(f"  CLASSIFIER")
    print(f"    Accuracy:                {correct}/{n} ({correct/n:.0%})")
    if misclassified:
        print(f"    Misclassified as:")
        from collections import Counter
        for label, count in Counter(r.classified_as for r in misclassified).most_common():
            examples = [r.title for r in misclassified if r.classified_as == label][:2]
            print(f"      {label} ×{count}  e.g. {examples}")
    print(f"    Avg classify time:       {avg_clf_s:.2f}s")
    print()
    print(f"  EXTRACTION")
    print(f"    Docs with ≥1 procedure:  {docs_with_procs}/{n} ({docs_with_procs/n:.0%})")
    print(f"    Docs with ≥1 implant:    {docs_with_implants}/{n} ({docs_with_implants/n:.0%})")
    print(f"    Avg procedures/doc:      {avg_procs:.1f}")
    print(f"    Avg implants/doc:        {avg_implants:.1f}")
    print(f"    Avg confidence:          {avg_conf:.2f}")
    print(f"    Avg extract time:        {avg_ext_s:.2f}s")
    print()
    print(f"  WARNINGS")
    print(f"    Docs with warnings:      {docs_with_warnings}/{n} ({docs_with_warnings/n:.0%})")
    if warning_counts:
        print(f"    Most common:")
        for w, c in warning_counts:
            print(f"      ×{c}  {w[:70]}")
    print()

    # Spot-check: show 3 detailed examples
    print("  SPOT-CHECK (3 samples)")
    print("  " + "-" * 61)
    for r in results[:3]:
        print(f"  [{r.idx}] {r.title}")
        if r.procedure_names:
            for p in r.procedure_names:
                print(f"       Procedure: {p}")
        else:
            print(f"       (no procedures extracted)")
        if r.implant_names:
            for imp in r.implant_names:
                print(f"       Implant:   {imp}")
    print("=" * 65)


if __name__ == "__main__":
    run()
