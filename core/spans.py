from dataclasses import dataclass


@dataclass(frozen=True)
class Span:
    """A detected PII candidate as a character range into the source text.

    Detectors only ever report spans -- they never rewrite text themselves.
    That separation is what keeps the redacted output byte-identical to the
    source outside the replaced ranges, so a reviewer can trust it wasn't
    silently altered.
    """

    start: int
    end: int
    entity_type: str
    confidence: str  # "high" | "low"
    source: str  # which detector produced this: "regex" | "lexicon" | "llm"
