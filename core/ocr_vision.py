from dataclasses import dataclass, field
from pathlib import Path

from ocrmac import ocrmac

# Below this Vision-reported confidence (0-1), a recognized line is treated
# as suspect and surfaced for the lawyer to check against the saved page
# image herself, rather than trusted silently. Calibrated empirically: a
# clean synthetic scan reads at ~1.0; a deliberately degraded (blurred +
# noisy) scan of the same text read at ~0.30 and silently misread digits
# inside an ID number while still looking plausible.
OCR_CONFIDENCE_THRESHOLD = 0.5


@dataclass
class OcrLine:
    text: str
    confidence: float


@dataclass
class OcrPageResult:
    text: str
    lines: list[OcrLine] = field(default_factory=list)

    @property
    def low_confidence_lines(self) -> list[tuple[str, float]]:
        return [
            (line.text, line.confidence)
            for line in self.lines
            if line.confidence < OCR_CONFIDENCE_THRESHOLD
        ]


def ocr_image_page(image_path: Path) -> OcrPageResult:
    """Run macOS Vision OCR (on-device, fully offline) on a single page
    image and return its text plus per-line confidence, in approximate
    reading order.

    Vision reports bounding boxes normalized 0-1 with the origin at the
    bottom-left and y increasing upward. Sorting by descending y, then
    ascending x, approximates top-to-bottom / left-to-right reading order
    for ordinary prose. Multi-column layouts and dense tables are a known
    weak spot for this ordering heuristic.
    """
    annotations = ocrmac.OCR(
        str(image_path),
        language_preference=["zh-Hans", "en-US"],
        recognition_level="accurate",
    ).recognize()
    ordered = sorted(annotations, key=lambda a: (-round(a[2][1], 3), a[2][0]))
    lines = [OcrLine(text=text, confidence=confidence) for text, confidence, _bbox in ordered]
    return OcrPageResult(text="\n".join(l.text for l in lines), lines=lines)


def ocr_image_text(image_path: Path) -> str:
    """Convenience wrapper for callers that only need the plain text."""
    return ocr_image_page(image_path).text
