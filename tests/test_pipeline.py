import pytest
from core.pipeline import decide_export, StageResult


def test_all_stages_clean_and_no_low_confidence_items_allows_auto_export():
    stages = [
        StageResult(name="regex", ok=True, low_confidence_count=0),
        StageResult(name="lexicon", ok=True, low_confidence_count=0),
        StageResult(name="llm", ok=True, low_confidence_count=0),
    ]
    decision = decide_export(stages)
    assert decision.auto_export is True
    assert decision.reasons == []


def test_any_low_confidence_item_blocks_auto_export():
    stages = [
        StageResult(name="regex", ok=True, low_confidence_count=1),
        StageResult(name="lexicon", ok=True, low_confidence_count=0),
        StageResult(name="llm", ok=True, low_confidence_count=0),
    ]
    decision = decide_export(stages)
    assert decision.auto_export is False
    assert any("regex" in r for r in decision.reasons)


def test_a_failed_stage_blocks_auto_export_even_with_zero_findings():
    # Ollama unreachable -> llm stage failed. Must not be treated as
    # "ran cleanly and found nothing" -- that would silently drop a
    # whole detection layer and could ship an undetected leak.
    stages = [
        StageResult(name="regex", ok=True, low_confidence_count=0),
        StageResult(name="lexicon", ok=True, low_confidence_count=0),
        StageResult(name="llm", ok=False, low_confidence_count=0),
    ]
    decision = decide_export(stages)
    assert decision.auto_export is False
    assert any("llm" in r for r in decision.reasons)


def test_multiple_problems_all_reported_not_just_first():
    stages = [
        StageResult(name="regex", ok=True, low_confidence_count=2),
        StageResult(name="lexicon", ok=False, low_confidence_count=0),
        StageResult(name="llm", ok=True, low_confidence_count=0),
    ]
    decision = decide_export(stages)
    assert decision.auto_export is False
    assert len(decision.reasons) == 2
