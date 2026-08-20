#!/usr/bin/env python3
"""Golden-corpus recall/precision scorecard against the real detection
pipeline (regex + LLM via Ollama; the case-lexicon layer is deliberately
NOT used here, so this measures what regex+LLM alone can do without a
lawyer's manual name list helping it -- a harder, more conservative bar).

This is NOT part of the pytest suite: it needs a running Ollama server,
takes real wall-clock minutes (multiple real model calls per document),
and its job is different from a unit test -- it is a REGRESSION FLOOR
against a small, curated, synthetic corpus, not a claim about real-world
recall on her actual photographed case files (which this corpus does not
yet include -- see the tool's README "已知局限").

Methodology and thresholds follow the same approach used by the closest
comparable open-source tool (TracyWang95/DataInfra-RedactionEverything's
e2e/industry_recall.py), verified by reading its actual source: identity
entities (name/ID/phone/bank card) must reach 100% recall in this corpus;
standard entities (address/org/email/birthdate/case number) must reach
>= 85%. A ground-truth string counts as caught if it appears as a
substring of any real value in the pipeline's output mapping.

Usage:
    python scripts/golden_recall.py [corpus_dir] [--repeat N]
    (corpus_dir defaults to golden_corpus/legal relative to the repo root;
    --repeat N re-runs every document N times against the real model and
    reports which ground-truth entities were NOT caught on every single
    run -- Ollama's sampling is not perfectly deterministic even at
    temperature=0 in practice, so a single run can look clean by luck.
    Costs N times the wall-clock; defaults to 1, i.e. no extra cost.)
"""
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from core.ollama_client import OllamaClient
from core.pipeline import redact_document

IDENTITY_MIN_RECALL = 1.0
STANDARD_MIN_RECALL = 0.85


def _matched(ground_truth_text: str, mapped_real_values: list[str]) -> bool:
    return any(ground_truth_text in value for value in mapped_real_values)


def _parse_args(argv: list[str]) -> tuple[Path, int]:
    corpus_dir = REPO_ROOT / "golden_corpus" / "legal"
    repeat = 1
    positional = []
    i = 0
    while i < len(argv):
        if argv[i] == "--repeat":
            repeat = int(argv[i + 1])
            i += 2
        else:
            positional.append(argv[i])
            i += 1
    if positional:
        corpus_dir = Path(positional[0])
    return corpus_dir, repeat


def main() -> int:
    corpus_dir, repeat = _parse_args(sys.argv[1:])
    expected_path = corpus_dir / "expected.json"
    expected = json.loads(expected_path.read_text(encoding="utf-8"))

    client = OllamaClient()

    totals = {"identity": [0, 0], "standard": [0, 0]}  # [recalled, total]
    rows: list[tuple[str, str, str, str]] = []  # (doc, category, gt_text, status)
    extras_by_doc: dict[str, list[str]] = {}
    unstable: list[str] = []  # entities not caught on every repeated run

    for filename, groups in expected.items():
        if filename.startswith("_"):
            continue
        doc_path = corpus_dir / filename
        text = doc_path.read_text(encoding="utf-8")

        run_mapped_values: list[list[str]] = []
        for run_idx in range(repeat):
            suffix = f" (第 {run_idx + 1}/{repeat} 次)" if repeat > 1 else ""
            print(f"[running] {filename} ({len(text)} 字符){suffix}...", file=sys.stderr)
            result = redact_document(text, lexicon=[], llm_client=client)
            run_mapped_values.append(list(result.replacement.mapping.values()))

        # A ground-truth entity counts as recalled here only if EVERY run
        # caught it -- this is what actually exposes non-determinism, as
        # opposed to just checking the union across runs (which would
        # hide exactly the "sometimes misses it" behavior being tested).
        mapped_values = run_mapped_values[0]
        for category in ("identity", "standard"):
            for gt_text in groups.get(category, []):
                totals[category][1] += 1
                hit_every_run = all(_matched(gt_text, mv) for mv in run_mapped_values)
                if hit_every_run:
                    totals[category][0] += 1
                elif repeat > 1:
                    unstable.append(f"{filename}: 「{gt_text}」并非每次都被识别到")
                rows.append((filename, category, gt_text, "✅" if hit_every_run else "❌"))

        expected_all = set(groups.get("identity", [])) | set(groups.get("standard", []))
        extras = [
            v for v in mapped_values
            if not any(gt in v or v in gt for gt in expected_all)
        ]
        if extras:
            extras_by_doc[filename] = extras

    print()
    print("=" * 70)
    print(f"{'文档':<42}{'类别':<10}{'真值':<20}{'结果'}")
    print("-" * 70)
    for filename, category, gt_text, status in rows:
        print(f"{filename:<42}{category:<10}{gt_text:<20}{status}")
    print("=" * 70)

    identity_recall = totals["identity"][0] / totals["identity"][1] if totals["identity"][1] else 1.0
    standard_recall = totals["standard"][0] / totals["standard"][1] if totals["standard"][1] else 1.0

    print(f"identity 召回率: {totals['identity'][0]}/{totals['identity'][1]} = {identity_recall:.1%}"
          f"  (门槛 {IDENTITY_MIN_RECALL:.0%})")
    print(f"standard 召回率: {totals['standard'][0]}/{totals['standard'][1]} = {standard_recall:.1%}"
          f"  (门槛 {STANDARD_MIN_RECALL:.0%})")

    if extras_by_doc:
        print()
        print("疑似过度脱敏(替换了真值列表之外的内容,建议人工核查是否合理):")
        for filename, extras in extras_by_doc.items():
            for v in extras:
                print(f"  {filename}: 「{v}」")
    else:
        print()
        print("未发现真值列表之外的替换内容。")

    if repeat > 1:
        print()
        if unstable:
            print(f"⚠️ 跑了 {repeat} 次,以下条目不是每次都被识别到(暴露了大模型的不稳定性):")
            for line in unstable:
                print(f"  {line}")
        else:
            print(f"跑了 {repeat} 次,结果保持一致,未发现不稳定的条目。")

    passed = identity_recall >= IDENTITY_MIN_RECALL and standard_recall >= STANDARD_MIN_RECALL
    print()
    print("结果: " + ("✅ 通过" if passed else "❌ 未达到回归门槛"))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
