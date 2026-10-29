"""Exact pure-function excerpts; no collector, API client or driver included."""
import re, unicodedata
from decimal import Decimal

def transaction_jibun(raw):
    """Identity transform only, restricted to observed numeric/explicit-san grammar.

    No trim, hyphen removal, zero conversion, mountain inference or repair.
    An unsupported raw value is preserved and excluded from candidate lookup.
    """
    if raw is None or raw=='':return 'JIBUN_INCOMPLETE',None
    require(isinstance(raw,str),'identifier_must_remain_string')
    if not re.fullmatch(r'(?:산)?[0-9]+(?:-[0-9]+)?',raw):return 'JIBUN_REPRESENTATION_UNSUPPORTED',None
    return 'JIBUN_IDENTITY_VALID',raw
