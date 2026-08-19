import json

import pytest

from core.llm_detector import detect_llm_entities_chunked


class SequencedClient:
    """Returns one response per call, in order -- lets a test control
    exactly what each chunk's LLM call sees."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = 0

    def generate(self, prompt: str) -> str:
        self.calls += 1
        return self._responses.pop(0)


def test_short_document_makes_a_single_call():
    text = "原告张三诉被告某某公司合同纠纷。"
    client = SequencedClient(['{"entities": [{"text": "张三", "type": "PERSON"}]}'])
    result = detect_llm_entities_chunked(text, client=client, max_chars=3000, overlap=200)
    assert result.ok is True
    assert client.calls == 1
    assert text[result.spans[0].start:result.spans[0].end] == "张三"


class EchoClient:
    """Finds any of a fixed set of known names literally present in
    whatever chunk it's asked about, and reports just those -- a stand-in
    for a real model's per-chunk behavior without hardcoding call count,
    which depends on exact chunk-boundary arithmetic this test shouldn't
    need to know about.
    """

    def __init__(self, known_names_and_types: dict[str, str]):
        self._known = known_names_and_types
        self.calls = 0

    def generate(self, prompt: str) -> str:
        self.calls += 1
        entities = [
            {"text": name, "type": etype}
            for name, etype in self._known.items()
            if name in prompt
        ]
        return json.dumps({"entities": entities}, ensure_ascii=False)


def test_long_document_finds_names_in_both_halves_with_correct_global_offsets():
    page1 = "原告张三诉被告某某公司。" + "填充文字。" * 100
    page2 = "证人王五出庭作证。" + "填充文字。" * 100
    text = page1 + "\n\n" + page2

    client = EchoClient({"张三": "PERSON", "王五": "PERSON"})
    result = detect_llm_entities_chunked(
        text, client=client, max_chars=len(page1) + 5, overlap=20
    )
    assert result.ok is True
    assert client.calls > 1  # confirms this really did split into multiple calls
    found = {text[s.start:s.end] for s in result.spans}
    assert found == {"张三", "王五"}


def test_any_chunk_failing_fails_the_whole_scan_closed():
    page1 = "原告张三。" + "填充文字。" * 100
    page2 = "被告李四。" + "填充文字。" * 100
    text = page1 + "\n\n" + page2

    responses = ["garbage", "still garbage", "more garbage", '{"entities": []}']
    client = SequencedClient(responses)
    result = detect_llm_entities_chunked(
        text, client=client, max_chars=len(page1) + 5, overlap=20, max_retries=3
    )
    assert result.ok is False
    assert result.spans == []


def test_offsets_in_second_chunk_map_back_to_original_document():
    prefix = "填充文字。" * 200
    target = "被告陈晓身份证复印件如下。"
    text = prefix + target

    # first call covers the prefix chunk and finds nothing; second call
    # covers the tail chunk containing the real name
    client = SequencedClient([
        '{"entities": []}',
        '{"entities": [{"text": "陈晓", "type": "PERSON"}]}',
    ])
    result = detect_llm_entities_chunked(
        text, client=client, max_chars=len(prefix) - 50, overlap=100
    )
    assert result.ok is True
    assert len(result.spans) == 1
    span = result.spans[0]
    assert text[span.start:span.end] == "陈晓"
