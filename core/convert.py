import shutil
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path

from PIL import Image

from core.ocr_vision import ocr_image_page

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
    source: str  # "text_layer" | "ocr" | "mixed"
    low_confidence_lines: list[tuple[str, float]] = field(default_factory=list)
    source_image_path: Path | None = None


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


def convert_docx(path: Path, image_output_dir: Path | None = None) -> tuple[str, list[PageText]]:
    result = subprocess.run(
        ["textutil", "-convert", "txt", "-stdout", str(path)],
        capture_output=True, text=True, check=True,
    )
    native_text = result.stdout

    image_blobs = _extract_docx_images(path)
    if not image_blobs:
        return native_text, []

    parts = [native_text.rstrip()]
    image_pages: list[PageText] = []
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        for i, blob in enumerate(image_blobs, start=1):
            tmp_img_path = tmp_dir / f"embedded_{i:03d}.png"
            try:
                with Image.open(BytesIO(blob)) as im:
                    im.convert("RGB").save(tmp_img_path, "PNG")
            except Exception:
                # Corrupt/unreadable embedded blob (e.g. an icon in an
                # unsupported format) -- skip it rather than crash the
                # whole document's conversion.
                continue

            ocr_result = ocr_image_page(tmp_img_path)

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
                )
            )
    return "\n".join(parts), image_pages


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
    result = subprocess.run(
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
            text_is_substantial = len(text_layer.strip()) >= MIN_TEXT_LAYER_CHARS
            has_image = _pdf_page_has_meaningful_image(path, page_num)

            if text_is_substantial and not has_image:
                # Genuinely text-only page: OCR would add nothing but
                # noise and cost, so skip it -- this fast path is safe
                # specifically because we've now confirmed there's no
                # embedded image being silently left behind.
                pages.append(PageText(page_num, text_layer, source="text_layer"))
                continue

            image_path = _render_pdf_page_to_png(path, page_num, tmp_dir)
            ocr_result = ocr_image_page(image_path)

            saved_image_path = None
            if image_output_dir is not None:
                image_output_dir.mkdir(parents=True, exist_ok=True)
                saved_image_path = image_output_dir / f"{path.stem}_第{page_num:04d}页_原图.png"
                shutil.copy2(image_path, saved_image_path)

            if text_is_substantial:
                # Composite page: real caption/typed text AND a
                # photographed exhibit on the same page. Union both --
                # never let one silently stand in for the other.
                combined_text = (
                    text_layer.rstrip()
                    + "\n\n[本页另含图片内容,以下为该图片的 OCR 识别结果]\n"
                    + ocr_result.text
                )
                source = "mixed"
            else:
                combined_text = ocr_result.text
                source = "ocr"

            pages.append(
                PageText(
                    page_num, combined_text, source=source,
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
