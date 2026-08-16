import pytest
from core.llm_detector import detect_llm_entities, LLMDetectionError


class FakeClient:
    """Test double standing in for the real Ollama HTTP client."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = 0

    def generate(self, prompt: str) -> str:
        self.calls += 1
        return self._responses.pop(0)


def test_valid_json_response_locates_exact_text_in_source():
    # The model is asked for exact substrings, not offsets -- LLMs are
    # unreliable at counting characters (confirmed empirically against
    # the real model: offsets were consistently off-by-a-few on Chinese
    # text). Locating the returned string deterministically in the
    # source sidesteps that failure mode entirely.
    text = "原告张三诉被告某某公司合同纠纷。"
    valid_json = '{"entities": [{"text": "张三", "type": "PERSON"}, {"text": "某某公司", "type": "ORG"}]}'
    client = FakeClient([valid_json])
    result = detect_llm_entities(text, client=client, max_retries=2)
    assert result.ok is True
    found = {(text[s.start:s.end], s.entity_type) for s in result.spans}
    assert found == {("张三", "PERSON"), ("某某公司", "ORG")}
    assert client.calls == 1


def test_malformed_json_triggers_retry_then_succeeds():
    text = "原告张三诉被告某某公司合同纠纷。"
    valid_json = '{"entities": [{"text": "张三", "type": "PERSON"}]}'
    client = FakeClient(["not json at all", valid_json])
    result = detect_llm_entities(text, client=client, max_retries=2)
    assert result.ok is True
    assert client.calls == 2


def test_exhausting_retries_fails_closed_not_silently_empty():
    text = "原告张三诉被告某某公司合同纠纷。"
    client = FakeClient(["garbage", "still garbage", "more garbage"])
    result = detect_llm_entities(text, client=client, max_retries=2)
    # must NOT report ok=True with zero spans -- that would look
    # indistinguishable from "the model genuinely found nothing".
    assert result.ok is False
    assert result.spans == []


def test_hallucinated_text_not_present_in_source_is_dropped():
    # The model claims an entity that doesn't literally appear in the
    # source text (paraphrase or outright hallucination). Never trust
    # that -- drop it rather than inventing a span for it.
    text = "原告张三诉被告某某公司合同纠纷。"
    bad_json = '{"entities": [{"text": "李四", "type": "PERSON"}]}'
    client = FakeClient([bad_json])
    result = detect_llm_entities(text, client=client, max_retries=1)
    assert result.spans == []


def test_repeated_occurrence_of_same_entity_all_located():
    text = "原告张三诉被告某某公司,张三提交了证据。"
    json_resp = '{"entities": [{"text": "张三", "type": "PERSON"}]}'
    client = FakeClient([json_resp])
    result = detect_llm_entities(text, client=client, max_retries=1)
    matched_texts = [text[s.start:s.end] for s in result.spans]
    assert matched_texts == ["张三", "张三"]


def test_duplicate_entity_entries_from_model_do_not_duplicate_spans():
    text = "原告张三诉被告某某公司合同纠纷。"
    json_resp = (
        '{"entities": ['
        '{"text": "张三", "type": "PERSON"},'
        '{"text": "张三", "type": "PERSON"}'
        "]}"
    )
    client = FakeClient([json_resp])
    result = detect_llm_entities(text, client=client, max_retries=1)
    assert len(result.spans) == 1


class RaisingClient:
    """Simulates Ollama being unreachable (connection refused, timeout)."""

    def __init__(self):
        self.calls = 0

    def generate(self, prompt: str) -> str:
        self.calls += 1
        raise ConnectionError("could not connect to Ollama")


def test_client_connection_failure_fails_closed_not_crashes():
    text = "原告张三诉被告李四"
    client = RaisingClient()
    result = detect_llm_entities(text, client=client, max_retries=2)
    assert result.ok is False
    assert result.spans == []
    assert client.calls == 2
