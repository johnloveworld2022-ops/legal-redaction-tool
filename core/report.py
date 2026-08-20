from core.convert import PageText
from core.pipeline import DocumentRedactionResult


def generate_report(
    results: list[tuple[str, DocumentRedactionResult]],
    ocr_pages: dict[str, list[PageText]] | None = None,
    failed_pages: dict[str, list[PageText]] | None = None,
    duplicate_lexicon_names: list[str] | None = None,
) -> str:
    ocr_pages = ocr_pages or {}
    failed_pages = failed_pages or {}
    duplicate_lexicon_names = duplicate_lexicon_names or []
    any_blocked = any(not r.export_decision.auto_export for _, r in results)
    header = (
        "⚠️ 有文档需要人工核实,请看下面每份文档的详情,确认无误后再运行"
        "「批准并导出」。"
        if any_blocked
        else "✅ 所有文档均未发现需要人工核实的内容,可以直接批准导出。"
    )

    lines = ["# 脱敏处理报告", "", header, ""]

    if duplicate_lexicon_names:
        lines.append("## ⚠️ 同名待确认")
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
