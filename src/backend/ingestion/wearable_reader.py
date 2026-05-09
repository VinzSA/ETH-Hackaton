"""
Wearable data reader — Fitbit and Garmin Connect export ZIPs.

Auto-detects the export format from the ZIP structure, then extracts:
  - Nightly SpO2 readings (min/avg per night)
  - Daily step counts
  - Daily resting heart rate

Returns a WearableRawData object consumed by wearable_extractor.py.
"""
from __future__ import annotations

import io
import json
import re
import zipfile
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class NightlySpO2:
    date: str           # YYYY-MM-DD
    avg_pct: float | None
    min_pct: float | None
    # True if SpO2 dropped below 90% for a sustained period this night
    had_significant_dip: bool = False


@dataclass
class DailyActivity:
    date: str           # YYYY-MM-DD
    steps: int | None
    active_minutes: int | None = None
    calories: int | None = None


@dataclass
class DailyHeartRate:
    date: str           # YYYY-MM-DD
    resting_hr: int | None


@dataclass
class WearableRawData:
    source: str                               # "fitbit" | "garmin" | "unknown"
    export_date_range: tuple[str, str] | None = None  # (earliest, latest) ISO dates
    spo2_nights: list[NightlySpO2] = field(default_factory=list)
    daily_activity: list[DailyActivity] = field(default_factory=list)
    daily_hr: list[DailyHeartRate] = field(default_factory=list)


# ── Public entry point ────────────────────────────────────────────────────────

def read_wearable_zip(source: str | bytes) -> WearableRawData:
    """
    Parse a Fitbit or Garmin export ZIP.
    `source` can be a file path string or raw bytes.
    """
    if isinstance(source, (str,)):
        with open(source, "rb") as f:
            raw = f.read()
    else:
        raw = source

    zf = zipfile.ZipFile(io.BytesIO(raw))
    names = zf.namelist()

    fmt = _detect_format(names)
    if fmt == "fitbit":
        return _parse_fitbit(zf, names)
    elif fmt == "garmin":
        return _parse_garmin(zf, names)
    else:
        return WearableRawData(source="unknown")


# ── Format detection ──────────────────────────────────────────────────────────

def _detect_format(names: list[str]) -> str:
    lower_names = [n.lower() for n in names]
    joined = " ".join(lower_names)
    # Garmin first — DI_CONNECT is a strong signal; check before generic terms
    if any("di_connect" in n or "garmin" in n or "activities/" in n for n in lower_names):
        return "garmin"
    if any("fitbit" in n or "spo2" in n or "sleep/" in n for n in lower_names):
        return "fitbit"
    if re.search(r"(heart.rate|physical.activity|sleep)", joined):
        return "fitbit"
    return "unknown"


# ── Fitbit parser ─────────────────────────────────────────────────────────────

def _parse_fitbit(zf: zipfile.ZipFile, names: list[str]) -> WearableRawData:
    data = WearableRawData(source="fitbit")

    spo2_files   = [n for n in names if "spo2" in n.lower() and n.endswith(".json")]
    sleep_files  = [n for n in names if "sleep" in n.lower() and n.endswith(".json")]
    step_files   = [n for n in names if ("steps" in n.lower() or "physical-activity" in n.lower()) and n.endswith(".json")]
    hr_files     = [n for n in names if "heart_rate" in n.lower() and n.endswith(".json")]

    # SpO2 — dedicated folder (newer Fitbit devices)
    if spo2_files:
        for fname in spo2_files:
            data.spo2_nights.extend(_fitbit_spo2(zf, fname))
    elif sleep_files:
        # Older devices: infer SpO2 from sleep staging metadata if available
        for fname in sleep_files:
            data.spo2_nights.extend(_fitbit_spo2_from_sleep(zf, fname))

    # Steps
    for fname in step_files:
        data.daily_activity.extend(_fitbit_steps(zf, fname))

    # Heart rate
    for fname in hr_files:
        data.daily_hr.extend(_fitbit_hr(zf, fname))

    data.export_date_range = _date_range(data)
    return data


def _fitbit_spo2(zf: zipfile.ZipFile, fname: str) -> list[NightlySpO2]:
    records = _load_json(zf, fname)
    nights = []
    if not isinstance(records, list):
        return nights

    for rec in records:
        # Format 1: {"dateTime": "2024-01-15", "value": {"avg": 96.5, "min": 89.0}}
        if "value" in rec and isinstance(rec["value"], dict):
            date_str = _parse_date(rec.get("dateTime", ""))
            avg = rec["value"].get("avg")
            mn  = rec["value"].get("min")
            if date_str:
                nights.append(NightlySpO2(
                    date=date_str,
                    avg_pct=float(avg) if avg is not None else None,
                    min_pct=float(mn) if mn is not None else None,
                    had_significant_dip=(float(mn) < 90.0) if mn is not None else False,
                ))

        # Format 2: per-minute readings — aggregate per night
        elif "timestamp" in rec and "value" in rec:
            pass  # handled by _aggregate_intranight below

    # If we got per-minute data instead of nightly summaries, aggregate
    if not nights and records and "timestamp" in records[0]:
        nights = _aggregate_intranight_spo2(records)

    return nights


def _aggregate_intranight_spo2(records: list[dict]) -> list[NightlySpO2]:
    from collections import defaultdict
    by_date: dict[str, list[float]] = defaultdict(list)
    for rec in records:
        ts = rec.get("timestamp", "")
        val = rec.get("value")
        date_str = _parse_date(ts[:10] if ts else "")
        if date_str and val is not None:
            try:
                by_date[date_str].append(float(val))
            except (ValueError, TypeError):
                pass

    nights = []
    for date_str, values in sorted(by_date.items()):
        mn = min(values)
        avg = sum(values) / len(values)
        # Significant dip: min < 90% sustained — proxy: >3 readings below 90
        dip_count = sum(1 for v in values if v < 90.0)
        nights.append(NightlySpO2(
            date=date_str,
            avg_pct=round(avg, 1),
            min_pct=round(mn, 1),
            had_significant_dip=(dip_count >= 3),
        ))
    return nights


def _fitbit_spo2_from_sleep(zf: zipfile.ZipFile, fname: str) -> list[NightlySpO2]:
    # Fallback: Fitbit sleep JSON sometimes contains SpO2Range in minuteData
    records = _load_json(zf, fname)
    if not isinstance(records, list):
        return []
    # Not all sleep JSONs have SpO2 — return empty, caller will skip
    return []


def _fitbit_steps(zf: zipfile.ZipFile, fname: str) -> list[DailyActivity]:
    records = _load_json(zf, fname)
    if not isinstance(records, list):
        return []
    result = []
    for rec in records:
        date_str = _parse_date(rec.get("dateTime", ""))
        val = rec.get("value")
        if date_str and val is not None:
            try:
                result.append(DailyActivity(date=date_str, steps=int(val)))
            except (ValueError, TypeError):
                pass
    return result


def _fitbit_hr(zf: zipfile.ZipFile, fname: str) -> list[DailyHeartRate]:
    records = _load_json(zf, fname)
    if not isinstance(records, list):
        return []
    result = []
    for rec in records:
        date_str = _parse_date(rec.get("dateTime", ""))
        val = rec.get("value", {})
        rhr = val.get("restingHeartRate") if isinstance(val, dict) else None
        if date_str:
            try:
                result.append(DailyHeartRate(
                    date=date_str,
                    resting_hr=int(rhr) if rhr is not None else None,
                ))
            except (ValueError, TypeError):
                pass
    return result


# ── Garmin parser ─────────────────────────────────────────────────────────────

def _parse_garmin(zf: zipfile.ZipFile, names: list[str]) -> WearableRawData:
    data = WearableRawData(source="garmin")

    spo2_files    = [n for n in names if "pulse_ox" in n.lower() and n.endswith(".json")]
    sleep_files   = [n for n in names if "sleep" in n.lower() and n.endswith(".json")]
    step_files    = [n for n in names if "steps" in n.lower() and n.endswith(".json")]
    hr_files      = [n for n in names if "heart_rate" in n.lower() and n.endswith(".json")]
    summary_files = [n for n in names if "summarized" in n.lower() or "daily_summary" in n.lower()]

    for fname in spo2_files:
        data.spo2_nights.extend(_garmin_spo2(zf, fname))

    for fname in step_files + summary_files:
        data.daily_activity.extend(_garmin_steps(zf, fname))

    for fname in hr_files:
        data.daily_hr.extend(_garmin_hr(zf, fname))

    data.export_date_range = _date_range(data)
    return data


def _garmin_spo2(zf: zipfile.ZipFile, fname: str) -> list[NightlySpO2]:
    records = _load_json(zf, fname)
    nights = []
    # Garmin pulse ox: list of {startGMT, endGMT, spO2Value}
    if isinstance(records, list):
        from collections import defaultdict
        by_date: dict[str, list[float]] = defaultdict(list)
        for rec in records:
            date_str = _parse_date(str(rec.get("startGMT", ""))[:10])
            val = rec.get("spO2Value") or rec.get("value")
            if date_str and val is not None:
                try:
                    by_date[date_str].append(float(val))
                except (ValueError, TypeError):
                    pass
        for date_str, values in sorted(by_date.items()):
            mn = min(values)
            avg = sum(values) / len(values)
            dip_count = sum(1 for v in values if v < 90.0)
            nights.append(NightlySpO2(
                date=date_str,
                avg_pct=round(avg, 1),
                min_pct=round(mn, 1),
                had_significant_dip=(dip_count >= 3),
            ))
    return nights


def _garmin_steps(zf: zipfile.ZipFile, fname: str) -> list[DailyActivity]:
    records = _load_json(zf, fname)
    result = []
    if isinstance(records, list):
        for rec in records:
            date_str = _parse_date(str(rec.get("calendarDate", rec.get("date", ""))))
            steps = rec.get("totalSteps") or rec.get("steps")
            active = rec.get("activeSeconds")
            if date_str and steps is not None:
                try:
                    result.append(DailyActivity(
                        date=date_str,
                        steps=int(steps),
                        active_minutes=int(active) // 60 if active else None,
                    ))
                except (ValueError, TypeError):
                    pass
    return result


def _garmin_hr(zf: zipfile.ZipFile, fname: str) -> list[DailyHeartRate]:
    records = _load_json(zf, fname)
    result = []
    if isinstance(records, list):
        for rec in records:
            date_str = _parse_date(str(rec.get("calendarDate", rec.get("date", ""))))
            rhr = rec.get("restingHeartRateValue") or rec.get("restingHeartRate")
            if date_str:
                try:
                    result.append(DailyHeartRate(
                        date=date_str,
                        resting_hr=int(rhr) if rhr is not None else None,
                    ))
                except (ValueError, TypeError):
                    pass
    return result


# ── Utilities ─────────────────────────────────────────────────────────────────

def _load_json(zf: zipfile.ZipFile, fname: str) -> list | dict:
    try:
        with zf.open(fname) as f:
            return json.load(f)
    except Exception:
        return []


def _parse_date(s: str) -> str | None:
    if not s:
        return None
    s = s.strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%y", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(s[:10], fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return None


def _date_range(data: WearableRawData) -> tuple[str, str] | None:
    all_dates = (
        [n.date for n in data.spo2_nights]
        + [a.date for a in data.daily_activity]
        + [h.date for h in data.daily_hr]
    )
    all_dates = [d for d in all_dates if d]
    if not all_dates:
        return None
    return (min(all_dates), max(all_dates))
