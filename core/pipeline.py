from dataclasses import dataclass, field

from core.detectors_regex import detect_structured_pii
from core.lexicon_matcher import match_lexicon
from core.llm_detector import detect_llm_entities
from core.merge_replace import ReplacementResult, apply_replacements, merge_spans
from core.spans import Span


@dataclass
class StageResult:
    name: str
    ok: bool
    low_confidence_count: int = 0


@dataclass
class ExportDecision:
    auto_export: bool
    reasons: list[str] = field(default_factory=list)


def decide_export(stages: list["StageResult"]) -> ExportDecision:
    """Auto-export is allowed only when every detection stage ran
    successfully AND found nothing it isn't confident about. A stage that
    failed to run (e.g. Ollama unreachable) is treated the same as a stage
    that found something suspicious -- both block the one-click path and
    require the second, explicit approval click. Silently exporting after
    a detector layer failed to run would be indistinguishable, from the
    output alone, from that layer having genuinely found nothing.
    """
    reasons: list[str] = []
    for s in stages:
        if not s.ok:
            reasons.append(f"{s.name} 检测未能正常完成,需人工确认")
        elif s.low_confidence_count > 0:
            reasons.append(f"{s.name} 发现 {s.low_confidence_count} 处需人工核实的疑似内容")
    return ExportDecision(auto_export=(len(reasons) == 0), reasons=reasons)


@dataclass
class DocumentRedactionResult:
    replacement: ReplacementResult
    stages: list[StageResult]
    export_decision: ExportDecision


def redact_document(
    text: str,
    lexicon: list[str],
    llm_client,
    existing_mapping: dict[str, str] | None = None,
    extra_stages: list[StageResult] | None = None,
) -> DocumentRedactionResult:
    """Run every detector on one document's already-extracted text, merge
    their findings, and apply the deterministic replacement. Pass the
    case's running mapping in via ``existing_mapping`` so the same real
    name gets the same token across every document in a case, not just
    within one call. ``extra_stages`` lets the caller fold in signals from
    outside entity detection (e.g. an OCR confidence stage from
    core.convert) into the same auto-export gate, so a suspect OCR page
    blocks the one-click path exactly like a suspect entity does -- one
    decision function, not two competing gates. Multi-document /
    folder-level orchestration and file I/O live in the CLI entry point,
    not here -- this function only ever sees text in memory.
    """
    stages: list[StageResult] = list(extra_stages or [])
    all_spans: list[Span] = []

    regex_spans = detect_structured_pii(text)
    stages.append(
        StageResult(
            "regex", ok=True,
            low_confidence_count=sum(1 for s in regex_spans if s.confidence == "low"),
        )
    )
    all_spans.extend(regex_spans)

    lexicon_spans = match_lexicon(text, lexicon)
    stages.append(StageResult("lexicon", ok=True, low_confidence_count=0))
    all_spans.extend(lexicon_spans)

    llm_result = detect_llm_entities(text, llm_client)
    stages.append(
        StageResult("llm", ok=llm_result.ok, low_confidence_count=len(llm_result.spans))
    )
    all_spans.extend(llm_result.spans)

    merged = merge_spans(all_spans)
    replacement = apply_replacements(text, merged, existing_mapping=existing_mapping)
    decision = decide_export(stages)

    return DocumentRedactionResult(
        replacement=replacement, stages=stages, export_decision=decision
    )
