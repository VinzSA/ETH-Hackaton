"""
Wearable pipeline tests — no API key needed, all computation is local.

Run with:  python tests/test_wearable.py
"""
from __future__ import annotations
import io
import json
import os
import sys
import zipfile
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ── Synthetic ZIP builders ────────────────────────────────────────────────────

def _make_fitbit_zip(
    n_nights: int = 30,
    dip_nights: int = 8,       # nights where SpO2 dips below 90%
    avg_steps: int = 6_000,
    resting_hr_start: int = 68,
    hr_trend: float = 0.0,     # bpm/day (positive = rising)
) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        # SpO2 nightly summaries
        spo2_data = []
        for i in range(n_nights):
            d = (datetime.today() - timedelta(days=n_nights - i)).strftime("%Y-%m-%d")
            is_dip = i < dip_nights
            spo2_data.append({
                "dateTime": d,
                "value": {
                    "avg": 95.0 if not is_dip else 91.0,
                    "min": 93.0 if not is_dip else 87.5,
                    "max": 99.0,
                }
            })
        zf.writestr("spo2/spo2-2024-01.json", json.dumps(spo2_data))

        # Steps
        steps_data = []
        for i in range(30):
            d = (datetime.today() - timedelta(days=30 - i)).strftime("%Y-%m-%d")
            import random; random.seed(i)
            steps_data.append({"dateTime": d, "value": str(avg_steps + random.randint(-500, 500))})
        zf.writestr("physical-activity/steps-2024-01.json", json.dumps(steps_data))

        # Heart rate (with optional trend)
        hr_data = []
        for i in range(60):
            d = (datetime.today() - timedelta(days=60 - i)).strftime("%Y-%m-%d")
            rhr = int(resting_hr_start + hr_trend * i)
            hr_data.append({"dateTime": d, "value": {"restingHeartRate": rhr}})
        zf.writestr("heart-rate/heart_rate-2024-01.json", json.dumps(hr_data))

    return buf.getvalue()


def _make_garmin_zip(
    n_nights: int = 21,
    dip_nights: int = 2,
    avg_steps: int = 9_000,
) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        # Pulse ox
        spo2_data = []
        for i in range(n_nights):
            d = (datetime.today() - timedelta(days=n_nights - i)).strftime("%Y-%m-%dT00:00:00")
            for minute in range(0, 360, 30):  # 6 hours of sleep
                val = 87.0 if (i < dip_nights and minute < 90) else 96.0
                spo2_data.append({"startGMT": d, "spO2Value": val})
        zf.writestr("DI_CONNECT/pulse_ox_data.json", json.dumps(spo2_data))

        # Steps
        steps_data = []
        for i in range(30):
            d = (datetime.today() - timedelta(days=30 - i)).strftime("%Y-%m-%d")
            steps_data.append({"calendarDate": d, "totalSteps": avg_steps + i * 10})
        zf.writestr("DI_CONNECT/steps_data.json", json.dumps(steps_data))

        # Heart rate
        hr_data = []
        for i in range(45):
            d = (datetime.today() - timedelta(days=45 - i)).strftime("%Y-%m-%d")
            hr_data.append({"calendarDate": d, "restingHeartRateValue": 62 + i // 10})
        zf.writestr("DI_CONNECT/heart_rate_data.json", json.dumps(hr_data))

    return buf.getvalue()


# ── Test helpers ──────────────────────────────────────────────────────────────

def section(title: str):
    print(f"\n{'='*65}")
    print(f"  {title}")
    print(f"{'='*65}")


def print_signals(signals):
    print(f"Device:          {signals.device}")
    print(f"Date range:      {signals.export_date_range}")

    if signals.osa:
        o = signals.osa
        print(f"\nOSA Signal:")
        print(f"  Probable OSA:     {o.probable_osa}  (confidence {o.confidence:.0%})")
        print(f"  Nights analyzed:  {o.nights_analyzed}")
        print(f"  Nights with dips: {o.nights_with_dips} ({o.dip_rate:.1%})")
        print(f"  Avg min SpO2:     {o.avg_min_spo2}%")
        print(f"  SourceRef:        '{o.source.snippet}'")

    if signals.functional_capacity:
        fc = signals.functional_capacity
        print(f"\nFunctional Capacity:")
        print(f"  Level:            {fc.level}")
        print(f"  Avg steps/day:    {int(fc.avg_daily_steps_30d):,}")
        print(f"  Days analyzed:    {fc.days_analyzed}")
        print(f"  Active min/day:   {fc.avg_active_minutes_30d}")
        print(f"  SourceRef:        '{fc.source.snippet}'")

    if signals.hr_trend:
        hr = signals.hr_trend
        print(f"\nHR Trend:")
        print(f"  Trend:            {hr.trend}")
        print(f"  Slope:            {hr.slope_bpm_per_day:+.3f} bpm/day")
        print(f"  Avg resting HR:   {hr.avg_resting_hr} bpm")
        print(f"  Days analyzed:    {hr.days_analyzed}")


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_fitbit_reader():
    from src.ingestion.wearable_reader import read_wearable_zip

    section("TEST 1 — Fitbit reader: format detection + raw parsing")
    zip_bytes = _make_fitbit_zip(n_nights=30, dip_nights=8)
    raw = read_wearable_zip(zip_bytes)

    print(f"Format detected:  {raw.source}  {'OK' if raw.source == 'fitbit' else 'FAIL'}")
    print(f"SpO2 nights:      {len(raw.spo2_nights)}")
    print(f"Activity days:    {len(raw.daily_activity)}")
    print(f"HR days:          {len(raw.daily_hr)}")
    print(f"Date range:       {raw.export_date_range}")

    dips = sum(1 for n in raw.spo2_nights if n.had_significant_dip)
    print(f"Nights with dips: {dips} (expected ~8)")

    assert raw.source == "fitbit"
    assert len(raw.spo2_nights) == 30
    assert dips == 8
    print("  → PASS")


def test_garmin_reader():
    from src.ingestion.wearable_reader import read_wearable_zip

    section("TEST 2 — Garmin reader: format detection + raw parsing")
    zip_bytes = _make_garmin_zip(n_nights=21, dip_nights=2)
    raw = read_wearable_zip(zip_bytes)

    print(f"Format detected:  {raw.source}  {'OK' if raw.source == 'garmin' else 'FAIL'}")
    print(f"SpO2 nights:      {len(raw.spo2_nights)}")
    print(f"Activity days:    {len(raw.daily_activity)}")
    print(f"HR days:          {len(raw.daily_hr)}")

    assert raw.source == "garmin"
    assert len(raw.daily_activity) > 0
    print("  → PASS")


def test_osa_positive():
    from src.ingestion.wearable_reader import read_wearable_zip
    from src.extractors.wearable_extractor import extract_wearable_signals

    section("TEST 3 — OSA signal: HIGH dip rate → probable OSA")
    # 12/30 nights = 40% dip rate → probable OSA, high confidence
    zip_bytes = _make_fitbit_zip(n_nights=30, dip_nights=12)
    raw = read_wearable_zip(zip_bytes)
    signals = extract_wearable_signals(raw)
    print_signals(signals)

    assert signals.osa is not None
    assert signals.osa.probable_osa is True
    assert signals.osa.confidence >= 0.65
    print("  → PASS")


def test_osa_negative():
    from src.ingestion.wearable_reader import read_wearable_zip
    from src.extractors.wearable_extractor import extract_wearable_signals

    section("TEST 4 — OSA signal: LOW dip rate → OSA unlikely")
    zip_bytes = _make_fitbit_zip(n_nights=30, dip_nights=2)
    raw = read_wearable_zip(zip_bytes)
    signals = extract_wearable_signals(raw)

    o = signals.osa
    print(f"Probable OSA: {o.probable_osa}  (dip rate {o.dip_rate:.1%})")
    assert o.probable_osa is False
    print("  → PASS")


def test_functional_capacity():
    from src.ingestion.wearable_reader import read_wearable_zip
    from src.extractors.wearable_extractor import extract_wearable_signals

    section("TEST 5 — Functional capacity levels")
    for avg_steps, expected_level in [(2_000, "low"), (5_500, "moderate"), (10_000, "high")]:
        zip_bytes = _make_fitbit_zip(avg_steps=avg_steps)
        raw = read_wearable_zip(zip_bytes)
        signals = extract_wearable_signals(raw)
        fc = signals.functional_capacity
        status = "OK" if fc.level == expected_level else f"FAIL (got {fc.level})"
        print(f"  {avg_steps:,} steps/day → {fc.level}  {status}")
        assert fc.level == expected_level
    print("  → PASS")


def test_hr_trend():
    from src.ingestion.wearable_reader import read_wearable_zip
    from src.extractors.wearable_extractor import extract_wearable_signals

    section("TEST 6 — Resting HR trend detection")
    for trend_slope, expected_trend in [(0.25, "rising"), (0.0, "stable"), (-0.3, "falling")]:
        zip_bytes = _make_fitbit_zip(hr_trend=trend_slope)
        raw = read_wearable_zip(zip_bytes)
        signals = extract_wearable_signals(raw)
        hr = signals.hr_trend
        status = "OK" if hr.trend == expected_trend else f"FAIL (got {hr.trend})"
        print(f"  slope {trend_slope:+.2f} bpm/day → {hr.trend}  {status}")
        assert hr.trend == expected_trend
    print("  → PASS")


def test_cross_source_gap_rules():
    from src.ingestion.wearable_reader import read_wearable_zip
    from src.extractors.wearable_extractor import extract_wearable_signals
    from src.ingestion.merger import PatientRecord, apply_wearable_signals, merge_documents
    from src.schema.preop_brief import AnesthesiaHistory, SourceRef

    section("TEST 7 — Cross-source gap rules (wearable ↔ clinical)")

    # Scenario A: probable OSA from wearable, no CPAP in clinical records
    print("\nScenario A: OSA signal + no CPAP in records")
    zip_bytes = _make_fitbit_zip(n_nights=30, dip_nights=12)
    raw = read_wearable_zip(zip_bytes)
    signals = extract_wearable_signals(raw)

    record = PatientRecord(patient_id="test_osa")
    apply_wearable_signals(record, signals)

    osa_warnings = [w for w in record.warnings if "OSA" in w or "SpO" in w]
    print(f"  OSA warning fired: {bool(osa_warnings)}")
    for w in osa_warnings:
        print(f"  ⚠  {w}")
    assert osa_warnings, "Expected OSA warning"

    # Scenario B: wearable says high capacity but prior ASA=3
    print("\nScenario B: High functional capacity + ASA III")
    zip_bytes = _make_fitbit_zip(avg_steps=10_000)
    raw = read_wearable_zip(zip_bytes)
    signals = extract_wearable_signals(raw)

    dummy_source = SourceRef(
        document_id="test", document_type="anesthesia_record",
        page=1, char_start=0, char_end=10, snippet="ASA III"
    )
    record2 = PatientRecord(patient_id="test_asa")
    record2.anesthesia_history = [AnesthesiaHistory(asa_score=3, source=dummy_source)]
    apply_wearable_signals(record2, signals)

    asa_warnings = [w for w in record2.warnings if "ASA" in w]
    print(f"  ASA conflict warning fired: {bool(asa_warnings)}")
    for w in asa_warnings:
        print(f"  ⚠  {w}")
    assert asa_warnings, "Expected ASA conflict warning"

    # Scenario C: low functional capacity → risk flag
    print("\nScenario C: Low functional capacity")
    zip_bytes = _make_fitbit_zip(avg_steps=2_000)
    raw = read_wearable_zip(zip_bytes)
    signals = extract_wearable_signals(raw)

    record3 = PatientRecord(patient_id="test_low_fc")
    apply_wearable_signals(record3, signals)

    low_fc_warnings = [w for w in record3.warnings if "Low functional" in w]
    print(f"  Low capacity warning fired: {bool(low_fc_warnings)}")
    for w in low_fc_warnings:
        print(f"  ⚠  {w}")
    assert low_fc_warnings, "Expected low functional capacity warning"

    print("  → PASS")


def test_full_patient_pipeline():
    """Integration: PDFs + wearable ZIP → PatientRecord with all signals."""
    from src.ingestion.pipeline import process_patient

    section("TEST 8 — Full process_patient() with wearable ZIP (no API needed)")
    print("(Using empty PDF list — wearable only)")

    zip_bytes = _make_fitbit_zip(n_nights=30, dip_nights=10, avg_steps=2_500, hr_trend=0.2)

    record = process_patient(
        sources=[],
        patient_id="wearable_only_test",
        texts=[],
        wearable_path=zip_bytes,
    )

    print(f"Patient ID:              {record.patient_id}")
    print(f"OSA signal present:      {record.wearable_osa_signal is not None}")
    print(f"Functional cap present:  {record.wearable_functional_capacity is not None}")
    print(f"HR trend present:        {record.wearable_hr_trend is not None}")
    print(f"\nWearable warnings ({len(record.warnings)}):")
    for w in record.warnings:
        print(f"  ⚠  {w}")

    assert record.wearable_osa_signal is not None
    assert record.wearable_functional_capacity is not None
    assert record.wearable_hr_trend is not None
    assert any("OSA" in w or "SpO" in w for w in record.warnings)
    assert any("functional" in w.lower() for w in record.warnings)

    import json
    out = os.path.join(os.path.dirname(__file__), "..", "data", "wearable_patient_record.json")
    with open(out, "w") as f:
        json.dump(record.to_dict(), f, indent=2, default=str)
    print(f"\nFull JSON saved → data/wearable_patient_record.json")
    print("  → PASS")


if __name__ == "__main__":
    test_fitbit_reader()
    test_garmin_reader()
    test_osa_positive()
    test_osa_negative()
    test_functional_capacity()
    test_hr_trend()
    test_cross_source_gap_rules()
    test_full_patient_pipeline()

    print(f"\n{'='*65}")
    print("  ALL WEARABLE TESTS PASSED")
    print(f"{'='*65}\n")
