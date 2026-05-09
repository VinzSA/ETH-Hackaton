"""
Wearable data → clinical signals.

Takes WearableRawData (from wearable_reader.py) and computes:
  1. OSA signal   — probable sleep apnea from nightly SpO2 dips
  2. Functional capacity — activity level from 30-day step average
  3. Resting HR trend   — cardiac reserve flag from HR over 60 days

Each signal carries a SourceRef so it appears in source grounding like any PDF entity.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from src.ingestion.wearable_reader import WearableRawData
from src.schema.preop_brief import SourceRef

# Step count thresholds (steps/day → functional capacity)
# Based on DASI equivalents used in cardiac pre-op assessment
STEPS_LOW      = 3_500   # < 3500 → low (<4 METs, can't climb a flight of stairs)
STEPS_HIGH     = 7_500   # > 7500 → high (>7 METs, vigorous activity)

# OSA proxy threshold
OSA_DIP_RATE   = 0.20    # ≥20% of nights with significant SpO2 dip → probable OSA
OSA_MIN_NIGHTS = 7       # need at least 7 nights to make any claim

# HR trend threshold
HR_RISE_BPM_PER_DAY = 0.10   # >0.1 bpm/day rise over 60 days = "rising"


@dataclass
class OSASignal:
    probable_osa: bool
    confidence: float               # 0.0–1.0
    nights_analyzed: int
    nights_with_dips: int
    avg_min_spo2: float | None      # average of nightly minimums
    dip_rate: float                 # proportion of nights with dips
    source: SourceRef


@dataclass
class FunctionalCapacity:
    level: Literal["low", "moderate", "high"]
    avg_daily_steps_30d: float
    days_analyzed: int
    avg_active_minutes_30d: float | None
    source: SourceRef


@dataclass
class HRTrend:
    trend: Literal["stable", "rising", "falling"]
    slope_bpm_per_day: float        # positive = rising
    days_analyzed: int
    avg_resting_hr: float | None
    source: SourceRef


@dataclass
class WearableSignals:
    device: str                           # "fitbit" | "garmin" | "unknown"
    export_date_range: tuple[str, str] | None
    osa: OSASignal | None = None
    functional_capacity: FunctionalCapacity | None = None
    hr_trend: HRTrend | None = None


def extract_wearable_signals(raw: WearableRawData) -> WearableSignals:
    """Compute all clinical signals from raw wearable data."""
    doc_id = f"wearable_{raw.source}"

    signals = WearableSignals(
        device=raw.source,
        export_date_range=raw.export_date_range,
    )

    if raw.spo2_nights:
        signals.osa = _compute_osa(raw, doc_id)

    if raw.daily_activity:
        signals.functional_capacity = _compute_functional_capacity(raw, doc_id)

    if raw.daily_hr:
        signals.hr_trend = _compute_hr_trend(raw, doc_id)

    return signals


# ── OSA signal ────────────────────────────────────────────────────────────────

def _compute_osa(raw: WearableRawData, doc_id: str) -> OSASignal:
    nights = raw.spo2_nights
    n = len(nights)
    dips = sum(1 for night in nights if night.had_significant_dip)
    dip_rate = dips / n if n > 0 else 0.0

    min_values = [night.min_pct for night in nights if night.min_pct is not None]
    avg_min = round(sum(min_values) / len(min_values), 1) if min_values else None

    probable_osa = (n >= OSA_MIN_NIGHTS) and (dip_rate >= OSA_DIP_RATE)

    # Confidence: penalise low night counts and borderline dip rates
    if n < OSA_MIN_NIGHTS:
        confidence = 0.2
    elif dip_rate >= 0.40:
        confidence = 0.85
    elif dip_rate >= OSA_DIP_RATE:
        confidence = 0.65
    else:
        confidence = 0.50  # OSA unlikely but not ruled out

    snippet = (
        f"{dips}/{n} nights SpO₂<90% — avg min SpO₂: {avg_min}%"
        if avg_min else f"{dips}/{n} nights with SpO₂ dips"
    )

    return OSASignal(
        probable_osa=probable_osa,
        confidence=round(confidence, 2),
        nights_analyzed=n,
        nights_with_dips=dips,
        avg_min_spo2=avg_min,
        dip_rate=round(dip_rate, 3),
        source=SourceRef(
            document_id=doc_id,
            document_type="wearable",
            page=1,
            char_start=0,
            char_end=len(snippet),
            snippet=snippet[:50],
        ),
    )


# ── Functional capacity ───────────────────────────────────────────────────────

def _compute_functional_capacity(raw: WearableRawData, doc_id: str) -> FunctionalCapacity:
    # Use last 30 days only
    cutoff = _days_ago(30)
    recent = [a for a in raw.daily_activity if a.date >= cutoff and a.steps is not None]

    if not recent:
        recent = raw.daily_activity  # fall back to all available data

    steps = [a.steps for a in recent if a.steps is not None]
    active = [a.active_minutes for a in recent if a.active_minutes is not None]

    avg_steps = round(sum(steps) / len(steps), 0) if steps else 0.0
    avg_active = round(sum(active) / len(active), 0) if active else None

    if avg_steps < STEPS_LOW:
        level: Literal["low", "moderate", "high"] = "low"
    elif avg_steps > STEPS_HIGH:
        level = "high"
    else:
        level = "moderate"

    snippet = f"30d avg steps: {int(avg_steps):,} → functional capacity: {level}"

    return FunctionalCapacity(
        level=level,
        avg_daily_steps_30d=avg_steps,
        days_analyzed=len(recent),
        avg_active_minutes_30d=avg_active,
        source=SourceRef(
            document_id=f"wearable_{raw.source}",
            document_type="wearable",
            page=1,
            char_start=0,
            char_end=len(snippet),
            snippet=snippet[:50],
        ),
    )


# ── Resting HR trend ──────────────────────────────────────────────────────────

def _compute_hr_trend(raw: WearableRawData, doc_id: str) -> HRTrend:
    # Use last 60 days
    cutoff = _days_ago(60)
    recent = [
        h for h in raw.daily_hr
        if h.date >= cutoff and h.resting_hr is not None
    ]
    if not recent:
        recent = [h for h in raw.daily_hr if h.resting_hr is not None]

    hrs = [h.resting_hr for h in recent if h.resting_hr is not None]
    avg_hr = round(sum(hrs) / len(hrs), 1) if hrs else None

    slope = _linear_slope(recent)

    if slope > HR_RISE_BPM_PER_DAY:
        trend: Literal["stable", "rising", "falling"] = "rising"
    elif slope < -HR_RISE_BPM_PER_DAY:
        trend = "falling"
    else:
        trend = "stable"

    snippet = f"Resting HR trend ({len(recent)}d): {trend}, slope {slope:+.2f} bpm/day"

    return HRTrend(
        trend=trend,
        slope_bpm_per_day=round(slope, 3),
        days_analyzed=len(recent),
        avg_resting_hr=avg_hr,
        source=SourceRef(
            document_id=f"wearable_{raw.source}",
            document_type="wearable",
            page=1,
            char_start=0,
            char_end=len(snippet),
            snippet=snippet[:50],
        ),
    )


# ── Utilities ─────────────────────────────────────────────────────────────────

def _days_ago(n: int) -> str:
    return (datetime.today() - timedelta(days=n)).strftime("%Y-%m-%d")


def _linear_slope(records: list) -> float:
    """Simple OLS slope of resting_hr over day-index."""
    pts = [(i, r.resting_hr) for i, r in enumerate(
        sorted(records, key=lambda r: r.date)
    ) if r.resting_hr is not None]
    if len(pts) < 2:
        return 0.0
    n = len(pts)
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    x_mean = sum(xs) / n
    y_mean = sum(ys) / n
    num = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys))
    den = sum((x - x_mean) ** 2 for x in xs)
    return num / den if den != 0 else 0.0
