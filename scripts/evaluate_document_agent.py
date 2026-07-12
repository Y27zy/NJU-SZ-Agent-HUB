"""Run the document processing Agent on local files and write quality reports."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.agent.document_processing_agent import DocumentProcessingAgent
from src.database import fetch_one


def _duplicate_block_count(markdown: str) -> int:
    """Count exact repeated prose blocks long enough to be meaningful."""
    seen: set[str] = set()
    duplicates = 0
    for block in re.split(r"\n{2,}", markdown):
        normalized = re.sub(r"\s+", "", re.sub(r"<!--.*?-->", "", block)).lower()
        if block.lstrip().startswith(("#", "<!--", "```", "|")) or len(normalized) < 30:
            continue
        if normalized in seen:
            duplicates += 1
        seen.add(normalized)
    return duplicates


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate DocumentProcessingAgent with real local documents.")
    parser.add_argument("files", nargs="+", type=Path, help="PDF/PPTX/TXT/Markdown files to process")
    parser.add_argument("--username", default="youzy", help="Account whose default model is used")
    parser.add_argument("--output", type=Path, default=Path("storage/document_benchmarks"))
    return parser.parse_args()


def main() -> None:
    args = _args()
    user = fetch_one("SELECT id FROM users WHERE username = ?", (args.username,))
    if not user:
        raise SystemExit(f"User not found: {args.username}")
    args.output.mkdir(parents=True, exist_ok=True)
    source_dir = args.output / "sources"
    source_dir.mkdir(exist_ok=True)

    reports = []
    for source in args.files:
        source = source.resolve()
        if not source.exists():
            print(f"SKIP missing file: {source}")
            continue
        local_source = source_dir / source.name
        shutil.copy2(source, local_source)
        started = time.perf_counter()
        result = DocumentProcessingAgent(int(user["id"])).run(
            local_source,
            source.stem,
            "资料",
            force=True,
        )
        elapsed = round(time.perf_counter() - started, 2)
        structure = json.loads(result.structure_json)
        markdown_path = args.output / f"{source.stem}.md"
        structure_path = args.output / f"{source.stem}.structure.json"
        markdown_path.write_text(result.markdown, encoding="utf-8")
        structure_path.write_text(json.dumps(structure, ensure_ascii=False, indent=2), encoding="utf-8")
        report = {
            "file": str(source),
            "model": result.model_name,
            "strategy": structure.get("processing", {}).get("strategy"),
            "page_count": result.page_count,
            "chapter_count": len(structure.get("chapters") or []),
            "markdown_characters": len(result.markdown),
            "duplicate_prose_blocks": _duplicate_block_count(result.markdown),
            "audit_issue_count": len(result.audit_issues),
            "elapsed_seconds": elapsed,
            "markdown_output": str(markdown_path.resolve()),
        }
        reports.append(report)
        print(json.dumps(report, ensure_ascii=False, indent=2))

    report_path = args.output / "benchmark-report.json"
    report_path.write_text(json.dumps(reports, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nReport: {report_path.resolve()}")


if __name__ == "__main__":
    main()
