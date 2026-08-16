import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from core.ocr_vision import ocr_image_page

# Below this many non-whitespace characters, a PDF page's embedded text
# layer is treated as unreliable (blank page, or a scanned image page
# sitting inside an otherwise text-layer PDF) and OCR'd instead of trusted.
MIN_TEXT_LAYER_CHARS = 20


@dataclass
class PageText:
    page_number: int
    text: str
    source: str  # "text_layer" | "ocr"
    low_confidence_lines: list[tuple[str, float]] = field(default_factory=list)
    source_image_path: Path | None = None


def convert_docx(path: Path) -> str:
    result = subprocess.run(
        ["textutil", "-convert", "txt", "-stdout", str(path)],
        capture_output=True, text=True, check=True,
    )
    return result.stdout


def _pdf_page_count(path: Path) -> int:
    result = subprocess.run(
        ["pdfinfo", str(path)], capture_output=True, text=True, check=True
    )
    for line in result.stdout.splitlines():
        if line.startswith("Pages:"):
            return int(line.split(":", 1)[1].strip())
    raise RuntimeError(f"无法读取 PDF 页数: {path}")


def _extract_pdf_page_text_layer(path: Path, page_num: int) -> str:
    result = subprocess.run(
        ["pdftotext", "-layout", "-f", str(page_num), "-l", str(page_num), str(path), "-"],
        capture_output=True, text=True, check=True,
    )
    return result.stdout


def _render_pdf_page_to_png(path: Path, page_num: int, out_dir: Path) -> Path:
    prefix = out_dir / f"page_{page_num:04d}"
    subprocess.run(
        ["pdftoppm", "-png", "-r", "300", "-f", str(page_num), "-l", str(page_num),
         str(path), str(prefix)],
        check=True, capture_output=True,
    )
    candidates = sorted(out_dir.glob(f"page_{page_num:04d}*.png"))
    if not candidates:
        raise RuntimeError(f"第 {page_num} 页渲染为图片失败: {path}")
    return candidates[0]


def convert_pdf(path: Path, image_output_dir: Path | None = None) -> list[PageText]:
    """Convert a PDF to per-page text. Each page is judged independently --
    a page whose text layer is too short falls back to on-device OCR --
    rather than classifying the whole file as "has text" or "is scanned",
    which breaks on the common case of a mostly-text PDF with one scanned
    exhibit page glued in.

    When ``image_output_dir`` is given, every OCR'd page's rendered image
    is saved there (instead of being discarded with the temp directory) so
    a human can open it side-by-side with the extracted text and catch a
    misread character before it silently propagates into detection.
    """
    page_count = _pdf_page_count(path)
    pages: list[PageText] = []
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        for page_num in range(1, page_count + 1):
            text_layer = _extract_pdf_page_text_layer(path, page_num)
            if len(text_layer.strip()) >= MIN_TEXT_LAYER_CHARS:
                pages.append(PageText(page_num, text_layer, source="text_layer"))
                continue
            image_path = _render_pdf_page_to_png(path, page_num, tmp_dir)
            ocr_result = ocr_image_page(image_path)

            saved_image_path = None
            if image_output_dir is not None:
                image_output_dir.mkdir(parents=True, exist_ok=True)
                saved_image_path = image_output_dir / f"{path.stem}_第{page_num:04d}页_原图.png"
                shutil.copy2(image_path, saved_image_path)

            pages.append(
                PageText(
                    page_num, ocr_result.text, source="ocr",
                    low_confidence_lines=ocr_result.low_confidence_lines,
                    source_image_path=saved_image_path,
                )
            )
    return pages


def pages_to_text(pages: list[PageText]) -> str:
    """Join per-page text with source markers, so OCR provenance survives
    into the later review report (a reviewer should trust an OCR'd page
    less than a native text-layer page).
    """
    parts = []
    for p in pages:
        tag = "(OCR)" if p.source == "ocr" else ""
        parts.append(f"\n\n=== 第 {p.page_number} 页{tag} ===\n{p.text}")
    return "".join(parts)


def convert_to_text(path: Path) -> str:
    """Normalize any supported input file to one plain-text string."""
    suffix = path.suffix.lower()
    if suffix == ".docx":
        return convert_docx(path)
    if suffix == ".pdf":
        return pages_to_text(convert_pdf(path))
    raise ValueError(f"不支持的文件类型: {suffix}(目前支持 .docx 和 .pdf)")
