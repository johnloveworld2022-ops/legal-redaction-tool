import re
from dataclasses import dataclass, field

from core.spans import Span

_TOKEN_RE = re.compile(r"⟦([^\d⟧]+)(\d+)⟧")

_TYPE_LABELS = {
    "PERSON": "人名",
    "ORG": "机构",
    "ID_CARD": "身份证",
    "PHONE": "电话",
    "BANK_CARD": "银行卡",
    "EMAIL": "邮箱",
    "ADDRESS": "地址",
    "BIRTHDATE": "出生日期",
    "CASE_NUMBER": "案号",
}

_CONFIDENCE_RANK = {"high": 1, "low": 0}


def _pick_best(cluster: list[Span]) -> Span:
    best = cluster[0]
    for s in cluster[1:]:
        if _CONFIDENCE_RANK[s.confidence] > _CONFIDENCE_RANK[best.confidence]:
            best = s
        elif _CONFIDENCE_RANK[s.confidence] == _CONFIDENCE_RANK[best.confidence]:
            if (s.end - s.start) < (best.end - best.start):
                best = s
    return best


def merge_spans(spans: list[Span]) -> list[Span]:
    """Collapse overlapping candidate spans from independent detectors into
    a single non-overlapping list, so downstream replacement never touches
    the same character twice. Within an overlapping cluster, the
    higher-confidence (and, on a tie, narrower) span wins.
    """
    if not spans:
        return []
    ordered = sorted(spans, key=lambda s: (s.start, s.end))
    merged: list[Span] = []
    cluster = [ordered[0]]
    cluster_end = ordered[0].end
    for s in ordered[1:]:
        if s.start < cluster_end:
            cluster.append(s)
            cluster_end = max(cluster_end, s.end)
        else:
            merged.append(_pick_best(cluster))
            cluster = [s]
            cluster_end = s.end
    merged.append(_pick_best(cluster))
    return merged


@dataclass
class ReplacementResult:
    text: str
    mapping: dict[str, str] = field(default_factory=dict)


def apply_replacements(
    text: str,
    spans: list[Span],
    existing_mapping: dict[str, str] | None = None,
) -> ReplacementResult:
    """Deterministically substitute each (already-merged, non-overlapping)
    span with a stable placeholder token. The same real string always gets
    the same token, so a name repeated through a document -- or across
    every document in the same case, when ``existing_mapping`` is passed
    in from the case's running mapping store -- reads consistently.
    Characters outside a span are copied verbatim -- never touched, never
    regenerated. The returned ``mapping`` is cumulative (existing entries
    plus any new ones), ready to be saved straight back to the store.
    """
    ordered = sorted(spans, key=lambda s: s.start)
    mapping: dict[str, str] = dict(existing_mapping or {})
    string_to_token: dict[str, str] = {v: k for k, v in mapping.items()}
    type_counters: dict[str, int] = {}
    for token in mapping:
        m = _TOKEN_RE.match(token)
        if m:
            label, num = m.group(1), int(m.group(2))
            type_counters[label] = max(type_counters.get(label, 0), num)

    parts: list[str] = []
    cursor = 0
    for span in ordered:
        parts.append(text[cursor:span.start])
        real_string = text[span.start:span.end]
        token = string_to_token.get(real_string)
        if token is None:
            label = _TYPE_LABELS.get(span.entity_type, "信息")
            type_counters[label] = type_counters.get(label, 0) + 1
            token = f"⟦{label}{type_counters[label]:03d}⟧"
            string_to_token[real_string] = token
            mapping[token] = real_string
        parts.append(token)
        cursor = span.end
    parts.append(text[cursor:])

    return ReplacementResult(text="".join(parts), mapping=mapping)
