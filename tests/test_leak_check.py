from core.leak_check import verify_no_leak


def test_clean_redacted_text_passes():
    text = "原告⟦人名001⟧身份证号⟦身份证001⟧,住⟦地址001⟧。"
    mapping = {
        "⟦人名001⟧": "张三",
        "⟦身份证001⟧": "110101199003072316",
        "⟦地址001⟧": "北京市朝阳区建国路88号",
    }
    result = verify_no_leak(text, mapping)
    assert result.ok is True
    assert result.leaks == []


def test_mapped_real_value_still_present_in_output_is_a_leak():
    # simulates a merge/replace bug: the token appears, but so does the
    # real name somewhere else in the text that wasn't replaced
    text = "原告⟦人名001⟧诉称,张三本人到庭。身份证号⟦身份证001⟧。"
    mapping = {"⟦人名001⟧": "张三", "⟦身份证001⟧": "110101199003072316"}
    result = verify_no_leak(text, mapping)
    assert result.ok is False
    assert any("张三" in leak for leak in result.leaks)


def test_fresh_id_card_pattern_not_in_mapping_is_a_leak():
    # a structured PII pattern the pipeline never detected/mapped at all
    # (e.g. a detector bug, or a value split across a chunk boundary) --
    # independent re-scan of the OUTPUT itself must still catch it
    text = "原告⟦人名001⟧,另一身份证号110101198503125678未被处理。"
    mapping = {"⟦人名001⟧": "张三"}
    result = verify_no_leak(text, mapping)
    assert result.ok is False
    assert any("110101198503125678" in leak for leak in result.leaks)


def test_fresh_phone_pattern_not_in_mapping_is_a_leak():
    text = "如有疑问请拨打13812345678,与本案脱敏无关的号码。"
    result = verify_no_leak(text, mapping={})
    assert result.ok is False
    assert any("13812345678" in leak for leak in result.leaks)


def test_empty_mapping_and_clean_text_passes():
    result = verify_no_leak("本合同双方已就交货期达成一致。", mapping={})
    assert result.ok is True
    assert result.leaks == []


def test_token_placeholders_themselves_are_not_flagged_as_leaks():
    # the placeholder tokens are expected to be present -- only the real
    # values behind them, or fresh undetected PII, count as leaks
    text = "原告⟦人名001⟧诉被告⟦机构001⟧合同纠纷。"
    mapping = {"⟦人名001⟧": "张三", "⟦机构001⟧": "北京鑫达贸易有限公司"}
    result = verify_no_leak(text, mapping)
    assert result.ok is True


def test_lexicon_name_missed_by_the_entire_pipeline_is_caught_on_output_rescan():
    # This is the gap the leak-check's own docstring previously claimed to
    # cover but didn't: a name that BOTH the lexicon-match stage and the
    # LLM stage somehow failed to catch during processing (so it was never
    # added to `mapping` at all) has no regex signature to fall back on --
    # the only way to catch it is re-running match_lexicon against the
    # final output, using the case's own curated name list.
    text = "原告李四诉被告某某公司合同纠纷。⟦身份证001⟧已核实。"
    mapping = {"⟦身份证001⟧": "110101199003072316"}
    result = verify_no_leak(text, mapping, lexicon=["李四"])
    assert result.ok is False
    assert any("李四" in leak for leak in result.leaks)


def test_lexicon_name_already_replaced_is_not_a_leak():
    text = "原告⟦人名001⟧诉被告某某公司合同纠纷。"
    mapping = {"⟦人名001⟧": "李四"}
    result = verify_no_leak(text, mapping, lexicon=["李四"])
    assert result.ok is True


def test_no_lexicon_argument_is_backward_compatible():
    # existing callers that don't pass lexicon must keep working exactly
    # as before (defaults to no lexicon re-check)
    text = "本合同双方已就交货期达成一致。"
    result = verify_no_leak(text, mapping={})
    assert result.ok is True
