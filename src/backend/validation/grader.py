"""
Validation grader — Task 2 from the Pre-Anesthesia Safety Check spec.

Compares AI extraction output against a hand-built ground truth answer key.
Reports precision, recall, and 95% Wilson confidence intervals per fact category.

Wilson CI is used (not normal approximation) because it stays valid at low counts,
which is common in per-patient medical fact extraction.
"""
from __future__ import annotations

import math


def proportion_confint(count: int, nobs: int, alpha: float = 0.05, method: str = "wilson") -> tuple[float, float]:
    """Wilson 95% confidence interval — minimal replacement for statsmodels."""
    if nobs == 0:
        return (0.0, 0.0)
    z = 1.959963984540054  # 0.975 quantile of standard normal
    p = count / nobs
    denom = 1 + z * z / nobs
    centre = (p + z * z / (2 * nobs)) / denom
    half = (z * math.sqrt(p * (1 - p) / nobs + z * z / (4 * nobs * nobs))) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))

CATEGORIES = ["allergies", "medications", "conditions", "anesthesia_history", "labs", "procedures"]


def grade_category(
    ground_truth_facts: set[str],
    ai_facts: set[str],
) -> dict:
    """
    Compare one category (e.g. "allergies") between ground truth and AI output.

    Inputs are sets of strings; matching is case-insensitive after stripping whitespace.
    Tagging facts with a report ID before calling (e.g. "case1::penicillin") lets you
    aggregate safely across multiple patients without merging distinct individuals.

    Returns
    -------
    dict with keys:
        true_positives   : facts the AI correctly found
        false_negatives  : real facts the AI missed  (safety-critical misses)
        false_positives  : facts the AI hallucinated
        precision        : tp / (tp + fp), or None if AI made no predictions
        recall           : tp / (tp + fn), or None if ground truth is empty
        precision_ci     : 95% Wilson CI on precision, or (None, None)
        recall_ci        : 95% Wilson CI on recall, or (None, None)
    """
    gt = {f.strip().lower() for f in ground_truth_facts}
    ai = {f.strip().lower() for f in ai_facts}

    true_positives  = gt & ai
    false_negatives = gt - ai
    false_positives = ai - gt

    tp = len(true_positives)
    fn = len(false_negatives)
    fp = len(false_positives)

    if tp + fn > 0:
        recall    = tp / (tp + fn)
        recall_ci = proportion_confint(tp, tp + fn, alpha=0.05, method="wilson")
    else:
        recall, recall_ci = None, (None, None)

    if tp + fp > 0:
        precision    = tp / (tp + fp)
        precision_ci = proportion_confint(tp, tp + fp, alpha=0.05, method="wilson")
    else:
        precision, precision_ci = None, (None, None)

    return {
        "true_positives":  true_positives,
        "false_negatives": false_negatives,
        "false_positives": false_positives,
        "precision":       precision,
        "precision_ci":    precision_ci,
        "recall":          recall,
        "recall_ci":       recall_ci,
    }


def grade_full_report(
    ground_truth: dict[str, dict[str, set[str]]],
    ai_output:    dict[str, dict[str, set[str]]],
    categories:   list[str] | None = None,
) -> dict[str, dict]:
    """
    Grade the AI across multiple reports and multiple categories.

    Inputs
    ------
    ground_truth : { report_id: { category: set of fact strings } }
    ai_output    : { report_id: { category: set of fact strings } }
    categories   : categories to grade (default: CATEGORIES)

    Facts are tagged with report_id before aggregation so "Penicillin" in patient A
    and "Penicillin" in patient B are treated as independent observations.

    Returns
    -------
    { category: result dict from grade_category }
    """
    cats = categories or CATEGORIES
    aggregated: dict[str, dict] = {}

    for cat in cats:
        all_gt: set[str] = set()
        all_ai: set[str] = set()

        for report_id, facts_by_cat in ground_truth.items():
            for fact in facts_by_cat.get(cat, set()):
                all_gt.add(f"{report_id}::{fact.strip().lower()}")

        for report_id in ground_truth:           # only grade reports we have GT for
            for fact in ai_output.get(report_id, {}).get(cat, set()):
                all_ai.add(f"{report_id}::{fact.strip().lower()}")

        aggregated[cat] = grade_category(all_gt, all_ai)

    return aggregated


def print_evaluation_report(metrics: dict[str, dict]) -> None:
    """Pretty-print the grading results to stdout."""
    print("=" * 65)
    print("  AI EXTRACTION EVALUATION REPORT")
    print("=" * 65)

    for category, m in metrics.items():
        print(f"\n[ {category.upper()} ]")

        if m["recall"] is not None:
            lo, hi = m["recall_ci"]
            n_found = len(m["true_positives"])
            n_total = len(m["true_positives"]) + len(m["false_negatives"])
            print(
                f"  Recall    : {m['recall']:.0%}  "
                f"[95% CI: {lo:.0%}–{hi:.0%}]   "
                f"(found {n_found}/{n_total})"
            )
        else:
            print("  Recall    : N/A (no facts in ground truth for this category)")

        if m["precision"] is not None:
            lo, hi = m["precision_ci"]
            n_correct = len(m["true_positives"])
            n_claimed = len(m["true_positives"]) + len(m["false_positives"])
            print(
                f"  Precision : {m['precision']:.0%}  "
                f"[95% CI: {lo:.0%}–{hi:.0%}]   "
                f"({n_correct}/{n_claimed} correct)"
            )
        else:
            print("  Precision : N/A (no predictions for this category)")

        if m["false_negatives"]:
            missed = {f.split("::", 1)[-1] for f in m["false_negatives"]}
            print(f"  ⚠  MISSED  : {sorted(missed)}")

        if m["false_positives"]:
            halluc = {f.split("::", 1)[-1] for f in m["false_positives"]}
            print(f"  ⚠  HALLUC  : {sorted(halluc)}")

    print()
    _print_summary_row(metrics)
    print("=" * 65)


def _print_summary_row(metrics: dict[str, dict]) -> None:
    """One-line summary row per category for quick scanning."""
    header = f"  {'Category':<22} {'Recall':>8}  {'Precision':>10}  {'Missed':>6}  {'Halluc':>6}"
    print(header)
    print("  " + "-" * 60)
    for cat, m in metrics.items():
        rec  = f"{m['recall']:.0%}"    if m["recall"]    is not None else "  —  "
        prec = f"{m['precision']:.0%}" if m["precision"] is not None else "  —  "
        missed = len(m["false_negatives"])
        halluc = len(m["false_positives"])
        print(f"  {cat:<22} {rec:>8}  {prec:>10}  {missed:>6}  {halluc:>6}")
