import threading
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field

from src.modules.library_agent import ask_about_selection


@dataclass
class ReadingJob:
    id: str
    user_id: int
    document_id: int
    action_nonce: int
    status: str = "pending"
    error: str = ""
    kind: str = "selection"
    result: dict | None = None
    cancel_event: threading.Event = field(default_factory=threading.Event)
    future: Future | None = None


_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="reading-agent")
_jobs: dict[str, ReadingJob] = {}
_lock = threading.Lock()


def start_reading_job(
    user_id: int,
    document_id: int,
    selected_text: str,
    action_type: str,
    context_mode: str,
    custom_question: str,
    action_nonce: int,
    *,
    anchor_start: int | None = None,
    anchor_end: int | None = None,
    parent_question_id: int | None = None,
    learning_prompt: str = "",
) -> str:
    job = ReadingJob(uuid.uuid4().hex, user_id, document_id, action_nonce)

    def worker() -> None:
        try:
            result = ask_about_selection(
                user_id,
                document_id,
                selected_text,
                action_type,
                context_mode,
                custom_question,
                cancel_check=job.cancel_event.is_set,
                anchor_start=anchor_start,
                anchor_end=anchor_end,
                parent_question_id=parent_question_id,
                learning_prompt=learning_prompt,
            )
            with _lock:
                job.result = result
                job.status = "cancelled" if job.cancel_event.is_set() else "completed"
        except Exception as exc:
            with _lock:
                job.status = "cancelled" if job.cancel_event.is_set() else "failed"
                job.error = "" if job.cancel_event.is_set() else str(exc)

    with _lock:
        _jobs[job.id] = job
        job.future = _executor.submit(worker)
    return job.id


def get_reading_job(job_id: str, user_id: int) -> dict | None:
    with _lock:
        job = _jobs.get(job_id)
        if not job or job.user_id != user_id:
            return None
        return {
            "id": job.id,
            "status": job.status,
            "error": job.error,
            "action_nonce": job.action_nonce,
            "kind": job.kind,
            "result": job.result,
        }


def start_canvas_job(
    user_id: int,
    document_id: int,
    action_nonce: int,
    kind: str,
    source_text: str = "",
) -> str:
    """Run document-wide canvas tools without blocking the reader UI."""
    job = ReadingJob(uuid.uuid4().hex, user_id, document_id, action_nonce, kind=kind)

    def worker() -> None:
        try:
            if kind == "mindmap":
                from src.modules.library_agent import generate_mindmap

                content = generate_mindmap(
                    user_id,
                    document_id,
                    cancel_check=job.cancel_event.is_set,
                    source_text=source_text,
                )
                result = {"content": content}
            elif kind == "paper_summary":
                from src.modules.library_agent import add_canvas_note
                from src.modules.paper_agent import summarize_paper

                content = summarize_paper(user_id, document_id)
                if job.cancel_event.is_set():
                    result = {"content": content}
                else:
                    node_id = add_canvas_note(user_id, document_id, "5 分钟速读", content, "paper_summary")
                    result = {"id": node_id, "content": content}
            else:
                raise ValueError(f"不支持的画布任务：{kind}")
            with _lock:
                job.result = result
                job.status = "cancelled" if job.cancel_event.is_set() else "completed"
        except Exception as exc:
            with _lock:
                job.status = "cancelled" if job.cancel_event.is_set() else "failed"
                job.error = "" if job.cancel_event.is_set() else str(exc)

    with _lock:
        _jobs[job.id] = job
        job.future = _executor.submit(worker)
    return job.id


def cancel_reading_job(job_id: str, user_id: int) -> bool:
    with _lock:
        job = _jobs.get(job_id)
        if not job or job.user_id != user_id:
            return False
        job.cancel_event.set()
        job.status = "cancelled"
        if job.future:
            job.future.cancel()
        return True


def discard_reading_job(job_id: str, user_id: int) -> None:
    with _lock:
        job = _jobs.get(job_id)
        if job and job.user_id == user_id and job.status in {"completed", "cancelled", "failed"}:
            _jobs.pop(job_id, None)
