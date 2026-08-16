from core.convert import PageText
from core.pipeline import DocumentRedactionResult


def generate_report(
    results: list[tuple[str, DocumentRedactionResult]],
    ocr_pages: dict[str, list[PageText]] | None = None,
) -> str:
    ocr_pages = ocr_pages or {}
    any_blocked = any(not r.export_decision.auto_export for _, r in results)
    header = (
        "⚠️ 有文档需要人工核实,请看下面每份文档的详情,确认无误后再运行"
        "「批准并导出」。"
        if any_blocked
        else "✅ 所有文档均未发现需要人工核实的内容,可以直接批准导出。"
    )

    lines = ["# 脱敏处理报告", "", header, ""]
    for filename, result in results:
        lines.append(f"## {filename}")
        if result.export_decision.auto_export:
            lines.append("状态: ✅ 未发现需要人工核实的内容")
        else:
            lines.append("状态: ⚠️ 需要人工核实")
            for reason in result.export_decision.reasons:
                lines.append(f"- {reason}")
        lines.append(f"本文档共替换 {len(result.replacement.mapping)} 处敏感信息。")

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
