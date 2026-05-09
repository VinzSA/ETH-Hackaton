"""
Medication normalizer: maps drug names to RxNorm + ATC codes.

Priority:
1. Local lookup table (top surgical drugs, no API latency)
2. Claude fallback for anything not in the table
"""
import os
import re
from functools import lru_cache

import anthropic

# Top surgical-relevant drugs with their RxNorm and ATC codes
# RxNorm: US standard | ATC: European standard
_DRUG_TABLE: dict[str, dict] = {
    # Anticoagulants
    "warfarin":      {"rxnorm": "11289",  "atc": "B01AA03"},
    "apixaban":      {"rxnorm": "1364430","atc": "B01AF02"},
    "rivaroxaban":   {"rxnorm": "1114195","atc": "B01AF01"},
    "dabigatran":    {"rxnorm": "1037042","atc": "B01AE07"},
    "edoxaban":      {"rxnorm": "1599538","atc": "B01AF03"},
    "heparin":       {"rxnorm": "5224",   "atc": "B01AB01"},
    "enoxaparin":    {"rxnorm": "67108",  "atc": "B01AB05"},
    "fondaparinux":  {"rxnorm": "321208", "atc": "B01AX05"},
    # Antiplatelets
    "aspirin":       {"rxnorm": "1191",   "atc": "B01AC06"},
    "clopidogrel":   {"rxnorm": "32968",  "atc": "B01AC04"},
    "ticagrelor":    {"rxnorm": "1116632","atc": "B01AC24"},
    "prasugrel":     {"rxnorm": "614391", "atc": "B01AC22"},
    # Beta-blockers
    "metoprolol":    {"rxnorm": "6918",   "atc": "C07AB02"},
    "bisoprolol":    {"rxnorm": "19484",  "atc": "C07AB07"},
    "carvedilol":    {"rxnorm": "20352",  "atc": "C07AG02"},
    "atenolol":      {"rxnorm": "1202",   "atc": "C07AB03"},
    # ACE inhibitors
    "lisinopril":    {"rxnorm": "29046",  "atc": "C09AA03"},
    "ramipril":      {"rxnorm": "35296",  "atc": "C09AA05"},
    "enalapril":     {"rxnorm": "3827",   "atc": "C09AA02"},
    "perindopril":   {"rxnorm": "54552",  "atc": "C09AA04"},
    # ARBs
    "losartan":      {"rxnorm": "203160", "atc": "C09CA01"},
    "valsartan":     {"rxnorm": "69749",  "atc": "C09CA03"},
    "candesartan":   {"rxnorm": "83515",  "atc": "C09CA06"},
    # Statins
    "atorvastatin":  {"rxnorm": "83367",  "atc": "C10AA05"},
    "rosuvastatin":  {"rxnorm": "301542", "atc": "C10AA07"},
    "simvastatin":   {"rxnorm": "36567",  "atc": "C10AA01"},
    # Diabetes
    "metformin":     {"rxnorm": "6809",   "atc": "A10BA02"},
    "insulin":       {"rxnorm": "5856",   "atc": "A10AB01"},
    # Pain / NSAID (relevant for bleeding risk)
    "ibuprofen":     {"rxnorm": "5640",   "atc": "M01AE01"},
    "naproxen":      {"rxnorm": "7258",   "atc": "M01AE02"},
    "diclofenac":    {"rxnorm": "3355",   "atc": "M01AB05"},
    # Anesthesia-relevant
    "propofol":      {"rxnorm": "51428",  "atc": "N01AX10"},
    "ketamine":      {"rxnorm": "6130",   "atc": "N01AX03"},
    "midazolam":     {"rxnorm": "41493",  "atc": "N05CD08"},
    "fentanyl":      {"rxnorm": "4337",   "atc": "N01AH01"},
    "morphine":      {"rxnorm": "7052",   "atc": "N02AA01"},
    # Reversal agents
    "andexanet alfa":{"rxnorm": "1856422","atc": "B06AC05"},
    "idarucizumab":  {"rxnorm": "1741052","atc": "V03AB37"},
    "protamine":     {"rxnorm": "8752",   "atc": "V03AB14"},
    "vitamin k":     {"rxnorm": "11248",  "atc": "B02BA01"},
}

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    return _client


def _normalize_name(name: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", name.lower()).strip()


def lookup_drug(name: str) -> dict[str, str | None]:
    """
    Return {"rxnorm": ..., "atc": ...} for a drug name.
    Tries local table first, falls back to Claude.
    """
    key = _normalize_name(name)
    # Direct hit
    if key in _DRUG_TABLE:
        return _DRUG_TABLE[key]

    # Partial match (handles "metoprolol succinate" → "metoprolol")
    for table_key, codes in _DRUG_TABLE.items():
        if table_key in key or key in table_key:
            return codes

    # Claude fallback
    return _claude_lookup(name)


@lru_cache(maxsize=256)
def _claude_lookup(name: str) -> dict[str, str | None]:
    try:
        client = _get_client()
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=60,
            system=(
                "You are a pharmacology assistant. Given a drug name, return ONLY a JSON object "
                'with keys "rxnorm" (RxNorm concept ID as string) and "atc" (ATC code as string). '
                "If unknown, use null. No explanation."
            ),
            messages=[{"role": "user", "content": name}],
        )
        import json, re as _re
        raw = response.content[0].text.strip()
        raw = _re.sub(r"^```(?:json)?\s*", "", raw)
        raw = _re.sub(r"\s*```$", "", raw)
        result = json.loads(raw)
        return {"rxnorm": result.get("rxnorm"), "atc": result.get("atc")}
    except Exception:
        return {"rxnorm": None, "atc": None}
