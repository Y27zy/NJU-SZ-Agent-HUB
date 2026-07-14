"""Persistent, resumable background jobs for document processing."""

from __future__ import annotations

import sqlite3
import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timedelta

from src.agent.document_processing_agent import DocumentProcessingCancelled
from src.database import execute, fetch_all, fetch_one, get_connection, init_db, now_iso
from src.llm.gateway import _is_transient_model_error
from src.llm.providers import LLMProviderError
from src.rag.document_processor import reprocess_document


ACTIVE_STATUSES = ("queued", "running", "retry_wait", "cancelling")
MAX_WORKERS = 2
POLL_SECONDS = 1.0
STALE_HEARTBEAT_SECONDS = 75

_executor = ThreadPoolExecutor(max_workers=MAX_WORKERS, thread_name_prefix="document-agent")
_active_futures: dict[str, Future] = {}
_cancel_events: dict[str, threading.Event] = {}
_runtime_lock = threading.Lock()
_wake_event = threading.Event()
_supervisor_started = False


def _row_dict(row) -> dict | None:
    return dict(row) if row else None


def _retry_delay(attempt_count: int) -> int:
    """Use bounded exponential backoff while retaining indefinite recovery."""
    return min(300, 5 * (2 ** min(max(attempt_count - 1, 0), 6)))


def _error_kind(exc: Exception) -> str:
    cause = exc.__cause__
    return type(cause or exc).__name__


def _is_retryable_error(exc: Exception) -> bool:
    if isinstance(exc, LLMProviderError):
        return _is_transient_model_error(exc)
    if isinstance(exc, PermissionError):
        return True
    if isinstance(exc, OSError) and getattr(exc, "winerror", None) in {5, 32, 33}:
        return True
    message = str(exc).lower()
    return any(
        marker in message
        for marker in (
            "timeout",
            "timed out",
            "connection reset",
            "connection aborted",
            "temporarily unavailable",
            "http 429",
            "http 500",
            "http 502",
            "http 503",
            "http 504",
            "拒绝访问",
        )
    )


def _job_payload(row: dict | None) -> dict | None:
    if not row:
        return None
    payload = dict(row)
    payload["progress_message"] = str(payload.get("progress_message") or "")
    payload["error"] = str(payload.get("error") or "")
    return payload


def ensure_document_job_worker() -> None:
    """Start one lightweight supervisor; jobs themselves remain database-backed."""
    global _supervisor_started
    with _runtime_lock:
        if _supervisor_started:
            return
        init_db()
        _supervisor_started = True
        threading.Thread(target=_supervisor_loop, name="document-job-supervisor", daemon=True).start()


def enqueue_document_job(user_id: int, document_id: int, job_type: str = "reprocess") -> str:
    """Create one durable job, returning the existing active job on duplicate clicks."""
    ensure_document_job_worker()
    placeholders = ",".join("?" for _ in ACTIVE_STATUSES)
    existing = fetch_one(
        f"""
        SELECT * FROM document_jobs
        WHERE user_id = ? AND document_id = ? AND status IN ({placeholders})
        ORDER BY created_at DESC LIMIT 1
        """,
        (user_id, document_id, *ACTIVE_STATUSES),
    )
    if existing:
        return str(existing["id"])

    job_id = uuid.uuid4().hex
    created_at = now_iso()
    try:
        execute(
            """
            INSERT INTO document_jobs
            (id, user_id, document_id, job_type, status, created_at, updated_at, next_retry_at)
            VALUES (?, ?, ?, ?, 'queued', ?, ?, ?)
            """,
            (job_id, user_id, document_id, job_type, created_at, created_at, created_at),
        )
    except sqlite3.IntegrityError:
        existing = fetch_one(
            f"""
            SELECT id FROM document_jobs
            WHERE document_id = ? AND status IN ({placeholders})
            ORDER BY created_at DESC LIMIT 1
            """,
            (document_id, *ACTIVE_STATUSES),
        )
        if not existing:
            raise
        job_id = str(existing["id"])
    execute(
        """
        UPDATE documents
        SET processing_status = CASE
                WHEN COALESCE(processed_markdown, '') = '' THEN 'processing'
                ELSE processing_status
            END,
            updated_at = ?
        WHERE id = ? AND user_id = ?
        """,
        (created_at, document_id, user_id),
    )
    _wake_event.set()
    return job_id


def start_reprocess_job(user_id: int, document_id: int) -> str:
    return enqueue_document_job(user_id, document_id, "reprocess")


def start_new_document_job(user_id: int, document_id: int) -> str:
    return enqueue_document_job(user_id, document_id, "build")


def get_document_job(job_id: str, user_id: int) -> dict | None:
    ensure_document_job_worker()
    return _job_payload(_row_dict(fetch_one("SELECT * FROM document_jobs WHERE id = ? AND user_id = ?", (job_id, user_id))))


def list_document_jobs(user_id: int, active_only: bool = False) -> list[dict]:
    ensure_document_job_worker()
    if active_only:
        placeholders = ",".join("?" for _ in ACTIVE_STATUSES)
        rows = fetch_all(
            f"SELECT * FROM document_jobs WHERE user_id = ? AND status IN ({placeholders}) ORDER BY created_at DESC",
            (user_id, *ACTIVE_STATUSES),
        )
    else:
        rows = fetch_all("SELECT * FROM document_jobs WHERE user_id = ? ORDER BY created_at DESC", (user_id,))
    return [_job_payload(dict(row)) for row in rows]


def get_active_document_jobs(user_id: int) -> dict[int, dict]:
    return {int(job["document_id"]): job for job in list_document_jobs(user_id, active_only=True)}


def cancel_document_job(job_id: str, user_id: int) -> bool:
    job = fetch_one("SELECT * FROM document_jobs WHERE id = ? AND user_id = ?", (job_id, user_id))
    if not job or job["status"] not in ACTIVE_STATUSES:
        return False
    immediate = job["status"] in {"queued", "retry_wait"}
    execute(
        """
        UPDATE document_jobs
        SET cancel_requested = 1, status = ?, updated_at = ?, completed_at = ?
        WHERE id = ? AND user_id = ?
        """,
        (
            "cancelled" if immediate else "cancelling",
            now_iso(),
            now_iso() if immediate else None,
            job_id,
            user_id,
        ),
    )
    if immediate:
        execute(
            """
            UPDATE documents
            SET processing_status = CASE
                    WHEN COALESCE(processed_markdown, '') = '' THEN 'error'
                    ELSE 'ready'
                END,
                processing_error = CASE
                    WHEN COALESCE(processed_markdown, '') = '' THEN '用户已取消后台整理，缓存已保留。'
                    ELSE NULL
                END,
                updated_at = ?
            WHERE id = ? AND user_id = ?
            """,
            (now_iso(), int(job["document_id"]), user_id),
        )
    with _runtime_lock:
        event = _cancel_events.get(job_id)
        if event:
            event.set()
    _wake_event.set()
    return True


def discard_document_job(job_id: str, user_id: int) -> None:
    """Finished jobs are intentionally retained as a diagnostic history."""


def _cancel_requested(job_id: str, local_event: threading.Event) -> bool:
    if local_event.is_set():
        return True
    row = fetch_one("SELECT cancel_requested FROM document_jobs WHERE id = ?", (job_id,))
    return not row or bool(row["cancel_requested"])


def _heartbeat_loop(job_id: str, stop: threading.Event) -> None:
    while not stop.wait(10):
        execute(
            "UPDATE document_jobs SET heartbeat_at = ?, updated_at = ? WHERE id = ? AND status IN ('running', 'cancelling')",
            (now_iso(), now_iso(), job_id),
        )


def _run_job(job_id: str) -> None:
    now = now_iso()
    with get_connection() as conn:
        cursor = conn.execute(
            """
            UPDATE document_jobs
            SET status = 'running', heartbeat_at = ?, updated_at = ?, next_retry_at = NULL,
                progress_message = '正在从最近断点继续', error = NULL, error_kind = NULL
            WHERE id = ? AND cancel_requested = 0
              AND (status = 'queued' OR (status = 'retry_wait' AND COALESCE(next_retry_at, '') <= ?))
            """,
            (now, now, job_id, now),
        )
        if cursor.rowcount != 1:
            return
        job = conn.execute("SELECT * FROM document_jobs WHERE id = ?", (job_id,)).fetchone()
    if not job:
        return

    local_cancel = threading.Event()
    heartbeat_stop = threading.Event()
    with _runtime_lock:
        _cancel_events[job_id] = local_cancel
    heartbeat = threading.Thread(target=_heartbeat_loop, args=(job_id, heartbeat_stop), daemon=True)
    heartbeat.start()

    def progress(current: int, total: int, message: str) -> None:
        timestamp = now_iso()
        execute(
            """
            UPDATE document_jobs
            SET progress_current = ?, progress_total = ?, progress_message = ?,
                heartbeat_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (current, total, message[:500], timestamp, timestamp, job_id),
        )

    try:
        reprocess_document(
            int(job["user_id"]),
            int(job["document_id"]),
            progress=progress,
            cancel_check=lambda: _cancel_requested(job_id, local_cancel),
        )
        timestamp = now_iso()
        execute(
            """
            UPDATE document_jobs
            SET status = 'completed', progress_message = '处理完成', heartbeat_at = ?,
                updated_at = ?, completed_at = ?, error = NULL, error_kind = NULL
            WHERE id = ?
            """,
            (timestamp, timestamp, timestamp, job_id),
        )
    except DocumentProcessingCancelled:
        timestamp = now_iso()
        execute(
            """
            UPDATE document_jobs
            SET status = 'cancelled', progress_message = '已取消', updated_at = ?, completed_at = ?
            WHERE id = ?
            """,
            (timestamp, timestamp, job_id),
        )
    except Exception as exc:
        current = fetch_one("SELECT attempt_count, cancel_requested FROM document_jobs WHERE id = ?", (job_id,))
        if current and current["cancel_requested"]:
            timestamp = now_iso()
            execute(
                "UPDATE document_jobs SET status = 'cancelled', updated_at = ?, completed_at = ? WHERE id = ?",
                (timestamp, timestamp, job_id),
            )
        elif _is_retryable_error(exc):
            attempts = int(current["attempt_count"] if current else 0) + 1
            delay = _retry_delay(attempts)
            retry_at = (datetime.now() + timedelta(seconds=delay)).isoformat(timespec="seconds")
            timestamp = now_iso()
            execute(
                """
                UPDATE document_jobs
                SET status = 'retry_wait', attempt_count = ?, next_retry_at = ?,
                    progress_message = ?, error = ?, error_kind = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    attempts,
                    retry_at,
                    f"连接中断，{delay} 秒后自动继续",
                    str(exc)[:1000],
                    _error_kind(exc),
                    timestamp,
                    job_id,
                ),
            )
            execute(
                """
                UPDATE documents
                SET processing_status = CASE
                        WHEN COALESCE(processed_markdown, '') = '' THEN 'processing'
                        ELSE 'ready'
                    END,
                    processing_error = ?, updated_at = ?
                WHERE id = ? AND user_id = ?
                """,
                (str(exc)[:1000], timestamp, int(job["document_id"]), int(job["user_id"])),
            )
        else:
            timestamp = now_iso()
            execute(
                """
                UPDATE document_jobs
                SET status = 'failed', attempt_count = attempt_count + 1,
                    progress_message = '处理暂停，需要检查错误', error = ?, error_kind = ?,
                    updated_at = ?, completed_at = ?
                WHERE id = ?
                """,
                (str(exc)[:1000], _error_kind(exc), timestamp, timestamp, job_id),
            )
    finally:
        heartbeat_stop.set()
        with _runtime_lock:
            _cancel_events.pop(job_id, None)
        _wake_event.set()


def _recover_stale_jobs() -> None:
    cutoff = (datetime.now() - timedelta(seconds=STALE_HEARTBEAT_SECONDS)).isoformat(timespec="seconds")
    timestamp = now_iso()
    execute(
        """
        UPDATE document_jobs
        SET status = CASE WHEN cancel_requested = 1 THEN 'cancelled' ELSE 'queued' END,
            next_retry_at = ?, updated_at = ?, completed_at = CASE WHEN cancel_requested = 1 THEN ? ELSE completed_at END
        WHERE status IN ('running', 'cancelling')
          AND COALESCE(heartbeat_at, updated_at) < ?
        """,
        (timestamp, timestamp, timestamp, cutoff),
    )


def _supervisor_loop() -> None:
    last_recovery = 0.0
    while True:
        try:
            if time.monotonic() - last_recovery >= 15:
                _recover_stale_jobs()
                last_recovery = time.monotonic()
            with _runtime_lock:
                finished = [job_id for job_id, future in _active_futures.items() if future.done()]
                for job_id in finished:
                    _active_futures.pop(job_id, None)
                available = MAX_WORKERS - len(_active_futures)
            if available > 0:
                now = now_iso()
                rows = fetch_all(
                    """
                    SELECT id FROM document_jobs
                    WHERE cancel_requested = 0
                      AND (status = 'queued' OR (status = 'retry_wait' AND COALESCE(next_retry_at, '') <= ?))
                    ORDER BY created_at ASC LIMIT ?
                    """,
                    (now, available),
                )
                with _runtime_lock:
                    for row in rows:
                        job_id = str(row["id"])
                        if job_id not in _active_futures:
                            _active_futures[job_id] = _executor.submit(_run_job, job_id)
        except Exception:
            # Keep the supervisor alive; a later iteration can recover SQLite or
            # transient filesystem failures without losing the persisted queue.
            pass
        _wake_event.wait(POLL_SECONDS)
        _wake_event.clear()
