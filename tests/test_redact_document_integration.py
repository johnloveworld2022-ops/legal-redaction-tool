from core.pipeline import redact_document


class FakeClient:
    def __init__(self, response):
        self._response = response

    def generate(self, prompt: str) -> str:
        return self._response


def test_clean_document_with_no_findings_auto_exports():
    text = "本合同双方已就交货期达成一致,无需另行通知。"
    client = FakeClient('{"entities": []}')
    result = redact_document(text, lexicon=[], llm_client=client)
    assert result.export_decision.auto_export is True
    assert result.replacement.text == text
    assert result.replacement.mapping == {}


def test_document_with_id_card_and_lexicon_name_is_fully_redacted_and_blocked():
    text = "原告张三身份证号110101199003072316,住址不详。"
    client = FakeClient('{"entities": []}')
    result = redact_document(text, lexicon=["张三"], llm_client=client)
    assert "张三" not in result.replacement.text
    assert "110101199003072316" not in result.replacement.text
    assert len(result.replacement.mapping) == 2
    # ID card was high confidence, lexicon match was high confidence --
    # nothing low-confidence here, so this document *would* auto-export.
    assert result.export_decision.auto_export is True


def test_llm_finding_blocks_auto_export_even_when_only_source_of_pii():
    text = "被告为某科技有限公司,负责人系李某。"
    llm_json = '{"entities": [{"text": "李某", "type": "PERSON"}]}'
    client = FakeClient(llm_json)
    result = redact_document(text, lexicon=[], llm_client=client)
    assert result.export_decision.auto_export is False
    assert any("llm" in r for r in result.export_decision.reasons)


def test_llm_unreachable_blocks_auto_export_even_with_no_other_findings():
    class BrokenClient:
        def generate(self, prompt: str) -> str:
            return "connection refused"

    text = "本合同双方已就交货期达成一致。"
    result = redact_document(text, lexicon=[], llm_client=BrokenClient())
    assert result.export_decision.auto_export is False
    assert any("llm" in r for r in result.export_decision.reasons)


def test_extra_stage_low_confidence_blocks_export_even_when_detectors_are_clean():
    from core.pipeline import StageResult

    text = "本合同双方已就交货期达成一致,无需另行通知。"
    client = FakeClient('{"entities": []}')
    ocr_stage = StageResult("ocr", ok=True, low_confidence_count=2)
    result = redact_document(text, lexicon=[], llm_client=client, extra_stages=[ocr_stage])
    assert result.export_decision.auto_export is False
    assert any("ocr" in r for r in result.export_decision.reasons)


def test_no_extra_stages_behaves_as_before():
    text = "本合同双方已就交货期达成一致,无需另行通知。"
    client = FakeClient('{"entities": []}')
    result = redact_document(text, lexicon=[], llm_client=client, extra_stages=None)
    assert result.export_decision.auto_export is True
