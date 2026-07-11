import sqlite3
from contextlib import contextmanager
from datetime import datetime
from typing import Iterator

from src.config import ensure_runtime_dirs, get_db_path


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


@contextmanager
def get_connection() -> Iterator[sqlite3.Connection]:
    ensure_runtime_dirs()
    conn = sqlite3.connect(get_db_path())
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with get_connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS user_model_configs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                provider TEXT NOT NULL,
                api_base TEXT,
                api_key TEXT,
                model_name TEXT NOT NULL,
                is_default INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                doc_type TEXT NOT NULL,
                title TEXT NOT NULL,
                file_path TEXT,
                folder_id INTEGER,
                source_format TEXT,
                original_text TEXT,
                processed_markdown TEXT,
                processing_status TEXT NOT NULL DEFAULT 'ready',
                processing_error TEXT,
                page_count INTEGER NOT NULL DEFAULT 0,
                structure_json TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT,
                FOREIGN KEY(user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS library_folders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                parent_id INTEGER,
                created_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id),
                FOREIGN KEY(parent_id) REFERENCES library_folders(id)
            );

            CREATE TABLE IF NOT EXISTS document_chunks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                doc_type TEXT NOT NULL,
                chunk_index INTEGER NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(document_id) REFERENCES documents(id)
            );

            CREATE TABLE IF NOT EXISTS todos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                description TEXT,
                deadline TEXT,
                priority TEXT NOT NULL DEFAULT 'medium',
                status TEXT NOT NULL DEFAULT 'open',
                created_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS todo_subtasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                todo_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'open',
                created_at TEXT NOT NULL,
                FOREIGN KEY(todo_id) REFERENCES todos(id),
                FOREIGN KEY(user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS memory_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                memory_type TEXT NOT NULL,
                content TEXT NOT NULL,
                importance INTEGER NOT NULL DEFAULT 3,
                created_at TEXT NOT NULL,
                last_accessed_at TEXT,
                FOREIGN KEY(user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS document_questions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                document_id INTEGER NOT NULL,
                action_type TEXT NOT NULL,
                selected_text TEXT NOT NULL,
                context_mode TEXT NOT NULL,
                context_snapshot TEXT,
                answer TEXT NOT NULL,
                anchor_start INTEGER,
                anchor_end INTEGER,
                canvas_x INTEGER NOT NULL DEFAULT 28,
                canvas_y INTEGER NOT NULL DEFAULT 72,
                canvas_width INTEGER NOT NULL DEFAULT 520,
                canvas_height INTEGER NOT NULL DEFAULT 520,
                updated_at TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id),
                FOREIGN KEY(document_id) REFERENCES documents(id)
            );

            CREATE TABLE IF NOT EXISTS document_mindmaps (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                document_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                canvas_x INTEGER NOT NULL DEFAULT 48,
                canvas_y INTEGER NOT NULL DEFAULT 96,
                canvas_width INTEGER NOT NULL DEFAULT 520,
                canvas_height INTEGER NOT NULL DEFAULT 520,
                updated_at TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id),
                FOREIGN KEY(document_id) REFERENCES documents(id)
            );

            CREATE TABLE IF NOT EXISTS document_highlights (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                document_id INTEGER NOT NULL,
                selected_text TEXT NOT NULL,
                note TEXT,
                color TEXT NOT NULL DEFAULT 'yellow',
                created_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id),
                FOREIGN KEY(document_id) REFERENCES documents(id)
            );
            """
        )
        _migrate_documents(conn)
        _migrate_canvas_tables(conn)


def _migrate_documents(conn: sqlite3.Connection) -> None:
    """Add library columns to databases created by earlier project versions."""
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(documents)").fetchall()}
    migrations = {
        "folder_id": "ALTER TABLE documents ADD COLUMN folder_id INTEGER",
        "source_format": "ALTER TABLE documents ADD COLUMN source_format TEXT",
        "original_text": "ALTER TABLE documents ADD COLUMN original_text TEXT",
        "processed_markdown": "ALTER TABLE documents ADD COLUMN processed_markdown TEXT",
        "processing_status": "ALTER TABLE documents ADD COLUMN processing_status TEXT NOT NULL DEFAULT 'ready'",
        "processing_error": "ALTER TABLE documents ADD COLUMN processing_error TEXT",
        "page_count": "ALTER TABLE documents ADD COLUMN page_count INTEGER NOT NULL DEFAULT 0",
        "updated_at": "ALTER TABLE documents ADD COLUMN updated_at TEXT",
        "structure_json": "ALTER TABLE documents ADD COLUMN structure_json TEXT",
    }
    for column, statement in migrations.items():
        if column not in existing:
            conn.execute(statement)
    conn.execute(
        """
        UPDATE documents
        SET processed_markdown = COALESCE(
                NULLIF(processed_markdown, ''),
                (SELECT group_concat(content, char(10) || char(10))
                 FROM (SELECT content FROM document_chunks
                       WHERE document_id = documents.id ORDER BY chunk_index))
            ),
            original_text = COALESCE(NULLIF(original_text, ''), processed_markdown),
            processing_status = CASE
                WHEN processing_status IS NULL OR processing_status = '' THEN 'ready'
                ELSE processing_status
            END,
            updated_at = COALESCE(updated_at, created_at)
        WHERE processed_markdown IS NULL OR processed_markdown = ''
        """
    )


def _migrate_canvas_tables(conn: sqlite3.Connection) -> None:
    migrations = {
        "document_questions": {
            "canvas_x": "INTEGER NOT NULL DEFAULT 28",
            "canvas_y": "INTEGER NOT NULL DEFAULT 72",
            "canvas_width": "INTEGER NOT NULL DEFAULT 520",
            "canvas_height": "INTEGER NOT NULL DEFAULT 520",
            "updated_at": "TEXT",
        },
        "document_mindmaps": {
            "canvas_x": "INTEGER NOT NULL DEFAULT 48",
            "canvas_y": "INTEGER NOT NULL DEFAULT 96",
            "canvas_width": "INTEGER NOT NULL DEFAULT 520",
            "canvas_height": "INTEGER NOT NULL DEFAULT 520",
            "updated_at": "TEXT",
        },
    }
    for table, columns in migrations.items():
        existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        for column, definition in columns.items():
            if column not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def fetch_all(query: str, params: tuple = ()) -> list[sqlite3.Row]:
    with get_connection() as conn:
        return conn.execute(query, params).fetchall()


def fetch_one(query: str, params: tuple = ()) -> sqlite3.Row | None:
    with get_connection() as conn:
        return conn.execute(query, params).fetchone()


def execute(query: str, params: tuple = ()) -> int:
    with get_connection() as conn:
        cur = conn.execute(query, params)
        return int(cur.lastrowid or 0)
