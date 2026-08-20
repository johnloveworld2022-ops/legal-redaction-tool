#!/usr/bin/env python3
"""Export every reviewed candidate file for a case into the approved
folder. This is the single, deliberate release gate: nothing reaches
03_已批准可上传/ except through here or the automatic "all clean" path
in process_case.py.

Usage: approve_export.py <案件名称>
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from core.orchestrator import approve_case_export


def main() -> int:
    if len(sys.argv) < 2:
        print("用法: approve_export.py <案件名称>")
        return 1

    case_name = sys.argv[1]
    summary = approve_case_export(case_name)

    if summary.blocked_by_leak:
        print("🚨 以下文件在导出前的独立复查中发现可能残留的敏感信息,未导出:")
        for filename, leaks in summary.blocked_by_leak:
            print(f"  {filename}:")
            for leak in leaks:
                print(f"    - {leak}")
        print("请打开 02_候选脱敏/ 里对应文件人工检查,确认安全后再重新处理。\n")

    if summary.exported_count == 0:
        if not summary.blocked_by_leak:
            print(f"案件「{case_name}」的 02_候选脱敏/ 里没有待导出的文件。")
        return 1

    print(
        f"✅ 已将 {summary.exported_count} 份文件导出到:\n  {summary.approved_dir}\n"
        "只从这个文件夹里的文件复制给 AI。"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
