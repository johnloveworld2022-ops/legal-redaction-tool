from core.spans import Span

_ORG_KEYWORDS = ["公司", "集团", "事务所", "银行", "医院", "法院", "学校", "协会", "中心", "厂"]


def _classify(entry: str) -> str:
    return "ORG" if any(k in entry for k in _ORG_KEYWORDS) else "PERSON"


def match_lexicon(text: str, lexicon: list[str]) -> list[Span]:
    """Match the case-specific name list the lawyer fills in by hand at the
    start of a case (party names, company names, etc.) against the text.

    This is plain contiguous-substring matching, not per-character fuzzy
    matching -- Chinese has no word boundaries, so a bag-of-characters
    approach would spuriously match a name's characters scattered across
    unrelated words. A small, case-scoped, human-curated list matched
    exactly is the most reliable detector in this whole pipeline, precisely
    because its search space is tiny.
    """
    spans: list[Span] = []
    for entry in lexicon:
        if not entry:
            continue
        entity_type = _classify(entry)
        start = 0
        while True:
            idx = text.find(entry, start)
            if idx == -1:
                break
            spans.append(Span(idx, idx + len(entry), entity_type, "high", source="lexicon"))
            start = idx + len(entry)
    return spans
