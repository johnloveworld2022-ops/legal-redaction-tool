import random

import pytest
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from core.ocr_vision import OCR_CONFIDENCE_THRESHOLD, ocr_image_page

CHINESE_FONT = "/System/Library/Fonts/STHeiti Light.ttc"
SENTENCE = "原告张三身份证号110101199003072316"


@pytest.fixture
def clean_image(tmp_path):
    img = Image.new("RGB", (900, 100), "white")
    d = ImageDraw.Draw(img)
    font = ImageFont.truetype(CHINESE_FONT, 40)
    d.text((20, 20), SENTENCE, font=font, fill="black")
    path = tmp_path / "clean.png"
    img.save(path)
    return path


@pytest.fixture
def degraded_image(tmp_path):
    # Simulates a poor-quality photocopy/scan: low contrast, heavy blur,
    # pixel noise -- the kind of input where Vision genuinely struggles
    # and can silently misread individual characters/digits.
    random.seed(42)
    img = Image.new("RGB", (900, 100), "white")
    d = ImageDraw.Draw(img)
    font = ImageFont.truetype(CHINESE_FONT, 40)
    d.text((20, 20), SENTENCE, font=font, fill=(135, 135, 135))
    img = img.filter(ImageFilter.GaussianBlur(2.5))
    px = img.load()
    w, h = img.size
    for x in range(w):
        for y in range(h):
            r, g, b = px[x, y]
            n = random.randint(-35, 35)
            px[x, y] = (
                max(0, min(255, r + n)),
                max(0, min(255, g + n)),
                max(0, min(255, b + n)),
            )
    path = tmp_path / "degraded.png"
    img.save(path)
    return path


def test_clean_scan_has_no_low_confidence_lines(clean_image):
    result = ocr_image_page(clean_image)
    assert SENTENCE in result.text
    assert result.low_confidence_lines == []


def test_degraded_scan_is_flagged_low_confidence(degraded_image):
    result = ocr_image_page(degraded_image)
    assert len(result.low_confidence_lines) > 0
    assert all(c < OCR_CONFIDENCE_THRESHOLD for _text, c in result.low_confidence_lines)


def test_all_lines_carry_a_confidence_score(clean_image):
    result = ocr_image_page(clean_image)
    assert len(result.lines) > 0
    for line in result.lines:
        assert 0.0 <= line.confidence <= 1.0
