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
