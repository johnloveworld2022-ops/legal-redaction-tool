import shutil
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path

from PIL import Image

from core.ocr_vision import OcrTimeoutError, ocr_image_page
from core.subprocess_utils import SubprocessTimeoutError, run_subprocess
from core.table_detector import detect_table_layout

_DOCX_WORD_NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}

_DOCX_IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".gif", ".heic")

# Below this many non-whitespace characters, a PDF page's embedded text
# layer is treated as unreliable (blank page, or a scanned image page
# sitting inside an otherwise text-layer PDF) and OCR'd instead of trusted.
MIN_TEXT_LAYER_CHARS = 20


# A page carrying an embedded image at least this many pixels (width *
# height) is treated as possibly containing photographed document content
# worth OCR'ing, as opposed to a small decorative logo/icon/letterhead.
MIN_MEANINGFUL_IMAGE_AREA_PX = 40_000  # e.g. 200x200


@dataclass
class PageText:
    page_number: int
    text: str
    source: str  # "text_layer" | "ocr" | "mixed" | "failed"
    low_confidence_lines: list[tuple[str, float]] = field(default_factory=list)
    source_image_path: Path | None = None
    failure_reason: str | None = None
    possible_table: bool = False


def _extract_docx_images(path: Path) -> list[bytes]:
    """docx is a zip archive; embedded pictures live under word/media/.
    textutil's plain-text conversion only reads text runs -- it never
    looks at these -- so a photographed page inserted directly into Word
    was previously invisible to the whole pipeline: not OCR'd, not
    flagged, nothing.
    """
    images: list[bytes] = []
    with zipfile.ZipFile(path) as zf:
        for name in sorted(zf.namelist()):
            if name.startswith("word/media/") and name.lower().endswith(_DOCX_IMAGE_EXTENSIONS):
                images.append(zf.read(name))
    return images


def _docx_has_native_table(path: Path) -> bool:
    """Detects a real Word table (<w:tbl> in word/document.xml) via the
    document's own structure, not text heuristics -- OCR/text-run
    extraction routinely loses the row/column structure that would let a
    text-pattern guess work reliably, and the native XML always has it.
    A table found here forces human review: a name/ID-number pair swapped
    between adjacent table rows would pass every per-token confidence
    check while being wrong about who the number belongs to.
    """
    with zipfile.ZipFile(path) as zf:
        if "word/document.xml" not in zf.namelist():
            return False
        xml_bytes = zf.read("word/document.xml")
    root = ET.fromstring(xml_bytes)
    return root.find(".//w:tbl", _DOCX_WORD_NS) is not None


def convert_docx(
    path: Path, image_output_dir: Path | None = None
) -> tuple[str, list[PageText], bool]:
    result = run_subprocess(
        ["textutil", "-convert", "txt", "-stdout", str(path)],
        capture_output=True, text=True, check=True,
    )
    native_text = result.stdout
    has_native_table = _docx_has_native_table(path)

    image_blobs = _extract_docx_images(path)
    if not image_blobs:
        return native_text, [], has_native_table

    parts = [native_text.rstrip()]
    image_pages: list[PageText] = []
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        for i, blob in enumerate(image_blobs, start=1):
            tmp_img_path = tmp_dir / f"embedded_{i:03d}.png"
            try:
                with Image.open(BytesIO(blob)) as im:
                    im.convert("RGB").save(tmp_img_path, "PNG")
            except Exception as e:
                # Corrupt/unreadable embedded blob (e.g. an icon in an
                # unsupported format). Previously this was silently
                # skipped with no record at all -- indistinguishable from
                # "there was no such image", which is exactly the class of
                # silent-loss bug fixed elsewhere in this file. Record a
                # failed ledger entry instead so it blocks auto-export.
                image_pages.append(
                    PageText(
                        page_number=i, text="", source="failed",
                        failure_reason=f"第 {i} 张插入图片无法读取: {e}",
                    )
                )
                continue

            try:
                ocr_result = ocr_image_page(tmp_img_path)
            except Exception as e:
                image_pages.append(
                    PageText(
                        page_number=i, text="", source="failed",
                        failure_reason=f"第 {i} 张插入图片 OCR 识别失败: {e}",
                    )
                )
                continue

            saved_image_path = None
            if image_output_dir is not None:
                image_output_dir.mkdir(parents=True, exist_ok=True)
                saved_image_path = image_output_dir / f"{path.stem}_插图{i:03d}_原图.png"
                shutil.copy2(tmp_img_path, saved_image_path)

            parts.append(f"\n\n[文档中第 {i} 张插入图片的 OCR 识别结果]\n{ocr_result.text}")
            image_pages.append(
                PageText(
                    page_number=i, text=ocr_result.text, source="ocr",
                    low_confidence_lines=ocr_result.low_confidence_lines,
                    source_image_path=saved_image_path,
                    possible_table=ocr_result.possible_table,
                )
            )
    has_table = has_native_table or any(p.possible_table for p in image_pages)
    return "\n".join(parts), image_pages, has_table


def _pdf_page_count(path: Path) -> int:
    result = run_subprocess(
        ["pdfinfo", str(path)], capture_output=True, text=True, check=True
    )
    for line in result.stdout.splitlines():
        if line.startswith("Pages:"):
            return int(line.split(":", 1)[1].strip())
    raise RuntimeError(f"无法读取 PDF 页数: {path}")


def _extract_pdf_page_text_layer(path: Path, page_num: int) -> str:
    result = run_subprocess(
        ["pdftotext", "-layout", "-f", str(page_num), "-l", str(page_num), str(path), "-"],
        capture_output=True, text=True, check=True,
    )
    return result.stdout


def _pdf_page_text_layer_boxes(
    path: Path, page_num: int
) -> list[tuple[float, float, float, float]]:
    """Per-line normalized bounding boxes for a PDF page's native text
    layer, via poppler's ``pdftotext -tsv`` (word/line-level coordinates
    in points). Used to feed detect_table_layout on text-only pages,
    since those never go through OCR and so never get a bbox any other
    way. Level 5 rows are actual text lines; level 1 is the page-size
    marker row.
    """
    result = run_subprocess(
        ["pdftotext", "-tsv", "-f", str(page_num), "-l", str(page_num), str(path), "-"],
        capture_output=True, text=True, check=True,
    )
    page_w = page_h = None
    boxes: list[tuple[float, float, float, float]] = []
    for line in result.stdout.splitlines()[1:]:  # skip TSV header
        cols = line.split("\t")
        if len(cols) < 11:
            continue
        level = cols[0]
        try:
            left, top, width, height = (float(cols[6]), float(cols[7]), float(cols[8]), float(cols[9]))
        except ValueError:
            continue
        if level == "1":
            page_w, page_h = width, height
        elif level == "5" and page_w and page_h:
            boxes.append((left / page_w, top / page_h, width / page_w, height / page_h))
    return boxes


def _pdf_page_has_meaningful_image(path: Path, page_num: int) -> bool:
    """Detect whether a page carries an embedded image large enough to
    plausibly be photographed document content, via poppler's
    ``pdfimages -list``. Any such page must be OCR'd regardless of how
    much native text it also has -- otherwise a short caption's text layer
    would satisfy MIN_TEXT_LAYER_CHARS and silently hide a photographed
    exhibit on the same page from OCR entirely (a real bug found via
    external review, not a hypothetical: a composite page with a >=20
    char caption plus an inserted exhibit photo previously lost the photo
    completely, with no error and no low-confidence signal to catch it).
    """
    result = run_subprocess(
        ["pdfimages", "-list", "-f", str(page_num), "-l", str(page_num), str(path)],
        capture_output=True, text=True, check=True,
    )
    for line in result.stdout.splitlines():
        parts = line.split()
        if not parts or not parts[0].isdigit():
            continue  # header / separator line
        try:
            width, height = int(parts[3]), int(parts[4])
        except (IndexError, ValueError):
            continue
        if width * height >= MIN_MEANINGFUL_IMAGE_AREA_PX:
            return True
    return False


def _render_pdf_page_to_png(path: Path, page_num: int, out_dir: Path) -> Path:
    prefix = out_dir / f"page_{page_num:04d}"
    run_subprocess(
        ["pdftoppm", "-png", "-r", "300", "-f", str(page_num), "-l", str(page_num),
         str(path), str(prefix)],
        check=True, capture_output=True,
        timeout=120,  # a page rendering at 300dpi is slower than text extraction
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
            try:
                pages.append(_convert_one_pdf_page(path, page_num, tmp_dir, image_output_dir))
            except Exception as e:
                # One page's failure (a corrupted page, a rendering
                # timeout) must not silently take the whole document's
                # remaining pages down with it, and must not silently
                # drop that one page either -- record it as failed so the
                # per-document processing ledger blocks auto-export until
                # a human looks at it.
                pages.append(
                    PageText(
                        page_num, "", source="failed",
                        failure_reason=f"第 {page_num} 页处理失败: {e}",
                    )
                )
    return pages


def _convert_one_pdf_page(
    path: Path, page_num: int, tmp_dir: Path, image_output_dir: Path | None
) -> PageText:
    text_layer = _extract_pdf_page_text_layer(path, page_num)
    text_is_substantial = len(text_layer.strip()) >= MIN_TEXT_LAYER_CHARS
    has_image = _pdf_page_has_meaningful_image(path, page_num)

    if text_is_substantial and not has_image:
        # Genuinely text-only page: OCR would add nothing but noise and
        # cost, so skip it -- this fast path is safe specifically because
        # we've now confirmed there's no embedded image being silently
        # left behind. Still check for table/form layout from the text
        # layer's own coordinates, since this page never goes through OCR
        # and so never gets a bbox any other way.
        boxes = _pdf_page_text_layer_boxes(path, page_num)
        return PageText(
            page_num, text_layer, source="text_layer",
            possible_table=detect_table_layout(boxes),
        )

    image_path = _render_pdf_page_to_png(path, page_num, tmp_dir)
    ocr_result = ocr_image_page(image_path)

    saved_image_path = None
    if image_output_dir is not None:
        image_output_dir.mkdir(parents=True, exist_ok=True)
        saved_image_path = image_output_dir / f"{path.stem}_第{page_num:04d}页_原图.png"
        shutil.copy2(image_path, saved_image_path)

    if text_is_substantial:
        # Composite page: real caption/typed text AND a photographed
        # exhibit on the same page. Union both -- never let one silently
        # stand in for the other.
        combined_text = (
            text_layer.rstrip()
            + "\n\n[本页另含图片内容,以下为该图片的 OCR 识别结果]\n"
            + ocr_result.text
        )
        source = "mixed"
    else:
        combined_text = ocr_result.text
        source = "ocr"

    return PageText(
        page_num, combined_text, source=source,
        low_confidence_lines=ocr_result.low_confidence_lines,
        source_image_path=saved_image_path,
        possible_table=ocr_result.possible_table,
    )


def pages_to_text(pages: list[PageText]) -> str:
    """Join per-page text with source markers, so OCR provenance survives
    into the later review report (a reviewer should trust an OCR'd page
    less than a native text-layer page).
    """
    tags = {"ocr": "(OCR)", "mixed": "(含OCR)"}
    parts = []
    for p in pages:
        tag = tags.get(p.source, "")
        parts.append(f"\n\n=== 第 {p.page_number} 页{tag} ===\n{p.text}")
    return "".join(parts)


def convert_to_text(path: Path) -> str:
    """Normalize any supported input file to one plain-text string."""
    suffix = path.suffix.lower()
    if suffix == ".docx":
        return convert_docx(path)[0]
    if suffix == ".pdf":
        return pages_to_text(convert_pdf(path))
    raise ValueError(f"不支持的文件类型: {suffix}(目前支持 .docx 和 .pdf)")
