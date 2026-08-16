"""Case-level orchestration: import files, run the full redaction
pipeline, and decide auto-export vs review. This is the single code path
shared by the CLI scripts (process_case.py, approve_export.py) and the web
GUI, so both surfaces are exercised by the same tests.
"""
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from core.case_workspace import CaseWorkspace, case_workspace_for
from core.convert import PageText, convert_docx, convert_pdf, pages_to_text
from core.mapping_store import MappingStore
from core.ollama_client import OllamaClient
from core.pipeline import DocumentRedactionResult, StageResult, redact_document
from core.report import generate_report


@dataclass
class ProcessSummary:
    case_name: str
    workspace: CaseWorkspace
    all_clean: bool
    exported_files: list[Path] = field(default_factory=list)
    report_path: Path | None = None
    processed_filenames: list[str] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)  # (filename, reason)


@dataclass
class ApproveSummary:
    case_name: str
    approved_dir: Path
    exported_count: int


def _convert(raw_path: Path, image_output_dir: Path) -> tuple[str, list[PageText]]:
    """Returns (text, ocr_pages). ocr_pages is empty for a .txt file being
    fed back in as an already-human-corrected transcription -- there is
    nothing left to OCR-check.
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


def process_case_files(
    case_name: str, file_paths: list[Path], llm_client=None,
) -> ProcessSummary:
    ws = case_workspace_for(case_name)
    lexicon = ws.load_lexicon()

    mapping_store = MappingStore(path=ws.mapping_path, keychain_service=ws.keychain_service)
    running_mapping = mapping_store.load()

    client = llm_client if llm_client is not None else OllamaClient()
    results: list[tuple[str, DocumentRedactionResult]] = []
    ocr_pages_by_file: dict[str, list[PageText]] = {}
    processed_filenames: list[str] = []
    skipped: list[tuple[str, str]] = []

    for src in file_paths:
        if not src.exists():
            skipped.append((src.name, "文件不存在"))
            continue
        raw_path = ws.import_raw_file(src)
        try:
            text, ocr_pages = _convert(raw_path, image_output_dir=ws.text_dir)
        except Exception as e:
            skipped.append((raw_path.name, str(e)))
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
        processed_filenames.append(raw_path.name)

    if not results:
        return ProcessSummary(
            case_name=case_name, workspace=ws, all_clean=False, skipped=skipped,
        )

    mapping_store.save(running_mapping)

    report_text = generate_report(results, ocr_pages=ocr_pages_by_file)
    report_path = ws.candidate_dir / "审核报告.md"
    report_path.write_text(report_text, encoding="utf-8")

    all_clean = all(r.export_decision.auto_export for _, r in results)
    exported_files: list[Path] = []
    if all_clean:
        for filename, _ in results:
            stem = Path(filename).stem
            src = ws.candidate_dir / f"{stem}_候选脱敏.txt"
            dest = ws.approved_dir / src.name
            shutil.copy2(src, dest)
            exported_files.append(dest)

    return ProcessSummary(
        case_name=case_name, workspace=ws, all_clean=all_clean,
        exported_files=exported_files, report_path=report_path,
        processed_filenames=processed_filenames, skipped=skipped,
    )


def approve_case_export(case_name: str) -> ApproveSummary:
    ws = case_workspace_for(case_name)
    candidates = [p for p in ws.candidate_dir.glob("*_候选脱敏.txt") if p.is_file()]
    for p in candidates:
        shutil.copy2(p, ws.approved_dir / p.name)
    return ApproveSummary(
        case_name=case_name, approved_dir=ws.approved_dir, exported_count=len(candidates),
    )
