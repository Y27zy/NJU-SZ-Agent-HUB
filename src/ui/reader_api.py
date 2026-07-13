from __future__ import annotations

import hashlib
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from mimetypes import guess_type
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from src.agent.reading_jobs import (
    cancel_reading_job,
    discard_reading_job,
    get_reading_job,
    start_canvas_job,
    start_reading_job,
)
from src.auth.auth_service import activate_model_config
from src.config import get_db_path
from src.rag.document_assets import document_asset_dir
from src.rag.simple_vector_store import get_library_document
from src.modules.library_agent import (
    add_canvas_note,
    delete_canvas_node,
    delete_highlight,
    list_document_mindmaps,
    list_document_questions,
    list_highlights,
    toggle_highlight_anchor,
    update_canvas_node,
)


_server: ThreadingHTTPServer | None = None
_server_lock = threading.Lock()


def _token() -> str:
    seed = f"nju-reader:{get_db_path().resolve()}".encode("utf-8")
    return hashlib.sha256(seed).hexdigest()


def _markdown_html(content: str) -> str:
    # Imported lazily to avoid a module cycle during component registration.
    from src.ui.library_components import _markdown_with_math

    return _markdown_with_math(content or "")


def _nodes(user_id: int, document_id: int) -> list[dict]:
    nodes: list[dict] = []
    titles = {
        "explain": "解释这一步",
        "example": "举一个例子",
        "solve": "提问与解题",
        "variable": "变量含义",
        "why": "为什么",
        "question": "自定义提问",
        "paper_summary": "5 分钟速读",
        "note": "阅读笔记",
    }
    for item in list_document_questions(user_id, document_id):
        content = item.get("answer") or ""
        nodes.append(
            {
                "id": item["id"],
                "type": "question",
                "title": titles.get(item.get("action_type"), "阅读问答"),
                "content": content,
                "html": _markdown_html(content),
                "selectedText": item.get("selected_text") or "",
                "anchorStart": item.get("anchor_start"),
                "anchorEnd": item.get("anchor_end"),
                "parentQuestionId": item.get("parent_question_id"),
                "x": int(item.get("canvas_x") or 28),
                "y": int(item.get("canvas_y") or 72),
                "width": int(item.get("canvas_width") or 520),
                "height": int(item.get("canvas_height") or 520),
            }
        )
    for item in list_document_mindmaps(user_id, document_id):
        content = item.get("content") or ""
        nodes.append(
            {
                "id": item["id"],
                "type": "mindmap",
                "title": "思维导图",
                "content": content,
                "html": _markdown_html(content),
                "selectedText": "",
                "x": int(item.get("canvas_x") or 48),
                "y": int(item.get("canvas_y") or 96),
                "width": int(item.get("canvas_width") or 620),
                "height": int(item.get("canvas_height") or 520),
            }
        )
    return nodes


def _highlights(user_id: int, document_id: int) -> list[dict]:
    return [dict(item) for item in list_highlights(user_id, document_id)]


def _state(user_id: int, document_id: int) -> dict:
    return {
        "nodes": _nodes(user_id, document_id),
        "highlights": _highlights(user_id, document_id),
    }


class ReaderApiHandler(BaseHTTPRequestHandler):
    server_version = "NJUReaderAPI/1.0"

    def log_message(self, _format: str, *args) -> None:
        return

    def _cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Reader-Token")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PATCH, DELETE, OPTIONS")

    def _json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self._cors()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self) -> bool:
        if self.headers.get("X-Reader-Token") == _token():
            return True
        self._json(403, {"ok": False, "error": "Reader API token 无效。"})
        return False

    def _asset_authorized(self, query: dict[str, list[str]]) -> bool:
        return query.get("token", [""])[0] == _token()

    def _asset(self, document_id: int, filename: str, user_id: int) -> None:
        document = get_library_document(user_id, document_id)
        if not document:
            self._json(404, {"ok": False, "error": "资料不存在或无权访问。"})
            return
        root = document_asset_dir(document_id).resolve()
        candidate = (root / Path(filename).name).resolve()
        if not candidate.is_file() or not candidate.is_relative_to(root):
            self._json(404, {"ok": False, "error": "图片资源不存在。"})
            return
        body = candidate.read_bytes()
        self.send_response(200)
        self._cors()
        self.send_header("Content-Type", guess_type(candidate.name)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "private, max-age=3600")
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            self._json(200, {"ok": True})
            return
        query = parse_qs(parsed.query)
        if parsed.path.startswith("/assets/"):
            if not self._asset_authorized(query):
                self._json(403, {"ok": False, "error": "图片资源令牌无效。"})
                return
            try:
                parts = parsed.path.strip("/").split("/")
                if len(parts) != 2 or parts[0] != "assets":
                    raise ValueError("无效的图片资源路径。")
                document_id_text = parts[1]
                filename = query.get("name", [""])[0]
                if not filename:
                    raise ValueError("缺少图片资源名称。")
                self._asset(int(document_id_text), filename, int(query.get("user_id", [0])[0]))
            except (TypeError, ValueError):
                self._json(400, {"ok": False, "error": "无效的图片资源路径。"})
            return
        if not self._authorized():
            return
        try:
            user_id = int(query.get("user_id", [0])[0])
            document_id = int(query.get("document_id", [0])[0])
            if parsed.path == "/state":
                self._json(200, {"ok": True, **_state(user_id, document_id)})
                return
            if parsed.path.startswith("/jobs/"):
                job_id = parsed.path.rsplit("/", 1)[-1]
                job = get_reading_job(job_id, user_id)
                if not job:
                    self._json(404, {"ok": False, "error": "任务不存在或已结束。"})
                    return
                payload = {"ok": True, "job": job}
                if job["status"] in {"completed", "cancelled", "failed"}:
                    payload.update(_state(user_id, document_id))
                    discard_reading_job(job_id, user_id)
                self._json(200, payload)
                return
            self._json(404, {"ok": False, "error": "未知 Reader API 路径。"})
        except Exception as exc:
            self._json(400, {"ok": False, "error": str(exc)})

    def do_POST(self) -> None:
        if not self._authorized():
            return
        parsed = urlparse(self.path)
        try:
            body = self._body()
            user_id = int(body.get("user_id") or 0)
            document_id = int(body.get("document_id") or 0)
            if parsed.path == "/highlights/toggle":
                added, highlight_id = toggle_highlight_anchor(
                    user_id,
                    document_id,
                    str(body.get("selected_text") or ""),
                    int(body.get("anchor_start") or 0),
                    int(body.get("anchor_end") or 0),
                    str(body.get("context_prefix") or ""),
                    str(body.get("context_suffix") or ""),
                )
                self._json(
                    200,
                    {
                        "ok": True,
                        "added": added,
                        "id": highlight_id,
                        "highlights": _highlights(user_id, document_id),
                    },
                )
                return
            if parsed.path == "/jobs":
                nonce = int(body.get("nonce") or 0)
                kind = str(body.get("kind") or "selection")
                if kind in {"mindmap", "paper_summary"}:
                    job_id = start_canvas_job(
                        user_id,
                        document_id,
                        nonce,
                        kind,
                        source_text=str(body.get("source_text") or ""),
                    )
                else:
                    job_id = start_reading_job(
                        user_id,
                        document_id,
                        str(body.get("selected_text") or ""),
                        str(body.get("action") or "question"),
                        str(body.get("context_mode") or "section"),
                        str(body.get("custom_question") or ""),
                        nonce,
                        anchor_start=body.get("anchor_start"),
                        anchor_end=body.get("anchor_end"),
                        parent_question_id=body.get("parent_question_id"),
                        learning_prompt=str(body.get("learning_prompt") or ""),
                    )
                self._json(202, {"ok": True, "job_id": job_id})
                return
            if parsed.path == "/notes":
                content = str(body.get("content") or "").strip()
                if not content:
                    raise ValueError("笔记内容不能为空。")
                node_id = add_canvas_note(user_id, document_id, "阅读笔记", content, "note")
                self._json(201, {"ok": True, "id": node_id, **_state(user_id, document_id)})
                return
            if parsed.path == "/models/activate":
                activate_model_config(user_id, int(body.get("model_id") or 0))
                self._json(200, {"ok": True})
                return
            self._json(404, {"ok": False, "error": "未知 Reader API 路径。"})
        except Exception as exc:
            self._json(400, {"ok": False, "error": str(exc)})

    def do_PATCH(self) -> None:
        if not self._authorized():
            return
        parsed = urlparse(self.path)
        try:
            parts = parsed.path.strip("/").split("/")
            if len(parts) != 3 or parts[0] != "nodes":
                raise ValueError("无效的画布节点路径。")
            node_type, node_id = parts[1], int(parts[2])
            if node_type not in {"question", "mindmap"}:
                raise ValueError("无效的画布节点类型。")
            body = self._body()
            update_canvas_node(
                int(body.get("user_id") or 0),
                node_type,
                node_id,
                content=body.get("content"),
                x=body.get("x"),
                y=body.get("y"),
                width=body.get("width"),
                height=body.get("height"),
            )
            self._json(200, {"ok": True})
        except Exception as exc:
            self._json(400, {"ok": False, "error": str(exc)})

    def do_DELETE(self) -> None:
        if not self._authorized():
            return
        parsed = urlparse(self.path)
        try:
            body = self._body()
            user_id = int(body.get("user_id") or 0)
            if parsed.path.startswith("/jobs/"):
                job_id = parsed.path.rsplit("/", 1)[-1]
                cancel_reading_job(job_id, user_id)
                self._json(200, {"ok": True})
                return
            parts = parsed.path.strip("/").split("/")
            if len(parts) == 2 and parts[0] == "highlights":
                delete_highlight(user_id, int(parts[1]))
                self._json(200, {"ok": True})
                return
            if len(parts) == 3 and parts[0] == "nodes" and parts[1] in {"question", "mindmap"}:
                delete_canvas_node(user_id, parts[1], int(parts[2]))
                self._json(200, {"ok": True})
                return
            self._json(404, {"ok": False, "error": "未知 Reader API 路径。"})
        except Exception as exc:
            self._json(400, {"ok": False, "error": str(exc)})


def ensure_reader_api_server() -> dict[str, str]:
    """Start one daemon API for smooth reader interactions in the local demo."""
    global _server
    port = int(os.getenv("READER_API_PORT", "8768"))
    with _server_lock:
        if _server is None:
            try:
                _server = ThreadingHTTPServer(("127.0.0.1", port), ReaderApiHandler)
                threading.Thread(target=_server.serve_forever, name="reader-api", daemon=True).start()
            except OSError:
                # Streamlit hot reload can preserve the previous daemon instance.
                _server = None
    return {"base_url": f"http://127.0.0.1:{port}", "token": _token()}
