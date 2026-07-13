"""Import curated course PDFs as admin-managed global library documents."""

from __future__ import annotations

import argparse
import hashlib
import shutil
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config import UPLOAD_DIR
from src.database import fetch_all, fetch_one, init_db
from src.rag.document_processor import process_document, reprocess_document


DEFAULT_COURSE_FILENAMES = (
    "离散数学结构 翻译版 ( etc.) (Z-Library).pdf",
    "微积分I（第三版）.pdf",
    "微积分II（第三版）.pdf",
    "线性代数讲义.pdf",
    "普通物理学 上 第7版.pdf",
    "普通物理学  下册  第7版.pdf",
)


def _copy_into_uploads(source: Path, user_id: int) -> Path:
    """Copy one source PDF into managed storage using a stable collision-safe name."""
    digest = hashlib.sha256(source.read_bytes()).hexdigest()[:12]
    destination_dir = UPLOAD_DIR / str(user_id) / "course"
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / f"{source.stem}_{digest}{source.suffix.lower()}"
    if not destination.exists():
        shutil.copy2(source, destination)
    return destination


def _existing_global_titles(user_id: int) -> set[str]:
    rows = fetch_all(
        """
        SELECT title FROM documents
        WHERE user_id = ? AND is_global = 1 AND library_scope = 'course' AND processing_status = 'ready'
        """,
        (user_id,),
    )
    return {str(row["title"]) for row in rows}


def _existing_global_document(user_id: int, title: str) -> dict | None:
    """Find an earlier import attempt so network retries continue in place."""
    row = fetch_one(
        """
        SELECT id, title, file_path, processing_status
        FROM documents
        WHERE user_id = ? AND title = ? AND is_global = 1 AND library_scope = 'course'
        ORDER BY id DESC LIMIT 1
        """,
        (user_id, title),
    )
    return dict(row) if row else None


def main() -> None:
    parser = argparse.ArgumentParser(description="Import and process admin-managed course PDFs.")
    parser.add_argument("--username", default="admin")
    parser.add_argument("--source-dir", type=Path, default=Path.home() / "Downloads")
    parser.add_argument("--source", type=Path, action="append", help="Import an explicit PDF; may be repeated.")
    parser.add_argument("--skip-existing", action="store_true", help="Skip a document whose title already exists globally.")
    parser.add_argument("--document-retries", type=int, default=2, help="Attempts per document after a transient failure.")
    parser.add_argument("--background", action="store_true", help="Launch the import worker in the background and return immediately.")
    parser.add_argument("--log-dir", type=Path, default=ROOT / "storage" / "logs")
    args = parser.parse_args()

    if args.background:
        args.log_dir.mkdir(parents=True, exist_ok=True)
        stdout_path = args.log_dir / "admin-course-import.log"
        stderr_path = args.log_dir / "admin-course-import.error.log"
        command = [sys.executable, str(Path(__file__).resolve()), "--username", args.username, "--source-dir", str(args.source_dir)]
        if args.skip_existing:
            command.append("--skip-existing")
        command.extend(["--document-retries", str(args.document_retries)])
        for source in args.source or []:
            command.extend(["--source", str(source)])
        with stdout_path.open("ab") as stdout, stderr_path.open("ab") as stderr:
            process = subprocess.Popen(
                command,
                cwd=ROOT,
                stdin=subprocess.DEVNULL,
                stdout=stdout,
                stderr=stderr,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        print(f"Background import started: pid={process.pid}")
        print(f"Log: {stdout_path}")
        return

    init_db()
    admin = fetch_one("SELECT id, is_admin FROM users WHERE username = ?", (args.username,))
    if not admin or not bool(admin["is_admin"]):
        raise SystemExit(f"{args.username} is not an administrator account.")
    user_id = int(admin["id"])
    sources = args.source or [args.source_dir / filename for filename in DEFAULT_COURSE_FILENAMES]
    missing = [source for source in sources if not source.is_file()]
    if missing:
        raise SystemExit("Missing source PDFs:\n" + "\n".join(str(path) for path in missing))

    existing = _existing_global_titles(user_id)
    failures: list[str] = []
    for source in sources:
        title = source.name
        if args.skip_existing and title in existing:
            print(f"Skip existing: {title}", flush=True)
            continue
        stored = _copy_into_uploads(source, user_id)
        print(f"\nImporting: {title}", flush=True)

        def progress(current: int, total: int, message: str) -> None:
            print(f"  {current}/{total} {message}", flush=True)

        attempts = max(1, args.document_retries)
        for attempt in range(1, attempts + 1):
            existing_document = _existing_global_document(user_id, title)
            try:
                if existing_document:
                    document_id = reprocess_document(user_id, int(existing_document["id"]), progress=progress)
                else:
                    document_id = process_document(
                        user_id,
                        stored,
                        title,
                        "course",
                        progress=progress,
                        library_scope="course",
                        is_global=True,
                    )
                print(f"  ready: document_id={document_id}", flush=True)
                break
            except Exception as exc:
                if attempt == attempts:
                    failures.append(f"{title}: {exc}")
                    print(f"  failed after {attempts} attempts: {exc}", flush=True)
                    break
                delay = 10 * attempt
                print(f"  attempt {attempt}/{attempts} failed: {exc}; retrying in {delay}s", flush=True)
                time.sleep(delay)
    if failures:
        print("\nCompleted with failures:\n" + "\n".join(failures), flush=True)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
