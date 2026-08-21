from dataclasses import dataclass, field

from core.detectors_regex import detect_structured_pii
from core.lexicon_matcher import match_lexicon


@dataclass
class LeakCheckResult:
    ok: bool
    leaks: list[str] = field(default_factory=list)


def verify_no_leak(
    redacted_text: str, mapping: dict[str, str], lexicon: list[str] | None = None,
) -> LeakCheckResult:
    """Independent re-check of the FINAL text about to be exported, run
    right before it reaches 03_已批准可上传/ -- separate from, and never
    trusting, the detection pipeline's own bookkeeping (StageResult.ok /
    export_decision). The detection stages can only report "here is what
    I found"; they cannot prove the absence of what they missed. This
    exists because that's exactly the gap: a bug in merge_replace's
    dedup, a value split across a chunk boundary, or a detector that
    simply never ran on some region would all currently produce a
    redacted_text that looks clean by the pipeline's own accounting while
    still containing the original sensitive value.

    Three independent checks, any one failing is a leak:
    1. Every real value the pipeline itself already mapped to a token
       must not still appear anywhere in the final text (proves the
       replacement step didn't miss an occurrence of something it
       already knew was sensitive).
    2. Re-running the structured regex detector (ID card / phone / bank
       card / email / birthdate / case number) on the OUTPUT text itself
       must find nothing -- a genuinely redacted document should contain
       no such pattern at all, regardless of whether the pipeline's
       detectors happened to catch it during processing.
    3. Re-running the case's own curated name list (lexicon) against the
       OUTPUT text must find nothing. This closes a real blind spot:
       checks 1-2 alone can never catch a name that was missed by BOTH
       the lexicon-match stage and the LLM stage during processing (so it
       was never added to `mapping` at all) -- names/orgs/addresses have
       no regex signature to fall back on. The lexicon is the one
       detector cheap and reliable enough to safely re-run here without
       another model call; a full re-check would also re-run the LLM
       detector on the output, which is a separate, deliberate,
       more-expensive decision (another model call per document) left to
       the caller. Found via external security/testing review; see
       grill-report-2026-08-21.md.
    """
    leaks: list[str] = []

    for real_value in mapping.values():
        if real_value and real_value in redacted_text:
            leaks.append(f"「{real_value}」的脱敏未完全生效,在最终文本中仍能找到")

    for span in detect_structured_pii(redacted_text):
        found_text = redacted_text[span.start:span.end]
        leaks.append(f"最终文本中发现疑似残留的敏感信息({span.entity_type}): 「{found_text}」")

    for span in match_lexicon(redacted_text, lexicon or []):
        found_text = redacted_text[span.start:span.end]
        leaks.append(
            f"最终文本中发现「案件人员清单」里的姓名/机构名仍未脱敏: 「{found_text}」"
        )

    return LeakCheckResult(ok=(len(leaks) == 0), leaks=leaks)
