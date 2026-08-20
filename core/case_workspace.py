import shutil
from dataclasses import dataclass
from pathlib import Path

WORKBENCH_ROOT = Path.home() / "法律脱敏工作台"

LEXICON_FILENAME = "案件人员清单.txt"
MAPPING_FILENAME = "mapping.json.enc"


@dataclass
class CaseWorkspace:
    root: Path

    @property
    def raw_dir(self) -> Path:
        return self.root / "00_原始"

    @property
    def text_dir(self) -> Path:
        return self.root / "01_文本化"

    @property
    def candidate_dir(self) -> Path:
        return self.root / "02_候选脱敏"

    @property
    def approved_dir(self) -> Path:
        return self.root / "03_已批准可上传"

    @property
    def lexicon_path(self) -> Path:
        return self.root / LEXICON_FILENAME

    @property
    def mapping_path(self) -> Path:
        return self.root / MAPPING_FILENAME

    @property
    def keychain_service(self) -> str:
        return f"法律脱敏工具-{self.root.name}"

    def ensure_created(self) -> None:
        for d in (self.raw_dir, self.text_dir, self.candidate_dir, self.approved_dir):
            d.mkdir(parents=True, exist_ok=True)
        if not self.lexicon_path.exists():
            self.lexicon_path.write_text(
                "# 在下面每行填一个本案涉及的姓名/公司名/地址关键词,处理前先填好\n",
                encoding="utf-8",
            )

    def load_lexicon(self) -> list[str]:
        if not self.lexicon_path.exists():
            return []
        lines = self.lexicon_path.read_text(encoding="utf-8").splitlines()
        return [ln.strip() for ln in lines if ln.strip() and not ln.strip().startswith("#")]

    def import_raw_file(self, src: Path) -> Path:
        dest = self.raw_dir / src.name
        shutil.copy2(src, dest)
        return dest


def find_duplicate_lexicon_entries(entries: list[str]) -> list[str]:
    """Returns the distinct entries that appear more than once in the
    case's manually-curated name list (after trimming incidental
    whitespace). A lawyer typing the same name twice is the cheapest
    available signal that two different people in this case might share a
    name -- the redaction pipeline currently has no way to tell them
    apart (same string -> same token, unconditionally), so this is
    surfaced as an ambiguity that blocks auto-export rather than silently
    merging them into one identity.
    """
    seen: dict[str, int] = {}
    for raw in entries:
        entry = raw.strip()
        if not entry:
            continue
        seen[entry] = seen.get(entry, 0) + 1
    return [entry for entry, count in seen.items() if count > 1]


def case_workspace_for(case_name: str) -> CaseWorkspace:
    safe_name = case_name.strip()
    if not safe_name:
        raise ValueError("案件名称不能为空")
    ws = CaseWorkspace(root=WORKBENCH_ROOT / f"案件_{safe_name}")
    ws.ensure_created()
    return ws


def list_case_names() -> list[str]:
    """Existing case names (without the '案件_' folder prefix), for a case
    picker UI. Reads WORKBENCH_ROOT at call time so it respects the same
    monkeypatching tests use for case_workspace_for.
    """
    if not WORKBENCH_ROOT.exists():
        return []
    prefix = "案件_"
    return sorted(
        p.name[len(prefix):]
        for p in WORKBENCH_ROOT.iterdir()
        if p.is_dir() and p.name.startswith(prefix)
    )
