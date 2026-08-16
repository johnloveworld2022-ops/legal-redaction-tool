from core.lexicon_matcher import match_lexicon


def test_exact_name_from_case_list_matched():
    text = "原告王芳诉称被告未按期交付货物。"
    lexicon = ["王芳", "李四贸易有限公司"]
    spans = match_lexicon(text, lexicon)
    hit = next(s for s in spans if text[s.start:s.end] == "王芳")
    assert hit.entity_type == "PERSON"
    assert hit.confidence == "high"


def test_name_does_not_spuriously_match_inside_unrelated_longer_string():
    # "芳" and "王" both appear here but not as the contiguous name "王芳" --
    # Chinese has no word boundaries, so naive substring search on
    # single characters would over-match. Must not report a hit for "王芳"
    # when it isn't actually contiguous in the source text.
    text = "该案由王律师与芳邻物业公司共同处理。"
    lexicon = ["王芳"]
    spans = match_lexicon(text, lexicon)
    assert spans == []


def test_multiple_lexicon_entries_all_found_independently():
    text = "买方为李四贸易有限公司,卖方为王芳。"
    lexicon = ["王芳", "李四贸易有限公司"]
    spans = match_lexicon(text, lexicon)
    found_texts = {text[s.start:s.end] for s in spans}
    assert found_texts == {"王芳", "李四贸易有限公司"}


def test_empty_lexicon_returns_no_spans():
    text = "原告王芳诉称被告未按期交付货物。"
    assert match_lexicon(text, []) == []


def test_repeated_occurrence_all_matched():
    text = "王芳提交证据,王芳的代理人到场,王芳未出庭。"
    spans = match_lexicon(text, ["王芳"])
    assert len(spans) == 3
