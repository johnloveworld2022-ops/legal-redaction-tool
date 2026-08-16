#!/usr/bin/env python3
"""Export every reviewed candidate file for a case into the approved
folder. This is the single, deliberate release gate: nothing reaches
03_已批准可上传/ except through here or the automatic "all clean" path
in process_case.py.

Usage: approve_export.py <案件名称>
"""
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from core.case_workspace import case_workspace_for


def main() -> int:
    if len(sys.argv) < 2:
        print("用法: approve_export.py <案件名称>")
        return 1

    case_name = sys.argv[1]
    ws = case_workspace_for(case_name)

    candidates = [
        p for p in ws.candidate_dir.glob("*_候选脱敏.txt") if p.is_file()
    ]
    if not candidates:
        print(f"案件「{case_name}」的 02_候选脱敏/ 里没有待导出的文件。")
        return 1

    for p in candidates:
        shutil.copy2(p, ws.approved_dir / p.name)

    print(
        f"✅ 已将 {len(candidates)} 份文件导出到:\n  {ws.approved_dir}\n"
        "只从这个文件夹里的文件复制给 AI。"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
