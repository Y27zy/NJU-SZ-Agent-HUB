"""Apply deterministic scan/readability cleanup to an existing document tree."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.database import fetch_all, fetch_one
from src.rag.document_assets import full_page_scan_pages
from src.rag.markdown_quality import optimize_scanned_page_markdown
from src.rag.simple_vector_store import update_document_markdown


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("document_id", type=int)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    root = fetch_one("SELECT * FROM documents WHERE id = ?", (args.document_id,))
    if not root:
        raise SystemExit("Document not found.")
    rows = fetch_all(
        "SELECT * FROM documents WHERE parent_document_id = ? ORDER BY sort_order, id",
        (args.document_id,),
    )
    documents = [dict(row) for row in rows] if rows else [dict(root)]
    scan_pages = full_page_scan_pages(root["file_path"] or "")
    before_quotes = before_images = after_quotes = after_images = changed = 0

    for document in documents:
        source = document.get("processed_markdown") or ""
        optimized = optimize_scanned_page_markdown(source, scan_pages)
        before_quotes += len(re.findall(r"(?m)^\s{0,3}>", source))
        before_images += source.count("asset://")
        after_quotes += len(re.findall(r"(?m)^\s{0,3}>", optimized))
        after_images += optimized.count("asset://")
        if optimized == source.strip():
            continue
        changed += 1
        if args.apply and not update_document_markdown(
            int(root["user_id"]),
            int(document["id"]),
            optimized,
            admin=True,
        ):
            raise SystemExit(f"Failed to update document {document['id']}.")

    print(
        {
            "documents": len(documents),
            "changed": changed,
            "full_page_scan_pages": len(scan_pages),
            "blockquote_lines": [before_quotes, after_quotes],
            "scan_references": [before_images, after_images],
            "applied": args.apply,
        }
    )


if __name__ == "__main__":
    main()
