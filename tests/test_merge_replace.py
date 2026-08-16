from core.spans import Span
from core.merge_replace import merge_spans, apply_replacements


def test_overlapping_spans_from_two_detectors_merge_without_double_replace():
    text = "被告张三居住于北京市海淀区。"
    # regex-ish detector catches "张三", llm-ish detector catches "张三居住"
    # (overlapping, sloppier boundary) -- merge must pick one, not both.
    span_a = Span(start=2, end=4, entity_type="PERSON", confidence="high", source="lexicon")
    span_b = Span(start=2, end=6, entity_type="PERSON", confidence="low", source="llm")
    merged = merge_spans([span_a, span_b])
    assert len(merged) == 1
    # narrower, higher-confidence span wins over the sloppier overlapping one
    assert (merged[0].start, merged[0].end) == (2, 4)


def test_same_real_string_gets_same_token_every_occurrence():
    text = "原告李四诉称,被告未履行合同。李四提交了证据。"
    spans = [
        Span(start=2, end=4, entity_type="PERSON", confidence="high", source="lexicon"),
        Span(start=15, end=17, entity_type="PERSON", confidence="high", source="lexicon"),
    ]
    result = apply_replacements(text, merge_spans(spans))
    assert len(result.mapping) == 1, "same real string must map to exactly one token"
    token = next(iter(result.mapping.keys()))
    assert result.text.count(token) == 2
    assert "李四" not in result.text


def test_two_different_names_get_two_different_sequential_tokens():
    text = "原告李四与被告王五签订协议。"
    spans = [
        Span(start=2, end=4, entity_type="PERSON", confidence="high", source="lexicon"),
        Span(start=7, end=9, entity_type="PERSON", confidence="high", source="lexicon"),
    ]
    result = apply_replacements(text, merge_spans(spans))
    assert len(result.mapping) == 2
    assert len(set(result.mapping.values())) == 2


def test_non_replaced_regions_are_byte_identical_to_source():
    text = "本案系买卖合同纠纷,原告李四主张被告支付货款人民币50000元。"
    spans = [Span(start=11, end=13, entity_type="PERSON", confidence="high", source="lexicon")]
    result = apply_replacements(text, merge_spans(spans))
    prefix = text[:11]
    suffix = text[13:]
    assert result.text.startswith(prefix)
    assert result.text.endswith(suffix)


def test_existing_mapping_from_a_prior_document_is_reused_across_documents():
    # Case-level consistency: the same real name must map to the same
    # token across every document in a case, not just within one call.
    doc1 = "原告张三诉称合同违约。"
    spans1 = [Span(start=2, end=4, entity_type="PERSON", confidence="high", source="lexicon")]
    result1 = apply_replacements(doc1, merge_spans(spans1))
    token_for_zhang_san = next(iter(result1.mapping.keys()))

    doc2 = "被告未回应张三的催告函,另有王五出庭作证。"
    spans2 = [
        Span(start=5, end=7, entity_type="PERSON", confidence="high", source="lexicon"),
        Span(start=14, end=16, entity_type="PERSON", confidence="high", source="lexicon"),
    ]
    result2 = apply_replacements(doc2, merge_spans(spans2), existing_mapping=result1.mapping)

    assert token_for_zhang_san in result2.text
    assert result2.mapping[token_for_zhang_san] == "张三"
    # a genuinely new name still gets a fresh, distinct token
    assert len(result2.mapping) == 2
    new_tokens = set(result2.mapping.keys()) - {token_for_zhang_san}
    assert len(new_tokens) == 1
    assert result2.mapping[next(iter(new_tokens))] == "王五"


def test_adjacent_non_overlapping_spans_both_replaced_independently():
    text = "甲方张三乙方李四"
    spans = [
        Span(start=2, end=4, entity_type="PERSON", confidence="high", source="lexicon"),
        Span(start=6, end=8, entity_type="PERSON", confidence="high", source="lexicon"),
    ]
    result = apply_replacements(text, merge_spans(spans))
    assert len(result.mapping) == 2
    assert "张三" not in result.text
    assert "李四" not in result.text
