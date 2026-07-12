"""Background jobs for cancellable document reprocessing."""

from __future__ import annotations

import threading
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field

from src.agent.document_processing_agent import DocumentProcessingCancelled
from src.rag.document_processor import reprocess_document


@dataclass
class DocumentJob:
    id: str
    user_id: int
    document_id: int
    status: str = "pending"
    error: str = ""
    cancel_event: threading.Event = field(default_factory=threading.Event)
    future: Future | None = None


_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="document-agent")
_jobs: dict[str, DocumentJob] = {}
_lock = threading.Lock()


def start_reprocess_job(user_id: int, document_id: int) -> str:
    """Start a reprocessing job and return its short-lived session identifier."""
    job = DocumentJob(uuid.uuid4().hex, user_id, document_id)

    def worker() -> None:
        try:
            with _lock:
                job.status = "running"
            reprocess_document(user_id, document_id, cancel_check=job.cancel_event.is_set)
            with _lock:
                job.status = "cancelled" if job.cancel_event.is_set() else "completed"
        except DocumentProcessingCancelled:
            with _lock:
                job.status = "cancelled"
        except Exception as exc:
            with _lock:
                job.status = "cancelled" if job.cancel_event.is_set() else "failed"
                job.error = "" if job.cancel_event.is_set() else str(exc)

    with _lock:
        _jobs[job.id] = job
        job.future = _executor.submit(worker)
    return job.id


def get_document_job(job_id: str, user_id: int) -> dict | None:
    """Read the current status of a reprocessing job owned by the user."""
    with _lock:
        job = _jobs.get(job_id)
        if not job or job.user_id != user_id:
            return None
        return {"id": job.id, "document_id": job.document_id, "status": job.status, "error": job.error}


def cancel_document_job(job_id: str, user_id: int) -> bool:
    """Request cancellation; work already inside an LLM call stops immediately afterward."""
    with _lock:
        job = _jobs.get(job_id)
        if not job or job.user_id != user_id or job.status not in {"pending", "running"}:
            return False
        job.cancel_event.set()
        job.status = "cancelling"
        return True


def discard_document_job(job_id: str, user_id: int) -> None:
    """Drop a finished job from the in-memory registry."""
    with _lock:
        job = _jobs.get(job_id)
        if job and job.user_id == user_id and job.status in {"completed", "cancelled", "failed"}:
            _jobs.pop(job_id, None)
