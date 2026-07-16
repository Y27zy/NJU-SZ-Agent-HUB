"""Repack an existing generated collection with the current hierarchy policy."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.database import get_connection
from src.rag.document_hierarchy import build_document_hierarchy
from src.rag.simple_vector_store import _publish_document_hierarchy


_GENERATED_WRAPPER = re.compile(r"\A#(?!#)\s+.*?\n+##(?!#)\s+.*?\n+", re.DOTALL)


def _reconstruct_processed_markdown(children: list[dict]) -> str:
    parts: list[str] = []
    current_group = None
    for child in children:
        group = child.get("group_title") or "未命名章节"
        if group != current_group:
            current_group = group
            parts.append(f"## {group}")
        body = _GENERATED_WRAPPER.sub("", child.get("processed_markdown") or "", count=1).strip()
        if body:
            parts.append(body)
    return "\n\n".join(parts)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("document_id", type=int)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    with get_connection() as conn:
        document_row = conn.execute("SELECT * FROM documents WHERE id = ?", (args.document_id,)).fetchone()
        if not document_row:
            raise SystemExit("Document not found.")
        document = dict(document_row)
        if document.get("document_role") == "collection":
            children = [
                dict(row)
                for row in conn.execute(
                    "SELECT * FROM documents WHERE parent_document_id = ? ORDER BY sort_order, id",
                    (args.document_id,),
                ).fetchall()
            ]
            source = _reconstruct_processed_markdown(children)
            previous_section_count = len(children)
        else:
            source = document.get("processed_markdown") or ""
            previous_section_count = 1
        hierarchy = build_document_hierarchy(source, document["title"], int(document.get("page_count") or 0))
        if hierarchy is None:
            raise SystemExit("The reconstructed document did not produce a hierarchy.")

        print(f"{previous_section_count} -> {len(hierarchy.sections)} sections")
        for section in hierarchy.sections:
            print(f"{section.sort_order:>3}  {section.group_title} / {section.title}")

        if args.apply:
            _publish_document_hierarchy(
                conn,
                document,
                hierarchy,
                document.get("original_text") or "",
                int(document.get("page_count") or 0),
                document.get("structure_json") or "",
            )
            print("Applied.")


if __name__ == "__main__":
    main()
