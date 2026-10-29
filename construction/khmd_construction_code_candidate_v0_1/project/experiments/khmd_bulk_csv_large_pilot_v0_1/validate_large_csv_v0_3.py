"""Exact pure-function excerpts; no collector, API client or driver included."""
import re, unicodedata
from decimal import Decimal

def need(v,c):
 if not v:raise ValueError(c)

def text(v):return re.sub(r'\s+',' ',unicodedata.normalize('NFC',v).strip())

def state(v,present=True):
 if not present:return 'ABSENT'
 if v=='':return 'EMPTY'
 if not v.strip():return 'WHITESPACE'
 if v.strip()=='-':return 'DISPLAY_DASH'
 if v.strip().upper()=='NULL':return 'NULL_LITERAL'
 if re.fullmatch(r'[+-]?0+(?:\.0+)?',v.strip().replace(',','')):return 'EXPLICIT_ZERO'
 return 'VALUE'

def optional(v):return text(v) if state(v) in ('VALUE','EXPLICIT_ZERO') else None

def num(v,decimal=False):
 v=optional(v)
 if v is None:return None
 v=v.replace(',','');need(re.fullmatch(r'-?\d+(?:\.\d+)?' if decimal else r'-?\d+',v),'INVALID_NUMBER')
 return format(Decimal(v).normalize(),'f') if decimal else str(int(v))
