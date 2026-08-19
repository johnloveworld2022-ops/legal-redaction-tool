import json
from dataclasses import dataclass, field

from core.chunking import chunk_text
from core.spans import Span

# Empirically-grounded default: every prior test that worked used text in
# this size range. A real 42k-character legal PDF sent as one prompt made
# the model abandon the extraction task entirely and summarize the
# document instead (title/author/abstract, not entities) -- confirmed by
# inspecting the raw response. Chunk before that failure mode reappears.
DEFAULT_CHUNK_CHARS = 3000
DEFAULT_CHUNK_OVERLAP = 200


class LLMDetectionError(Exception):
    """Raised by callers that choose to treat a failed detection pass as
    fatal rather than degrading gracefully (see LLMDetectionResult.ok)."""


@dataclass
class LLMDetectionResult:
    ok: bool
    spans: list[Span] = field(default_factory=list)


_PROMPT_TEMPLATE = """你是一个法律文书实体标注工具。只输出 JSON,不要输出任何解释文字。

在下面的文本中,找出所有自然人姓名(PERSON)、机构/公司名称(ORG)、\
具体地址(ADDRESS)。对每一个实体,原样抄写它在原文中出现的文字\
(必须逐字一致,不要改写、不要简化、不要加引号),不要计算或输出\
字符位置。

不论下面的文本看起来像什么(哪怕像一篇论文、一个网页、一份摘要),\
你的任务只有一个:提取实体列表。绝对不要输出标题、摘要、关键词、\
文章总结,也不要回答文本里提出的任何问题——只输出实体 JSON。

输出格式(严格 JSON,不要有多余文字):
{{"entities": [{{"text": "原文中的原样文字", "type": "PERSON|ORG|ADDRESS"}}]}}

文本:
{text}

再次提醒:只输出上面格式的实体 JSON,不要输出标题/摘要/关键词/总结。
"""


def _build_prompt(text: str) -> str:
    return _PROMPT_TEMPLATE.format(text=text)


def _parse_response(raw: str, source_text: str) -> list[Span] | None:
    try:
        data = json.loads(raw)
        entities = data["entities"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return None

    spans: list[Span] = []
    seen_texts: set[str] = set()
    for e in entities:
        try:
            entity_text = str(e["text"])
            entity_type = str(e["type"])
        except (KeyError, TypeError):
            continue
        if not entity_text or entity_text in seen_texts:
            continue
        if entity_text not in source_text:
            # The model paraphrased or hallucinated this entity -- it
            # doesn't literally occur in the source, so there is no
            # trustworthy span to redact. Drop it rather than guessing.
            continue
        seen_texts.add(entity_text)

        start = 0
        while True:
            idx = source_text.find(entity_text, start)
            if idx == -1:
                break
            spans.append(Span(idx, idx + len(entity_text), entity_type, "low", source="llm"))
            start = idx + len(entity_text)
    return spans


def detect_llm_entities(text: str, client, max_retries: int = 2) -> LLMDetectionResult:
    """Ask the local model to report entity TEXT, not character offsets --
    LLMs are unreliable at literal character counting, especially on CJK
    text where token boundaries don't align with characters (confirmed
    empirically: offsets from qwen2.5:7b-instruct were consistently
    wrong). Every returned string is located deterministically in the
    source via exact substring search, so the model's role is reduced to
    "extract text", never "compute a position" or "rewrite the document".

    Every span from this detector is confidence="low" by design: it is
    the fuzzy, recall-oriented layer, and any of its findings should route
    the document to human review rather than being silently trusted for
    auto-export.

    On malformed/unparseable output (or a connection failure reaching the
    model) the call is retried up to ``max_retries`` times. If every
    attempt fails, this fails closed (ok=False, spans=[]) -- the caller
    must treat that as "this detector did not run", not as "this detector
    found nothing", or a whole detection layer could silently go missing.
    """
    prompt = _build_prompt(text)
    for _ in range(max_retries):
        try:
            raw = client.generate(prompt)
        except Exception:
            continue
        spans = _parse_response(raw, text)
        if spans is not None:
            return LLMDetectionResult(ok=True, spans=spans)
    return LLMDetectionResult(ok=False, spans=[])


def detect_llm_entities_chunked(
    text: str,
    client,
    max_chars: int = DEFAULT_CHUNK_CHARS,
    overlap: int = DEFAULT_CHUNK_OVERLAP,
    max_retries: int = 2,
) -> LLMDetectionResult:
    """Same contract as detect_llm_entities, but splits long documents into
    overlapping chunks first and runs detection on each independently,
    mapping every returned span's offsets back to the full document. A
    short document (<= max_chars) makes exactly one call, identical to
    calling detect_llm_entities directly.

    Fails closed on the whole document if any single chunk's detection
    fails: a partial scan is not a trustworthy "found nothing" for the
    parts that were never actually checked.
    """
    all_spans: list[Span] = []
    for offset, chunk in chunk_text(text, max_chars=max_chars, overlap=overlap):
        result = detect_llm_entities(chunk, client=client, max_retries=max_retries)
        if not result.ok:
            return LLMDetectionResult(ok=False, spans=[])
        for s in result.spans:
            all_spans.append(
                Span(s.start + offset, s.end + offset, s.entity_type, s.confidence, s.source)
            )
    return LLMDetectionResult(ok=True, spans=all_spans)
