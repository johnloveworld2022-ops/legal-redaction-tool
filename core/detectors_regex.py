import re

from core.spans import Span

_ID_CARD_RE = re.compile(r"\d{17}[\dXx]")
_PHONE_RE = re.compile(r"1[3-9]\d{9}")
_BANK_CARD_RE = re.compile(r"\d{16,19}")
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

_ID_CHECK_WEIGHTS = [7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2]
_ID_CHECK_CODES = "10X98765432"


def _id_checksum_valid(id_str: str) -> bool:
    digits = id_str[:17]
    if not digits.isdigit():
        return False
    total = sum(int(d) * w for d, w in zip(digits, _ID_CHECK_WEIGHTS))
    expected = _ID_CHECK_CODES[total % 11]
    return id_str[17].upper() == expected


def detect_structured_pii(text: str) -> list[Span]:
    """Regex-based detection of structured PII.

    Checksums (ID card) only raise confidence -- they are never a gate for
    whether something gets reported. OCR routinely mangles a single digit,
    which would flip a real ID's checksum to "invalid"; silently dropping
    those would be a leak, not a safe default.
    """
    spans: list[Span] = []

    for m in _ID_CARD_RE.finditer(text):
        candidate = m.group()
        confidence = "high" if _id_checksum_valid(candidate) else "low"
        spans.append(
            Span(m.start(), m.end(), "ID_CARD", confidence, source="regex")
        )

    id_card_ranges = {(s.start, s.end) for s in spans}

    for m in _PHONE_RE.finditer(text):
        span_range = (m.start(), m.end())
        # avoid double-reporting a phone-shaped substring that's actually
        # part of an already-detected 18-digit ID candidate
        if any(a <= span_range[0] and span_range[1] <= b for a, b in id_card_ranges):
            continue
        spans.append(Span(m.start(), m.end(), "PHONE", "high", source="regex"))

    phone_ranges = {(s.start, s.end) for s in spans if s.entity_type == "PHONE"}

    for m in _BANK_CARD_RE.finditer(text):
        span_range = (m.start(), m.end())
        if any(a <= span_range[0] and span_range[1] <= b for a, b in id_card_ranges):
            continue
        if span_range in phone_ranges:
            continue
        spans.append(Span(m.start(), m.end(), "BANK_CARD", "high", source="regex"))

    for m in _EMAIL_RE.finditer(text):
        spans.append(Span(m.start(), m.end(), "EMAIL", "high", source="regex"))

    return spans
