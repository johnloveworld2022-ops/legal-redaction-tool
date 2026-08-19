from core.chunking import chunk_text


def test_short_text_returns_single_chunk_at_offset_zero():
    text = "原告张三诉被告李四合同纠纷。"
    chunks = chunk_text(text, max_chars=3000, overlap=200)
    assert chunks == [(0, text)]


def test_long_text_split_into_multiple_chunks():
    text = "段落一。" * 500  # well over max_chars
    chunks = chunk_text(text, max_chars=1000, overlap=100)
    assert len(chunks) > 1
    for offset, chunk in chunks:
        assert text[offset:offset + len(chunk)] == chunk


def test_chunks_cover_the_entire_text_with_no_gaps():
    text = "甲" * 5000
    chunks = chunk_text(text, max_chars=1200, overlap=150)
    covered = set()
    for offset, chunk in chunks:
        covered.update(range(offset, offset + len(chunk)))
    assert covered == set(range(len(text)))


def test_consecutive_chunks_overlap():
    text = "甲" * 5000
    chunks = chunk_text(text, max_chars=1200, overlap=150)
    for i in range(len(chunks) - 1):
        end_of_this = chunks[i][0] + len(chunks[i][1])
        start_of_next = chunks[i + 1][0]
        assert start_of_next < end_of_this  # they overlap, not just touch


def test_prefers_paragraph_boundary_when_available():
    para_a = "第一段内容。" * 50
    para_b = "第二段内容。" * 50
    text = para_a + "\n\n" + para_b
    chunks = chunk_text(text, max_chars=len(para_a) + 10, overlap=50)
    # the first chunk should end right at (or very near) the paragraph
    # break rather than mid-way through para_b
    first_chunk_end = chunks[0][0] + len(chunks[0][1])
    assert first_chunk_end <= len(para_a) + 2


def test_never_infinite_loops_on_pathological_input():
    # a single "paragraph" far longer than max_chars, no break points at all
    text = "甲" * 10000
    chunks = chunk_text(text, max_chars=500, overlap=490)
    assert len(chunks) > 1
    assert len(chunks) < 1000  # sane upper bound -- would blow up if stuck
