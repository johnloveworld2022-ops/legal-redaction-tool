from core.case_workspace import find_duplicate_lexicon_entries


def test_no_duplicates_returns_empty():
    assert find_duplicate_lexicon_entries(["张三", "李四贸易有限公司", "王五"]) == []


def test_exact_duplicate_name_flagged():
    dupes = find_duplicate_lexicon_entries(["张三", "李四", "张三"])
    assert dupes == ["张三"]


def test_duplicate_with_incidental_whitespace_still_flagged():
    # lines are already stripped by load_lexicon before reaching here, but
    # guard against double-counting from leading/trailing whitespace
    # variants that slipped through
    dupes = find_duplicate_lexicon_entries(["张三", "张三 "])
    assert dupes == ["张三"]


def test_multiple_distinct_duplicates_all_reported():
    dupes = find_duplicate_lexicon_entries(["张三", "李四", "张三", "李四"])
    assert set(dupes) == {"张三", "李四"}


def test_empty_list_returns_empty():
    assert find_duplicate_lexicon_entries([]) == []
