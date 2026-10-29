"""Exact pure-function excerpts; no collector, API client or driver included."""
import re, unicodedata
from decimal import Decimal

def _integer(value: object, name: str) -> int:
    if isinstance(value, bool) or not re.fullmatch(r"[0-9]+", str(value)):
        raise ValueError(f"{name} must be an explicit integer component")
    return int(str(value))

def quarter_id(year: object, month: object) -> str:
    """Contract calendar components only; invalid/missing values fail closed."""
    y, m = _integer(year, "year"), _integer(month, "month")
    if not 1 <= y <= 9999 or not 1 <= m <= 12:
        raise ValueError("contract year/month out of range")
    return f"{y:04d}Q{(m - 1) // 3 + 1}"
