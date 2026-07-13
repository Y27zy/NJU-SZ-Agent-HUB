"""Delete one user's private content while keeping the login account intact."""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config import STORAGE_DIR, UPLOAD_DIR
from src.database import fetch_one, get_connection
from src.rag.document_assets import document_asset_dir


def _safe_remove_tree(path: Path, root: Path) -> None:
    """Remove a known generated directory only when it is inside its storage root."""
    try:
        resolved = path.resolve()
        resolved.relative_to(root.resolve())
    except (OSError, ValueError):
        raise ValueError(f"Refusing to remove a path outside managed storage: {path}")
    if resolved.exists():
        shutil.rmtree(resolved)


def clear_user_content(username: str, include_models: bool = False) -> dict[str, int]:
    """Clear documents, tasks, memories, runs, and optional model settings for one user."""
    user = fetch_one("SELECT id FROM users WHERE username = ?", (username,))
    if not user:
        raise ValueError(f"Unknown user: {username}")
    user_id = int(user["id"])
    with get_connection() as conn:
        document_ids = [int(row["id"]) for row in conn.execute("SELECT id FROM documents WHERE user_id = ?", (user_id,))]
        counts = {
            "documents": len(document_ids),
            "todos": int(conn.execute("SELECT COUNT(*) FROM todos WHERE user_id = ?", (user_id,)).fetchone()[0]),
            "memories": int(conn.execute("SELECT COUNT(*) FROM memory_items WHERE user_id = ?", (user_id,)).fetchone()[0]),
            "model_configs": int(conn.execute("SELECT COUNT(*) FROM user_model_configs WHERE user_id = ?", (user_id,)).fetchone()[0]),
        }
        if document_ids:
            marks = ",".join("?" for _ in document_ids)
            for table in ("document_questions", "document_mindmaps", "document_highlights", "document_chunks"):
                conn.execute(f"DELETE FROM {table} WHERE document_id IN ({marks})", document_ids)
        conn.execute("DELETE FROM documents WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM todo_subtasks WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM todos WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM memory_items WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM agent_runs WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM library_folders WHERE user_id = ?", (user_id,))
        if include_models:
            conn.execute("DELETE FROM user_model_configs WHERE user_id = ?", (user_id,))

    for document_id in document_ids:
        _safe_remove_tree(document_asset_dir(document_id), STORAGE_DIR / "document_assets")
    _safe_remove_tree(UPLOAD_DIR / str(user_id), UPLOAD_DIR)
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description="Clear a user's private NJU-SZ Agent Hub content.")
    parser.add_argument("--username", required=True)
    parser.add_argument("--include-models", action="store_true", help="Also remove saved API configurations.")
    parser.add_argument("--yes", action="store_true", help="Required acknowledgement for this destructive operation.")
    args = parser.parse_args()
    if not args.yes:
        raise SystemExit("Pass --yes after checking the username; the account itself will be kept.")
    counts = clear_user_content(args.username, include_models=args.include_models)
    print(f"Cleared {args.username}: {counts}")


if __name__ == "__main__":
    main()
