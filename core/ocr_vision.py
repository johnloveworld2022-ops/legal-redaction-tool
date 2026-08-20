import concurrent.futures
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, TypeVar

from ocrmac import ocrmac

from core.table_detector import detect_table_layout

# Below this Vision-reported confidence (0-1), a recognized line is treated
# as suspect and surfaced for the lawyer to check against the saved page
# image herself, rather than trusted silently. Calibrated empirically: a
# clean synthetic scan reads at ~1.0; a deliberately degraded (blurred +
# noisy) scan of the same text read at ~0.30 and silently misread digits
# inside an ID number while still looking plausible.
OCR_CONFIDENCE_THRESHOLD = 0.5

OCR_TIMEOUT_SECONDS = 60

_T = TypeVar("_T")


class OcrTimeoutError(RuntimeError):
    def __init__(self, timeout: float):
        self.timeout = timeout
        super().__init__(f"OCR 识别超时({timeout}秒)")


def _run_with_soft_timeout(fn: Callable[[], _T], timeout: float) -> _T:
    """Runs fn() in a background thread and raises OcrTimeoutError if it
    doesn't finish within `timeout`. This is a SOFT timeout: it releases
    the caller so the per-page processing ledger can mark the page failed
    and move on, but it does not (cannot, from pure Python) forcibly kill
    a blocked native call inside macOS Vision -- an actually-hung call
    leaves its worker thread running in the background. A fresh
    single-use executor is used per call (never shared) specifically so a
    leaked thread from one pathological page cannot exhaust a shared pool
    and stall every subsequent page too.
    """
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    future = executor.submit(fn)
    try:
        return future.result(timeout=timeout)
    except concurrent.futures.TimeoutError:
        raise OcrTimeoutError(timeout)
    finally:
        executor.shutdown(wait=False)


@dataclass
class OcrLine:
    text: str
    confidence: float
    bbox: tuple[float, float, float, float]  # (left, top, width, height), normalized 0-1


@dataclass
class OcrPageResult:
    text: str
    lines: list[OcrLine] = field(default_factory=list)
    possible_table: bool = False

    @property
    def low_confidence_lines(self) -> list[tuple[str, float]]:
        return [
            (line.text, line.confidence)
            for line in self.lines
            if line.confidence < OCR_CONFIDENCE_THRESHOLD
        ]


def _run_vision_ocr(image_path: Path):
    return ocrmac.OCR(
        str(image_path),
        language_preference=["zh-Hans", "en-US"],
        recognition_level="accurate",
    ).recognize()


def ocr_image_page(image_path: Path, timeout: float = OCR_TIMEOUT_SECONDS) -> OcrPageResult:
    """Run macOS Vision OCR (on-device, fully offline) on a single page
    image and return its text plus per-line confidence, in approximate
    reading order.

    Vision reports bounding boxes normalized 0-1 with the origin at the
    bottom-left and y increasing upward. Sorting by descending y, then
    ascending x, approximates top-to-bottom / left-to-right reading order
    for ordinary prose. Multi-column layouts and dense tables are a known
    weak spot for this ordering heuristic -- possible_table flags that
    case via geometric column detection so it routes to forced review
    instead of silently reading in the wrong order.
    """
    annotations = _run_with_soft_timeout(lambda: _run_vision_ocr(image_path), timeout=timeout)
    ordered = sorted(annotations, key=lambda a: (-round(a[2][1], 3), a[2][0]))
    lines = [
        OcrLine(text=text, confidence=confidence, bbox=tuple(bbox))
        for text, confidence, bbox in ordered
    ]
    possible_table = detect_table_layout([l.bbox for l in lines])
    return OcrPageResult(
        text="\n".join(l.text for l in lines), lines=lines, possible_table=possible_table
    )


def ocr_image_text(image_path: Path) -> str:
    """Convenience wrapper for callers that only need the plain text."""
    return ocr_image_page(image_path).text
