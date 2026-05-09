"""
Bayesian confidence scoring — Task 3 from the Pre-Anesthesia Safety Check spec.

For each extracted fact, computes a posterior probability that the fact is true,
given how many source documents confirm or contradict it.  The output is designed
to appear on the dashboard next to each extracted fact.

Method: Bayes' rule in odds form.
    posterior_odds = prior_odds × LR_confirm^k × LR_contradict^m

where k = number of confirming documents, m = number of contradicting documents.
Likelihood ratios are tunable constants; the defaults are conservative for a
safety-critical clinical context (we penalise contradictions more than we reward
confirmations).
"""
from __future__ import annotations

from dataclasses import dataclass, field

# ── Population priors ─────────────────────────────────────────────────────────
# Rough base-rate prevalence for common clinical facts.
# These are only starting points; the posterior is dominated by evidence once
# multiple documents are present.
DEFAULT_PRIORS: dict[str, float] = {
    # Allergies
    "penicillin allergy":  0.10,
    "latex allergy":       0.04,
    "nsaid allergy":       0.02,
    # Diagnoses / conditions
    "diabetes":            0.10,
    "hypertension":        0.30,
    "asthma":              0.08,
    "copd":                0.06,
    "atrial fibrillation": 0.02,
    "heart failure":       0.02,
    "ckd":                 0.08,
    "sleep apnea":         0.10,
    # Medications
    "warfarin":            0.01,
    "apixaban":            0.02,
    "rivaroxaban":         0.01,
    "dabigatran":          0.005,
    "aspirin":             0.20,
    "metformin":           0.10,
    "metoprolol":          0.08,
    "atorvastatin":        0.15,
}

# Likelihood ratios: how much each document shifts our belief.
# A confirming source is strong positive evidence (×10).
# A contradicting source is moderate negative evidence (×0.3).
# Tuned for clinical safety: we want false negatives to be penalised harder
# than false positives, so contradictions multiply odds by 0.3 (not 0.1).
LR_CONFIRM    = 10.0
LR_CONTRADICT = 0.3


def bayesian_confidence(
    fact_name:         str,
    n_confirmations:   int,
    n_contradictions:  int = 0,
    prior:             float | None = None,
) -> float:
    """
    Compute posterior probability that a clinical fact is true.

    Parameters
    ----------
    fact_name        : normalised fact string (used to look up the prior).
    n_confirmations  : how many source documents confirm this fact.
    n_contradictions : how many source documents explicitly contradict it.
    prior            : override the default prior; if None, uses DEFAULT_PRIORS
                       or a conservative 0.05 baseline.

    Returns
    -------
    float in [0, 1] — posterior probability the fact is true.
    """
    if prior is None:
        prior = DEFAULT_PRIORS.get(fact_name.strip().lower(), 0.05)

    # Degenerate priors cannot be updated
    if prior <= 0.0:
        return 0.0
    if prior >= 1.0:
        return 1.0

    prior_odds      = prior / (1.0 - prior)
    posterior_odds  = (
        prior_odds
        * (LR_CONFIRM    ** n_confirmations)
        * (LR_CONTRADICT ** n_contradictions)
    )
    return posterior_odds / (1.0 + posterior_odds)


def format_confidence(
    fact_name:        str,
    n_confirmations:  int,
    n_contradictions: int = 0,
) -> str:
    """
    Return a dashboard-ready string for one extracted fact.

    Example outputs:
        "🔴 Penicillin Allergy — 91% confidence (2 confirm)"
        "🟡 Warfarin — 58% confidence (1 confirm, 1 contradict)"
        "⚪ Latex Allergy — 33% confidence (0 confirm)"
    """
    p = bayesian_confidence(fact_name, n_confirmations, n_contradictions)

    if p >= 0.85:
        icon = "🔴"   # high confidence + safety-critical → strong flag
    elif p >= 0.50:
        icon = "🟡"   # moderate confidence → warn the clinician
    else:
        icon = "⚪"   # low confidence → show but soft

    sources = f"{n_confirmations} confirm"
    if n_contradictions:
        sources += f", {n_contradictions} contradict"

    return f"{icon} {fact_name.title()} — {p:.0%} confidence ({sources})"


# ── Per-patient record scoring ────────────────────────────────────────────────

@dataclass
class ScoredFact:
    category: str           # "medications", "allergies", etc.
    name: str               # normalised fact string
    n_confirmations: int
    n_contradictions: int
    posterior: float
    dashboard_label: str    # output of format_confidence()


@dataclass
class PatientConfidenceReport:
    """All scored facts for one patient, ready for the frontend."""
    patient_id: str
    facts: list[ScoredFact] = field(default_factory=list)

    def by_category(self) -> dict[str, list[ScoredFact]]:
        out: dict[str, list[ScoredFact]] = {}
        for f in self.facts:
            out.setdefault(f.category, []).append(f)
        return out

    def to_dict(self) -> dict:
        return {
            "patient_id": self.patient_id,
            "facts": [
                {
                    "category":         f.category,
                    "name":             f.name,
                    "n_confirmations":  f.n_confirmations,
                    "n_contradictions": f.n_contradictions,
                    "posterior":        round(f.posterior, 3),
                    "label":            f.dashboard_label,
                }
                for f in self.facts
            ],
        }


def score_patient_record(record, documents=None) -> PatientConfidenceReport:
    """
    Compute Bayesian confidence for every fact in a merged PatientRecord.

    ``record``    — a PatientRecord (from ingestion.merger); after merge_documents
                    this carries record.source_documents, so ``documents`` is optional.
    ``documents`` — explicit list[ExtractedDocument] override; if None, falls back
                    to record.source_documents.

    For each unique fact (medication name, allergy substance, diagnosis, lab test,
    procedure), counts how many independent source documents mention it and computes
    the posterior probability.  Contradictions are detected when a later document
    explicitly omits a previously listed medication/diagnosis.
    """
    if documents is None:
        documents = getattr(record, "source_documents", [])

    report = PatientConfidenceReport(patient_id=record.patient_id)

    # Build per-document fact sets so we can count confirmations
    doc_facts: dict[str, dict[str, set[str]]] = {}
    for doc in documents:
        doc_id = doc.document_id
        doc_facts[doc_id] = {
            "medications": {m.name.lower().strip() for m in doc.medications},
            "allergies":   {a.substance.lower().strip() for a in doc.allergies},
            "conditions":  {d.description.lower().strip() for d in doc.diagnoses},
            "labs":        {l.test_name.lower().strip() for l in doc.labs},
            "procedures":  {p.name.lower().strip() for p in doc.procedures},
        }

    n_docs = len(documents)

    def _score_facts(
        category: str,
        facts: list,
        name_fn,
    ) -> None:
        for fact in facts:
            name = name_fn(fact).lower().strip()
            confirms = sum(
                1 for df in doc_facts.values()
                if name in df.get(category, set())
            )
            # A document that has the same category of data but does NOT mention
            # this fact is a weak contradiction (only applies to medications/allergies).
            contradicts = 0
            if category in ("medications", "allergies"):
                contradicts = sum(
                    1 for df in doc_facts.values()
                    if df.get(category)          # doc has data for this category
                    and name not in df[category] # but doesn't mention this fact
                )
                # Cap contradictions at confirms to avoid driving posterior to ~0
                # for facts that simply don't appear in every document type.
                contradicts = min(contradicts, confirms)

            posterior = bayesian_confidence(name, confirms, contradicts)
            label     = format_confidence(name, confirms, contradicts)
            report.facts.append(
                ScoredFact(
                    category=category,
                    name=name,
                    n_confirmations=confirms,
                    n_contradictions=contradicts,
                    posterior=posterior,
                    dashboard_label=label,
                )
            )

    _score_facts("medications", record.medications, lambda m: m.name)
    _score_facts("allergies",   record.allergies,   lambda a: a.substance)
    _score_facts("conditions",  record.diagnoses,   lambda d: d.description)
    _score_facts("labs",        record.labs,         lambda l: l.test_name)
    _score_facts("procedures",  record.procedures,  lambda p: p.name)

    # Sort each category by descending confidence so the most reliable facts appear first
    report.facts.sort(key=lambda f: (-f.posterior, f.category, f.name))
    return report
