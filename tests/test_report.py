from pathlib import Path

from core.convert import PageText
from core.merge_replace import ReplacementResult
from core.pipeline import DocumentRedactionResult, ExportDecision, StageResult
from core.report import (
    CASE_LEVEL_HEADINGS, extract_document_sections, generate_report,
    list_document_headings, merge_preserved_sections,
)


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


def test_extract_document_sections_pulls_out_matching_headings():
    result_a = _blocked_result(["ocr 发现 1 处需人工核实的疑似内容"])
    result_b = _clean_result()
    report = generate_report([("a.pdf", result_a), ("b.pdf", result_b)])

    sections = extract_document_sections(report, {"a.pdf", "b.pdf"})
    assert set(sections.keys()) == {"a.pdf", "b.pdf"}
    assert sections["a.pdf"].startswith("## a.pdf")
    assert "需要人工核实" in sections["a.pdf"]
    assert sections["b.pdf"].startswith("## b.pdf")
    assert "未发现需要人工核实" in sections["b.pdf"]


def test_extract_document_sections_ignores_non_matching_headings():
    # the "同名待确认" case-level heading also starts with "## " but is
    # not a per-document filename -- must not be mistaken for one.
    result = _clean_result()
    report = generate_report(
        [("a.pdf", result)], duplicate_lexicon_names=["张三"],
    )
    sections = extract_document_sections(report, {"a.pdf"})
    assert set(sections.keys()) == {"a.pdf"}


def test_extract_document_sections_returns_empty_for_unknown_filenames():
    result = _clean_result()
    report = generate_report([("a.pdf", result)])
    sections = extract_document_sections(report, {"nonexistent.pdf"})
    assert sections == {}


def test_merge_preserved_sections_appends_them_after_fresh_content():
    fresh_result = _clean_result()
    fresh_report = generate_report([("new.txt", fresh_result)])
    preserved = {"old.pdf": "## old.pdf\n状态: ✅ 未发现需要人工核实的内容\n本文档共替换 0 处敏感信息。"}

    merged = merge_preserved_sections(fresh_report, preserved)
    assert "## new.txt" in merged
    assert "## old.pdf" in merged
    # fresh section still comes before the preserved one
    assert merged.index("## new.txt") < merged.index("## old.pdf")


def test_merge_preserved_sections_upgrades_header_when_preserved_needs_review():
    fresh_result = _clean_result()
    fresh_report = generate_report([("new.txt", fresh_result)])
    assert "可以直接批准导出" in fresh_report  # sanity: starts clean

    preserved = {
        "old.pdf": (
            "## old.pdf\n状态: ⚠️ 需要人工核实\n- llm 发现 1 处需人工核实的疑似内容\n"
            "本文档共替换 1 处敏感信息。"
        )
    }
    merged = merge_preserved_sections(fresh_report, preserved)
    assert "需要人工核实" in merged.split("\n")[2]  # header line upgraded
    assert "可以直接批准导出" not in merged


def test_merge_preserved_sections_with_empty_dict_is_a_no_op():
    fresh_result = _clean_result()
    fresh_report = generate_report([("new.txt", fresh_result)])
    assert merge_preserved_sections(fresh_report, {}) == fresh_report


def test_list_document_headings_finds_all_headings_including_case_level():
    result = _clean_result()
    report = generate_report(
        [("a.pdf", result), ("b.pdf", result)], duplicate_lexicon_names=["张三"],
    )
    headings = list_document_headings(report)
    assert headings == {"a.pdf", "b.pdf", "⚠️ 同名待确认"}


def test_case_level_headings_constant_matches_what_generate_report_emits():
    # guards against report.py's actual case-level heading text drifting
    # away from the constant orchestrator.py relies on to exclude it
    # from "other documents in this case" when merging preserved sections
    result = _clean_result()
    report = generate_report([("a.pdf", result)], duplicate_lexicon_names=["张三"])
    headings = list_document_headings(report)
    assert headings - {"a.pdf"} == CASE_LEVEL_HEADINGS


def test_leak_listed_prominently_with_distinct_severity():
    result = _blocked_result(["regex 发现 1 处需人工核实的疑似内容"])
    report = generate_report(
        [("case.pdf", result)],
        leaks={"case.pdf": ["「张三」的脱敏未完全生效,在最终文本中仍能找到"]},
    )
    assert "🚨" in report
    assert "张三" in report


def test_no_leaks_produces_no_leak_section():
    result = _clean_result()
    report = generate_report([("case.pdf", result)], leaks={"case.pdf": []})
    assert "🚨" not in report
