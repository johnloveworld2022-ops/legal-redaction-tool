from pathlib import Path

from core.convert import PageText
from core.merge_replace import ReplacementResult
from core.pipeline import DocumentRedactionResult, ExportDecision, StageResult
from core.report import generate_report


def _clean_result():
    return DocumentRedactionResult(
        replacement=ReplacementResult(text="ok", mapping={}),
        stages=[StageResult("regex", ok=True)],
        export_decision=ExportDecision(auto_export=True, reasons=[]),
    )


def _blocked_result(reasons):
    return DocumentRedactionResult(
        replacement=ReplacementResult(text="⟦人名001⟧", mapping={"⟦人名001⟧": "张三"}),
        stages=[StageResult("ocr", ok=True, low_confidence_count=1)],
        export_decision=ExportDecision(auto_export=False, reasons=reasons),
    )


def test_clean_case_header_says_ready_to_export():
    report = generate_report([("a.pdf", _clean_result())])
    assert "可以直接批准导出" in report


def test_blocked_case_header_flags_review_needed():
    report = generate_report([("a.pdf", _blocked_result(["ocr 发现 1 处需人工核实的疑似内容"]))])
    assert "需要人工核实" in report


def test_ocr_low_confidence_page_lists_image_path_and_suspect_text():
    result = _blocked_result(["ocr 发现 1 处需人工核实的疑似内容"])
    page = PageText(
        page_number=3,
        text="garbled",
        source="ocr",
        low_confidence_lines=[("数售法三學份源号", 0.3)],
        source_image_path=Path("/tmp/case_第0003页_原图.png"),
    )
    report = generate_report(
        [("case.pdf", result)], ocr_pages={"case.pdf": [page]}
    )
    assert "第 3 页" in report
    assert "case_第0003页_原图.png" in report
    assert "数售法三學份源号" in report
    assert "0.30" in report


def test_clean_ocr_pages_produce_no_extra_section():
    result = _clean_result()
    page = PageText(page_number=1, text="fine", source="ocr", low_confidence_lines=[])
    report = generate_report([("case.pdf", result)], ocr_pages={"case.pdf": [page]})
    assert "OCR 核对" not in report


def test_failed_pages_listed_with_reason():
    result = _blocked_result(["处理台账 检测未能正常完成,需人工确认"])
    failed_page = PageText(
        page_number=5, text="", source="failed",
        failure_reason="第 5 页处理失败: 外部命令超时(120秒): pdftoppm",
    )
    report = generate_report(
        [("case.pdf", result)], failed_pages={"case.pdf": [failed_page]}
    )
    assert "第 5 页" in report
    assert "外部命令超时" in report
    assert "处理失败" in report


def test_no_failed_pages_produces_no_failure_section():
    result = _clean_result()
    report = generate_report([("case.pdf", result)], failed_pages={"case.pdf": []})
    assert "处理失败" not in report


def test_duplicate_lexicon_names_listed_once_at_case_level():
    result = _blocked_result(["同名待确认 发现 1 处需人工核实的疑似内容"])
    report = generate_report([("case.pdf", result)], duplicate_lexicon_names=["张三"])
    assert "张三" in report
    assert "同名" in report or "重复" in report


def test_no_duplicate_names_produces_no_ambiguity_section():
    result = _clean_result()
    report = generate_report([("case.pdf", result)], duplicate_lexicon_names=[])
    assert "同名待确认" not in report
