#!/usr/bin/env python3
"""Import one or more case files, run the full local redaction pipeline,
and either auto-export the clean result or leave it for manual review.

Also accepts .txt input directly (no conversion/OCR) -- this is how a
corrected transcription gets fed back in after fixing an OCR misread found
via the review report: edit the .txt file saved under 01_文本化/, then drop
that corrected .txt back onto this same case.

Usage: process_case.py <案件名称> <file1> [file2 ...]
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from core.orchestrator import process_case_files


def main() -> int:
    if len(sys.argv) < 3:
        print("用法: process_case.py <案件名称> <file1> [file2 ...]")
        return 1

    case_name = sys.argv[1]
    input_files = [Path(p) for p in sys.argv[2:]]

    summary = process_case_files(case_name, input_files)

    for filename, reason in summary.skipped:
        print(f"跳过:{filename}{reason}")

    if not summary.processed_filenames:
        print("没有成功处理任何文件。")
        return 1

    if not summary.workspace.load_lexicon():
        print(
            "提醒:案件人员清单是空的。建议先在\n"
            f"  {summary.workspace.lexicon_path}\n"
            "里填入本案涉及的姓名/公司名,再处理效果会好很多——下次处理时生效。\n"
        )

    if summary.all_clean:
        print(
            f"✅ {len(summary.exported_files)} 份文件未发现需要人工核实的内容,"
            f"已直接导出到:\n  {summary.workspace.approved_dir}"
        )
    else:
        print(
            "⚠️ 有文件需要你确认后才能导出。请查看:\n"
            f"  {summary.report_path}\n"
            "确认没问题后,运行「批准并导出」。"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
