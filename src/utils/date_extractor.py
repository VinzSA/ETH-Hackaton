"""
Pulls the document date from the header of a clinical note.
Used to populate ExtractedDocument.document_date and feed temporal reconciliation.
"""
import re
from datetime import datetime, date


# Regex patterns ordered by specificity — try them in order, stop at first match
_PATTERNS = [
    # ISO: 2024-01-15
    r"\b(\d{4}-\d{2}-\d{2})\b",
    # US long: January 15, 2024 / Jan 15, 2024
    r"\b((?:January|February|March|April|May|June|July|August|September|October|November|December"
    r"|Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\.?\s+\d{1,2},?\s+\d{4})\b",
    # EU: 15/01/2024 or 15.01.2024
    r"\b(\d{1,2}[./]\d{1,2}[./]\d{4})\b",
    # US: 01/15/2024
    r"\b(\d{2}/\d{2}/\d{4})\b",
]

_MONTH_MAP = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4,
    "jun": 6, "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def extract_document_date(text: str, search_chars: int = 600) -> str | None:
    """
    Extract the document date from the first `search_chars` characters.
    Returns ISO 8601 string (YYYY-MM-DD) or None.
    Headers carry the date; searching the full document would pick up patient birthdates etc.
    """
    header = text[:search_chars]

    for pattern in _PATTERNS:
        match = re.search(pattern, header, re.IGNORECASE)
        if match:
            parsed = _parse_date_string(match.group(1))
            if parsed:
                # Sanity check: date must be plausible (1990-2030)
                if 1990 <= parsed.year <= 2030:
                    return parsed.isoformat()

    return None


def _parse_date_string(s: str) -> date | None:
    s = s.strip().rstrip(",")

    # ISO
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        pass

    # Long month name: "January 15, 2024" or "Jan 15 2024"
    m = re.match(
        r"(\w+)\.?\s+(\d{1,2}),?\s+(\d{4})", s, re.IGNORECASE
    )
    if m:
        month_str = m.group(1).lower().rstrip(".")
        month = _MONTH_MAP.get(month_str)
        if month:
            try:
                return date(int(m.group(3)), month, int(m.group(2)))
            except ValueError:
                pass

    # EU dot/slash: 15.01.2024 or 15/01/2024
    m = re.match(r"(\d{1,2})[./](\d{1,2})[./](\d{4})", s)
    if m:
        try:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            pass

    # US slash: 01/15/2024
    try:
        return datetime.strptime(s, "%m/%d/%Y").date()
    except ValueError:
        pass

    return None


def days_since(iso_date: str | None) -> int | None:
    """Return how many days ago the document date is. None if no date."""
    if not iso_date:
        return None
    try:
        doc_date = datetime.strptime(iso_date, "%Y-%m-%d").date()
        return (date.today() - doc_date).days
    except ValueError:
        return None


def is_stale(iso_date: str | None, threshold_days: int = 180) -> bool:
    """Returns True if the date is older than threshold_days (default 6 months)."""
    age = days_since(iso_date)
    if age is None:
        return False
    return age > threshold_days
