import random
import subprocess

import pytest
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from core.convert import convert_docx, convert_pdf, convert_to_text

CHINESE_FONT = "/System/Library/Fonts/STHeiti Light.ttc"
SENTENCE = "原告张三身份证号110101199003072316"


@pytest.fixture
def docx_file(tmp_path):
    src_txt = tmp_path / "src.txt"
    src_txt.write_text(SENTENCE, encoding="utf-8")
    out_docx = tmp_path / "case.docx"
    subprocess.run(
        ["textutil", "-convert", "docx", "-output", str(out_docx), str(src_txt)],
        check=True, capture_output=True,
    )
    return out_docx


@pytest.fixture
def text_layer_pdf(tmp_path):
    # cupsfilter renders a plain-text file to a real, selectable-text PDF
    # via the system print filter -- a proper text-layer PDF, not an image.
    src_txt = tmp_path / "src.txt"
    src_txt.write_text(SENTENCE, encoding="utf-8")
    out_pdf = tmp_path / "case.pdf"
    result = subprocess.run(
        ["cupsfilter", str(src_txt)], capture_output=True, check=True
    )
    out_pdf.write_bytes(result.stdout)
    return out_pdf


@pytest.fixture
def scanned_image_pdf(tmp_path):
    img = Image.new("RGB", (900, 150), "white")
    d = ImageDraw.Draw(img)
    font = ImageFont.truetype(CHINESE_FONT, 40)
    d.text((20, 40), SENTENCE, font=font, fill="black")
    out_pdf = tmp_path / "scanned.pdf"
    img.save(out_pdf, "PDF")
    return out_pdf


@pytest.fixture
def degraded_scanned_pdf(tmp_path):
    random.seed(42)
    img = Image.new("RGB", (900, 150), "white")
    d = ImageDraw.Draw(img)
    font = ImageFont.truetype(CHINESE_FONT, 40)
    d.text((20, 40), SENTENCE, font=font, fill=(135, 135, 135))
    img = img.filter(ImageFilter.GaussianBlur(2.5))
    px = img.load()
    w, h = img.size
    for x in range(w):
        for y in range(h):
            r, g, b = px[x, y]
            n = random.randint(-35, 35)
            px[x, y] = (
                max(0, min(255, r + n)), max(0, min(255, g + n)), max(0, min(255, b + n))
            )
    out_pdf = tmp_path / "degraded.pdf"
    img.save(out_pdf, "PDF")
    return out_pdf


def test_docx_extracts_expected_text(docx_file):
    text = convert_docx(docx_file)
    assert SENTENCE in text


def test_text_layer_pdf_uses_text_layer_not_ocr(text_layer_pdf):
    pages = convert_pdf(text_layer_pdf)
    assert len(pages) == 1
    assert pages[0].source == "text_layer"
    assert SENTENCE in pages[0].text


def test_scanned_image_pdf_falls_back_to_ocr(scanned_image_pdf):
    pages = convert_pdf(scanned_image_pdf)
    assert len(pages) == 1
    assert pages[0].source == "ocr"
    assert "张三" in pages[0].text
    assert "110101199003072316" in pages[0].text


def test_convert_to_text_marks_ocr_pages(scanned_image_pdf):
    text = convert_to_text(scanned_image_pdf)
    assert "(OCR)" in text
    assert "张三" in text


def test_unsupported_extension_raises(tmp_path):
    bad_file = tmp_path / "case.rtf"
    bad_file.write_text("hello", encoding="utf-8")
    with pytest.raises(ValueError):
        convert_to_text(bad_file)


def test_clean_ocr_page_has_no_low_confidence_lines(scanned_image_pdf):
    pages = convert_pdf(scanned_image_pdf)
    assert pages[0].low_confidence_lines == []


def test_degraded_ocr_page_is_flagged_for_manual_check(degraded_scanned_pdf):
    pages = convert_pdf(degraded_scanned_pdf)
    assert pages[0].source == "ocr"
    assert len(pages[0].low_confidence_lines) > 0


def test_ocr_page_image_persisted_when_output_dir_given(tmp_path, scanned_image_pdf):
    image_dir = tmp_path / "saved_pages"
    image_dir.mkdir()
    pages = convert_pdf(scanned_image_pdf, image_output_dir=image_dir)
    assert pages[0].source_image_path is not None
    assert pages[0].source_image_path.exists()
    assert pages[0].source_image_path.parent == image_dir


def test_text_layer_page_has_no_source_image(text_layer_pdf):
    pages = convert_pdf(text_layer_pdf)
    assert pages[0].source_image_path is None
    assert pages[0].low_confidence_lines == []
