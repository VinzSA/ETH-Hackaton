"""
Run the extraction pipeline on real MT Samples data.

Usage:
    cd /Users/adnana24/Downloads/hack
    export ANTHROPIC_API_KEY=sk-ant-...
    er-preop-brief/.venv/bin/python tests/run_mtsamples.py

If data/mtsamples.csv is missing, this script downloads it automatically.
"""
import json
import os
import sys
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

CSV_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "mtsamples.csv")
# Direct CSV from Kaggle mirror (no login needed)
CSV_URL = "https://raw.githubusercontent.com/jackmleitch/Whatscooking-/master/input/mtsamples.csv"
FALLBACK_URL = "https://raw.githubusercontent.com/socd06/medical-nlp/master/data/mtsamples.csv"


def download_csv():
    os.makedirs(os.path.dirname(CSV_PATH), exist_ok=True)
    print("data/mtsamples.csv not found — downloading via curl...")
    for url in [FALLBACK_URL, CSV_URL]:
        ret = os.system(f'curl -L -s -o "{CSV_PATH}" "{url}"')
        if ret == 0 and os.path.exists(CSV_PATH):
            lines = open(CSV_PATH).read().count("\n")
            if lines > 100:
                print(f"Downloaded: {lines} rows\n")
                return
    print(
        "\nAuto-download failed. Download manually:\n"
        "  https://www.kaggle.com/datasets/tboyle10/medicaltranscriptions\n"
        "  Save as: data/mtsamples.csv"
    )
    sys.exit(1)


def run():
    if not os.path.exists(CSV_PATH):
        download_csv()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ERROR: Set ANTHROPIC_API_KEY first.\n  export ANTHROPIC_API_KEY=sk-ant-...")
        sys.exit(1)

    from src.ingestion.pipeline import process_text
    from src.utils.mtsamples import load_samples

    # Pick one real note per document type
    TARGET_TYPES = [
        "discharge_summary",
        "operative_note",
        "anesthesia_record",
        "cardiology_consult",
        "lab_report",
    ]

    print("Loading MT Samples...")
    seen_types = set()
    selected = []
    for row in load_samples():
        if row["document_type"] in TARGET_TYPES and row["document_type"] not in seen_types:
            selected.append(row)
            seen_types.add(row["document_type"])
        if seen_types >= set(TARGET_TYPES):
            break

    if not selected:
        print("No samples found — check that data/mtsamples.csv loaded correctly.")
        sys.exit(1)

    print(f"Running pipeline on {len(selected)} real MT Samples notes...\n")

    all_results = []
    for row in selected:
        print("=" * 70)
        print(f"DOCUMENT TYPE : {row['document_type']}")
        print(f"SPECIALTY     : {row['specialty']}")
        print(f"TITLE         : {row['title']}")
        print(f"TEXT PREVIEW  : {row['transcription'][:200].strip()}...")
        print("-" * 70)

        result = process_text(
            row["transcription"],
            document_id=row["id"],
            document_type=row["document_type"],
        )

        print(f"Classified as : {result.document_type}")
        print(f"Confidence    : {result.extraction_confidence}")

        if result.medications:
            print(f"\nMedications ({len(result.medications)}):")
            for m in result.medications:
                anticoag = " [ANTICOAGULANT]" if m.is_anticoagulant else ""
                antiplatelet = " [ANTIPLATELET]" if m.is_antiplatelet else ""
                print(f"  - {m.name} {m.dose or ''} {m.frequency or ''}{anticoag}{antiplatelet}")
                print(f"    rxnorm={m.rxnorm_code}  atc={m.atc_code}  indication={m.indication}")

        if result.diagnoses:
            print(f"\nDiagnoses ({len(result.diagnoses)}):")
            for d in result.diagnoses:
                print(f"  - {d.description} [{d.icd10_code}]  active={d.is_active}")

        if result.allergies:
            print(f"\nAllergies ({len(result.allergies)}):")
            for a in result.allergies:
                print(f"  - {a.substance} | {a.reaction} | severity={a.severity}")

        if result.labs:
            print(f"\nLabs ({len(result.labs)}):")
            for lab in result.labs:
                print(f"  - {lab.test_name}: {lab.value} {lab.unit}  loinc={lab.loinc_code}  date={lab.measured_date}")

        if result.procedures:
            print(f"\nProcedures ({len(result.procedures)}):")
            for p in result.procedures:
                print(f"  - {p.name}  date={p.procedure_date}  complications={p.complications}")

        if result.implants:
            print(f"\nImplants ({len(result.implants)}):")
            for i in result.implants:
                print(f"  - {i.description}  site={i.body_site}  date={i.implanted_date}")

        if result.anesthesia_history:
            a = result.anesthesia_history[0]
            print(f"\nAnesthesia:")
            print(f"  ASA={a.asa_score}  type={a.anesthesia_type}")
            print(f"  Airway: {a.airway_notes}")
            print(f"  Complications: {a.complications}")

        if result.cardiac:
            c = result.cardiac[0]
            print(f"\nCardiac:")
            print(f"  EF={c.ejection_fraction_pct}%  NYHA={c.nyha_class}")
            print(f"  MI={c.has_history_mi}  Stents={c.has_stents}  AF={c.has_atrial_fibrillation}")

        if result.extraction_warnings:
            print(f"\nWarnings:")
            for w in result.extraction_warnings:
                print(f"  ⚠  {w}")

        all_results.append({"input": row, "output": result.model_dump()})

    # Save full JSON output for backend team
    out_path = os.path.join(os.path.dirname(__file__), "..", "data", "mtsamples_output.json")
    with open(out_path, "w") as f:
        json.dump(all_results, f, indent=2, default=str)

    print("\n" + "=" * 70)
    print(f"DONE — {len(all_results)} documents processed")
    print(f"Full JSON saved to: data/mtsamples_output.json")
    print("=" * 70)


if __name__ == "__main__":
    run()
