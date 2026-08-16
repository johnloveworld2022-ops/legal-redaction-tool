#!/usr/bin/env python3
"""Import one or more case files, run the full local redaction pipeline,
and either auto-export the clean result or leave it for manual review.

Also accepts .txt input directly (no conversion/OCR) -- this is how a
corrected transcription gets fed back in after fixing an OCR misread found
via the review report: edit the .txt file saved under 01_文本化/, then drop
that corrected .txt back onto this same case.

Usage: process_case.py <案件名称> <file1> [file2 ...]
"""
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from core.case_workspace import case_workspace_for
from core.convert import PageText, convert_docx, convert_pdf, pages_to_text
from core.mapping_store import MappingStore
from core.ollama_client import OllamaClient
from core.pipeline import DocumentRedactionResult, StageResult, redact_document
from core.report import generate_report


def _convert(raw_path: Path, image_output_dir: Path) -> tuple[str, list[PageText]]:
    """Returns (text, ocr_pages). ocr_pages is empty for non-PDF input, or
    for a .txt file being fed back in as an already-human-corrected
    transcription -- there is nothing left to OCR-check in either case.
    """
    suffix = raw_path.suffix.lower()
    if suffix == ".txt":
        return raw_path.read_text(encoding="utf-8"), []
    if suffix == ".docx":
        return convert_docx(raw_path, image_output_dir=image_output_dir)
    if suffix == ".pdf":
        pages = convert_pdf(raw_path, image_output_dir=image_output_dir)
        return pages_to_text(pages), [p for p in pages if p.source in ("ocr", "mixed")]
    raise ValueError(f"不支持的文件类型: {suffix}(目前支持 .docx、.pdf、.txt)")


def main() -> int:
    if len(sys.argv) < 3:
        print("用法: process_case.py <案件名称> <file1> [file2 ...]")
        return 1

    case_name = sys.argv[1]
    input_files = [Path(p) for p in sys.argv[2:]]

    ws = case_workspace_for(case_name)
    lexicon = ws.load_lexicon()
    if not lexicon:
        print(
            "提醒:案件人员清单是空的。建议先在\n"
            f"  {ws.lexicon_path}\n"
            "里填入本案涉及的姓名/公司名,再处理效果会好很多——但仍会继续处理。\n"
        )

    mapping_store = MappingStore(path=ws.mapping_path, keychain_service=ws.keychain_service)
    running_mapping = mapping_store.load()

    client = OllamaClient()
    results: list[tuple[str, DocumentRedactionResult]] = []
    ocr_pages_by_file: dict[str, list[PageText]] = {}

    for src in input_files:
        if not src.exists():
            print(f"跳过:文件不存在 {src}")
            continue
        raw_path = ws.import_raw_file(src)
        try:
            text, ocr_pages = _convert(raw_path, image_output_dir=ws.text_dir)
        except Exception as e:
            print(f"❌ {raw_path.name} 转换失败,已跳过: {e}")
            continue

        (ws.text_dir / f"{raw_path.stem}.txt").write_text(text, encoding="utf-8")
        ocr_pages_by_file[raw_path.name] = ocr_pages

        low_conf_count = sum(len(p.low_confidence_lines) for p in ocr_pages)
        extra_stages = [StageResult("ocr", ok=True, low_confidence_count=low_conf_count)]

        result = redact_document(
            text, lexicon, client,
            existing_mapping=running_mapping, extra_stages=extra_stages,
        )
        running_mapping = result.replacement.mapping

        candidate_path = ws.candidate_dir / f"{raw_path.stem}_候选脱敏.txt"
        candidate_path.write_text(result.replacement.text, encoding="utf-8")
        results.append((raw_path.name, result))

    if not results:
        print("没有成功处理任何文件。")
        return 1

    mapping_store.save(running_mapping)

    report_text = generate_report(results, ocr_pages=ocr_pages_by_file)
    (ws.candidate_dir / "审核报告.md").write_text(report_text, encoding="utf-8")

    all_clean = all(r.export_decision.auto_export for _, r in results)
    if all_clean:
        for filename, _ in results:
            stem = Path(filename).stem
            src = ws.candidate_dir / f"{stem}_候选脱敏.txt"
            shutil.copy2(src, ws.approved_dir / src.name)
        print(
            f"✅ {len(results)} 份文件未发现需要人工核实的内容,"
            f"已直接导出到:\n  {ws.approved_dir}"
        )
    else:
        print(
            "⚠️ 有文件需要你确认后才能导出。请查看:\n"
            f"  {ws.candidate_dir / '审核报告.md'}\n"
            "确认没问题后,运行「批准并导出」。"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
