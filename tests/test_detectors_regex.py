import pytest
from core.detectors_regex import detect_structured_pii


def _span_texts(spans, text):
    return [text[s.start:s.end] for s in spans]


def test_valid_id_card_detected_high_confidence():
    text = "身份证号:110101199003072316,请核实。"
    spans = detect_structured_pii(text)
    assert "110101199003072316" in _span_texts(spans, text)
    hit = next(s for s in spans if text[s.start:s.end] == "110101199003072316")
    assert hit.entity_type == "ID_CARD"
    assert hit.confidence == "high"


def test_id_card_bad_checksum_still_flagged_low_confidence():
    # last digit corrupted by OCR (valid checksum would be '6', this is '5')
    text = "身份证号:110101199003072315,请核实。"
    spans = detect_structured_pii(text)
    hit = next(
        (s for s in spans if text[s.start:s.end] == "110101199003072315"), None
    )
    assert hit is not None, "checksum-failing near-ID must still be flagged, not dropped"
    assert hit.confidence == "low"
    assert hit.entity_type == "ID_CARD"


def test_phone_number_offsets_correct_mid_sentence():
    text = "如有疑问请拨打13812345678进行咨询。"
    spans = detect_structured_pii(text)
    hit = next(s for s in spans if s.entity_type == "PHONE")
    assert text[hit.start:hit.end] == "13812345678"


def test_bank_card_detected():
    text = "汇款至6222021234567890123账户。"
    spans = detect_structured_pii(text)
    assert any(s.entity_type == "BANK_CARD" for s in spans)


def test_email_detected():
    text = "联系邮箱 zhangsan@example.com 谢谢。"
    spans = detect_structured_pii(text)
    hit = next(s for s in spans if s.entity_type == "EMAIL")
    assert text[hit.start:hit.end] == "zhangsan@example.com"


def test_ambiguous_numeric_id_like_case_number_flagged_low_confidence():
    # An 18-digit run that is plausibly a case/document number, not a
    # real person ID (checksum will not validate). Must still surface
    # as a low-confidence candidate for human review rather than being
    # silently ignored -- false negatives are worse than an extra
    # reviewed candidate.
    text = "案号:(2024)京0105民初123456789012345678号"
    spans = detect_structured_pii(text)
    hit = next(
        (s for s in spans if text[s.start:s.end] == "123456789012345678"), None
    )
    assert hit is not None
    assert hit.entity_type == "ID_CARD"
    assert hit.confidence == "low"


def test_no_false_high_confidence_on_short_numbers():
    text = "请于5日内提交材料,共3份。"
    spans = detect_structured_pii(text)
    assert spans == []


def test_birthdate_with_出生_suffix_detected():
    text = "原告张三,男,1990年3月12日出生,住北京市朝阳区。"
    spans = detect_structured_pii(text)
    hit = next((s for s in spans if s.entity_type == "BIRTHDATE"), None)
    assert hit is not None
    assert text[hit.start:hit.end] == "1990年3月12日出生"
    assert hit.confidence == "high"


def test_ordinary_date_without_出生_suffix_not_flagged_as_birthdate():
    # A filing/contract/hearing date is legally meaningful content, not a
    # birthdate -- must not be swept up by the birthdate pattern just for
    # sharing the same YYYY年M月D日 shape.
    text = "本案于2024年5月10日立案受理。"
    spans = detect_structured_pii(text)
    assert not any(s.entity_type == "BIRTHDATE" for s in spans)


def test_standard_case_number_detected():
    text = "案号:(2024)京0105民初12345号,原告诉称..."
    spans = detect_structured_pii(text)
    hit = next((s for s in spans if s.entity_type == "CASE_NUMBER"), None)
    assert hit is not None
    assert text[hit.start:hit.end] == "(2024)京0105民初12345号"
    assert hit.confidence == "high"


def test_supreme_court_case_number_without_district_code_detected():
    text = "本案已被(2023)最高法民申678号裁定驳回。"
    spans = detect_structured_pii(text)
    hit = next((s for s in spans if s.entity_type == "CASE_NUMBER"), None)
    assert hit is not None
    assert text[hit.start:hit.end] == "(2023)最高法民申678号"
