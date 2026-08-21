from core.convert import PageText
from core.pipeline import DocumentRedactionResult

# Headings generate_report emits that are NOT a per-document filename.
# Callers merging preserved sections from an old report (see
# merge_preserved_sections) must exclude these when deciding which "## "
# headings represent other documents in the case, or the case-level
# section would be duplicated (once freshly regenerated, once preserved).
_DUPLICATE_NAMES_HEADING = "⚠️ 同名待确认"
CASE_LEVEL_HEADINGS = {_DUPLICATE_NAMES_HEADING}


def generate_report(
    results: list[tuple[str, DocumentRedactionResult]],
    ocr_pages: dict[str, list[PageText]] | None = None,
    failed_pages: dict[str, list[PageText]] | None = None,
    duplicate_lexicon_names: list[str] | None = None,
    leaks: dict[str, list[str]] | None = None,
) -> str:
    ocr_pages = ocr_pages or {}
    failed_pages = failed_pages or {}
    duplicate_lexicon_names = duplicate_lexicon_names or []
    leaks = leaks or {}
    any_leak = any(doc_leaks for doc_leaks in leaks.values())
    any_blocked = any_leak or any(not r.export_decision.auto_export for _, r in results)
    header = (
        "⚠️ 有文档需要人工核实,请看下面每份文档的详情,确认无误后再运行"
        "「批准并导出」。"
        if any_blocked
        else "✅ 所有文档均未发现需要人工核实的内容,可以直接批准导出。"
    )

    lines = ["# 脱敏处理报告", "", header, ""]

    if duplicate_lexicon_names:
        lines.append(f"## {_DUPLICATE_NAMES_HEADING}")
        lines.append(
            "「案件人员清单」里以下姓名出现了不止一次,可能是本案里有两个不同的人"
            "恰好同名——系统目前没办法自动区分,会把它们当成同一个人替换成同一个"
            "占位符。请确认:如果确实是同一个人重复写了,把清单里多余的一行删掉;"
            "如果确实是两个不同的人,建议分开处理,或者先用其他能区分的方式"
            "(比如加上角色说明)手动核对每处指代的是谁。"
        )
        for name in duplicate_lexicon_names:
            lines.append(f"- {name}")
        lines.append("")
    for filename, result in results:
        lines.append(f"## {filename}")

        doc_leaks = leaks.get(filename, [])
        if doc_leaks:
            lines.append("### 🚨 检测到可能的信息残留(独立复查发现,优先处理)")
            lines.append(
                "系统在导出前对最终文本做了一次独立复查,发现以下内容可能仍然"
                "包含未脱敏的敏感信息。这个检查和上面的正常审核是分开的、更严格"
                "的一道关卡——即使其他部分显示「没问题」,这里列出的内容也必须"
                "先处理掉才能导出。"
            )
            for leak in doc_leaks:
                lines.append(f"- {leak}")
            lines.append("")

        if result.export_decision.auto_export:
            lines.append("状态: ✅ 未发现需要人工核实的内容")
        else:
            lines.append("状态: ⚠️ 需要人工核实")
            for reason in result.export_decision.reasons:
                lines.append(f"- {reason}")
        lines.append(f"本文档共替换 {len(result.replacement.mapping)} 处敏感信息。")

        doc_failed_pages = failed_pages.get(filename, [])
        if doc_failed_pages:
            lines.append("")
            lines.append("### ⚠️ 处理失败(以下内容未能识别,不能确认是否安全)")
            for page in doc_failed_pages:
                lines.append(f"- 第 {page.page_number} 页处理失败: {page.failure_reason}")
            lines.append(
                "这些页面/图片的内容未能被识别,系统无法确认里面是否包含敏感信息。"
                "请打开原始文件人工检查这些页面,确认安全后再考虑是否导出。"
            )

        flagged_pages = [p for p in ocr_pages.get(filename, []) if p.low_confidence_lines]
        if flagged_pages:
            lines.append("")
            lines.append("### OCR 核对(识别质量较低,建议对照原图逐条检查)")
            for page in flagged_pages:
                image_hint = (
                    f"原图: {page.source_image_path.name}"
                    if page.source_image_path is not None
                    else "(未保存原图)"
                )
                lines.append(f"- 第 {page.page_number} 页,{image_hint}")
                for text, confidence in page.low_confidence_lines:
                    lines.append(f"  - 可疑文字(置信度 {confidence:.2f}): 「{text}」")
            lines.append(
                "如发现识别错误,可直接打开 01_文本化/ 里对应的 .txt 文件手动改正,"
                "改完后把这个 .txt 文件重新拖进「导入新卷宗」(填相同的案件名称)"
                "即可用你改正后的文字重新处理。"
            )
        lines.append("")
    return "\n".join(lines)


def list_document_headings(report_text: str) -> set[str]:
    """All '## X' heading titles in a report string, including
    CASE_LEVEL_HEADINGS entries -- callers deciding which headings
    represent actual per-document filenames (as opposed to a case-level
    section) must subtract CASE_LEVEL_HEADINGS themselves.
    """
    return {line[3:] for line in report_text.split("\n") if line.startswith("## ")}


def extract_document_sections(report_text: str, filenames: set[str]) -> dict[str, str]:
    """Parse a report string previously produced by generate_report and
    return {filename: full markdown section (heading through the next
    '## ' heading or end of text)} for every name in `filenames` that has
    a matching '## {filename}' heading. Headings that aren't in
    `filenames` (e.g. the case-level "## ⚠️ 同名待确认" heading, which
    also starts with "## " but is not a per-document filename) are
    skipped, not mistaken for a document section.

    Used by merge_preserved_sections to carry another document's
    already-computed review section forward when regenerating a report
    for a different subset of a case's documents.
    """
    sections: dict[str, str] = {}
    current_name: str | None = None
    current_lines: list[str] = []

    def _flush() -> None:
        if current_name is not None:
            sections[current_name] = "\n".join(current_lines).rstrip("\n")

    for line in report_text.split("\n"):
        if line.startswith("## "):
            _flush()
            heading = line[3:]
            if heading in filenames:
                current_name = heading
                current_lines = [line]
            else:
                current_name = None
                current_lines = []
        elif current_name is not None:
            current_lines.append(line)
    _flush()
    return sections


def merge_preserved_sections(report_text: str, preserved_sections: dict[str, str]) -> str:
    """Append preserved per-document sections (extracted from a PRIOR
    report via extract_document_sections, for documents not part of the
    current regeneration) after report_text's own freshly-generated
    sections, and upgrade the summary header to the "needs review"
    wording if any preserved section still indicates it needs review.

    Exists because process_case_files only ever knows about the
    documents passed into the CURRENT call -- without this, reprocessing
    a single corrected file (the documented OCR-correction workflow)
    would silently discard every other document's review status when
    审核报告.md gets regenerated and overwritten from just that one file.
    Real bug found via external architecture review; see
    grill-report-2026-08-21.md.
    """
    if not preserved_sections:
        return report_text

    any_preserved_needs_review = any(
        "⚠️ 需要人工核实" in section or "🚨" in section
        for section in preserved_sections.values()
    )

    lines = report_text.split("\n")
    if any_preserved_needs_review:
        for i, line in enumerate(lines):
            if line.startswith("✅ 所有文档均未发现"):
                lines[i] = (
                    "⚠️ 有文档需要人工核实,请看下面每份文档的详情,确认无误后再运行"
                    "「批准并导出」。"
                )
                break

    merged_text = "\n".join(lines).rstrip("\n")
    for name in sorted(preserved_sections):
        merged_text += "\n\n" + preserved_sections[name]
    return merged_text + "\n"
