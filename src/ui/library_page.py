from pathlib import Path

import streamlit as st

from src.agent.document_jobs import cancel_document_job, get_active_document_jobs, start_new_document_job, start_reprocess_job
from src.agent.reading_jobs import cancel_reading_job, discard_reading_job, get_reading_job, start_reading_job
from src.auth.auth_service import activate_model_config, get_default_model_config, is_admin, list_model_configs
from src.modules.library_agent import (
    add_canvas_note,
    create_folder,
    delete_canvas_node,
    delete_highlight,
    generate_mindmap,
    list_document_mindmaps,
    list_document_questions,
    ensure_default_folders,
    list_folders,
    list_highlights,
    toggle_highlight,
    update_canvas_node,
)
from src.modules.paper_agent import summarize_paper
from src.rag.document_assets import ensure_document_images
from src.rag.simple_vector_store import (
    create_document_record,
    delete_library_document,
    can_edit_library_document,
    get_library_document,
    get_document_chunks,
    list_library_documents,
    update_document_markdown,
    update_document_assets_markdown,
)
from src.config import UPLOAD_DIR
from src.ui.library_components import render_collection, render_library_hall, render_study_workspace
from src.ui.reader_api import ensure_reader_api_server
from src.utils.file_storage import safe_upload_path


CATEGORY_LABELS = {
    "all": "全部资料",
    "course": "课程资料",
    "paper": "论文研读",
    "other": "其他资料",
    "custom": "自定义资料库",
    "public": "南大公共资料",
    "exam": "真题与备考",
    "shared": "校园共享",
}
SHARED_LIBRARY_SCOPES = ("course", "paper", "other", "public", "exam", "shared")
ACTION_LABELS = {
    "explain": "解释这一步",
    "example": "给一个例子",
    "solve": "提问与解题",
    "variable": "变量含义",
    "why": "为什么",
    "question": "自定义提问",
    "paper_summary": "5 分钟速读",
    "note": "阅读笔记",
}


def inject_library_theme(workspace: bool = False) -> None:
    marker = "workspace-page-marker" if workspace else "library-page-marker"
    st.markdown(f'<span class="{marker}"></span>', unsafe_allow_html=True)
    st.markdown(
        """
        <style>
        .stApp:has(.library-page-marker), .stApp:has(.workspace-page-marker) { background:#fcfcfd !important; }
        .stApp:has(.library-page-marker) .block-container { max-width:var(--page-max) !important; padding:0 2.35rem 4.25rem !important; }
        .stApp.workspace-component-ready:has(.workspace-page-marker) .block-container { max-width:none !important; padding:0 !important; }
        .stApp.workspace-component-ready:has(.workspace-page-marker) [data-testid="stMainBlockContainer"] { gap:0 !important; }
        .stApp.workspace-component-ready:has(.workspace-page-marker) [data-testid="stMainBlockContainer"] > div,
        .stApp.workspace-component-ready:has(.workspace-page-marker) [data-testid="stVerticalBlock"] { gap:0 !important; }
        .stApp.workspace-component-ready:has(.workspace-page-marker) .st-key-top_nav { display:none !important; }
        .stApp:has(.library-page-marker) .st-key-top_nav { margin-bottom:0 !important; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _category_data(documents: list[dict], admin: bool) -> list[dict]:
    def count_scope(scope: str) -> int:
        direct = sum(doc.get("library_scope") == scope for doc in documents)
        if admin:
            return direct
        # Existing personal documents predate explicit library scopes. Keep their
        # previous course/paper/other filtering behavior without publishing them.
        legacy = sum(
            doc.get("library_scope", "custom") == "custom" and doc.get("doc_type") == scope
            for doc in documents
        ) if scope in {"course", "paper", "other"} else 0
        return direct + legacy

    counts = {
        "all": len(documents),
        "course": count_scope("course"),
        "paper": count_scope("paper"),
        "other": count_scope("other"),
        "custom": sum(doc.get("library_scope", "custom") == "custom" for doc in documents),
        "public": sum(doc.get("library_scope") == "public" for doc in documents),
        "exam": sum(doc.get("library_scope") == "exam" for doc in documents),
        "shared": sum(doc.get("library_scope") == "shared" for doc in documents),
    }
    visible_categories = ["all", *SHARED_LIBRARY_SCOPES] if admin else list(CATEGORY_LABELS)
    return [
        {
            "key": key,
            "label": CATEGORY_LABELS[key],
            "count": counts[key],
            "featured": key == "custom",
            "disabled": False,
            "note": "管理员维护" if key in {"public", "exam", "shared"} and admin else "",
        }
        for key in visible_categories
    ]


def _filtered_documents(documents: list[dict], category: str) -> list[dict]:
    if category == "all":
        return documents
    if category == "custom":
        return [doc for doc in documents if doc.get("library_scope", "custom") == "custom"]
    if category in {"public", "exam", "shared"}:
        return [doc for doc in documents if doc.get("library_scope") == category]
    if category in {"course", "paper", "other"}:
        return [
            doc for doc in documents
            if doc.get("library_scope") == category
            or (doc.get("library_scope", "custom") == "custom" and doc.get("doc_type") == category)
        ]
    return []


def _document_rows(
    documents: list[dict],
    user_id: int,
    admin: bool,
    jobs_by_document: dict[int, dict] | None = None,
) -> list[dict]:
    jobs_by_document = jobs_by_document or {}
    kind_labels = {"course": "课程", "paper": "论文", "other": "资料"}
    status_labels = {"ready": "可学习", "processing": "处理中", "error": "处理失败"}
    return [
        {
            "id": doc["id"],
            "title": doc["title"],
            "kind": kind_labels.get(doc["doc_type"], "资料"),
            "status": status_labels.get(doc.get("processing_status"), "可学习"),
            "pages": doc.get("page_count") or 0,
            "global": bool(doc.get("is_global")),
            "can_delete": (not bool(doc.get("is_global")) and int(doc["user_id"]) == user_id) or (admin and bool(doc.get("is_global"))),
            "can_reprocess": (not bool(doc.get("is_global")) and int(doc["user_id"]) == user_id) or (admin and bool(doc.get("is_global"))),
            "job": jobs_by_document.get(int(doc["id"])),
        }
        for doc in documents
    ]


def _save_upload(user_id: int, uploaded) -> str:
    path = safe_upload_path(user_id, "library", uploaded.name)
    path.write_bytes(uploaded.getbuffer())
    return str(path)


@st.dialog("构建新资料", width="large")
def show_document_builder(user_id: int, library_scope: str = "custom", admin: bool = False) -> None:
    if library_scope != "custom" and not admin:
        st.error("只有管理员可以向公共资料库添加资料。")
        return
    if admin:
        scope_options = list(SHARED_LIBRARY_SCOPES)
    elif library_scope in CATEGORY_LABELS and library_scope != "all":
        scope_options = [library_scope]
    else:
        scope_options = ["custom", *SHARED_LIBRARY_SCOPES]
    default_scope = library_scope if library_scope in scope_options else scope_options[0]
    target_scope = st.selectbox(
        "发布到" if admin else "资料库",
        scope_options,
        index=scope_options.index(default_scope),
        format_func=lambda value: CATEGORY_LABELS[value],
        disabled=not admin,
    )
    scope_name = CATEGORY_LABELS[target_scope]
    st.markdown(f"### 向{scope_name}构建新资料")
    st.caption("系统会提取文本；扫描页走多模态 OCR；随后恢复标题、段落、表格和 LaTeX，生成可划选原文。")
    uploaded = st.file_uploader(
        "拖入 PDF、PPTX、TXT 或 Markdown",
        type=["pdf", "pptx", "txt", "md", "markdown"],
        key="document_builder_upload",
    )
    left, right = st.columns(2)
    with left:
        doc_type = st.selectbox(
            "资料用途",
            ["course", "paper", "other"],
            index=["course", "paper", "other"].index(target_scope) if target_scope in {"course", "paper", "other"} else 2,
            format_func=lambda value: {"course": "课程学习", "paper": "论文研读", "other": "其他资料"}[value],
        )
    with right:
        folders = ensure_default_folders(user_id)
        folder_options = [None, *[folder["id"] for folder in folders]]
        folder_id = st.selectbox(
            "保存到个人文件夹" if target_scope == "custom" else "管理员文件夹",
            folder_options,
            format_func=lambda value: f"{scope_name}（根目录）" if value is None else next(folder["name"] for folder in folders if folder["id"] == value),
        )
    folder_input, folder_action = st.columns([0.78, 0.22], vertical_alignment="bottom")
    folder_name = folder_input.text_input("新建文件夹", placeholder="例如：机器学习导论")
    if folder_action.button("创建文件夹", use_container_width=True):
        if not folder_name.strip():
            st.warning("请输入文件夹名称。")
        else:
            create_folder(user_id, folder_name)
            st.rerun()
    if st.button("开始构建资料", type="primary", use_container_width=True):
        if uploaded is None:
            st.warning("请先选择一个资料文件。")
            return
        try:
            file_path = _save_upload(user_id, uploaded)
            document_id = create_document_record(
                user_id,
                doc_type,
                uploaded.name,
                file_path,
                folder_id,
                Path(file_path).suffix.lower().lstrip("."),
                target_scope,
                admin,
            )
            start_new_document_job(user_id, document_id)
            st.session_state.library_view = "collection"
            st.toast(f"已加入{scope_name}，后台会持续整理直到完成。")
            st.rerun()
        except Exception as exc:
            st.error(f"构建失败：{exc}")


def _event_is_new(name: str, event) -> bool:
    if not event:
        return False
    nonce = event.get("nonce")
    key = f"library_event_{name}"
    if nonce == st.session_state.get(key):
        return False
    st.session_state[key] = nonce
    if event.get("reader_scroll") is not None:
        st.session_state.workspace_reader_scroll = max(0, int(event["reader_scroll"]))
    if event.get("canvas_scroll") is not None:
        st.session_state.workspace_canvas_scroll = max(0, int(event["canvas_scroll"]))
    return True


def _document_markdown(user_id: int, document: dict) -> str:
    source = document.get("processed_markdown") or document.get("original_text") or ""
    if not source:
        source = "\n\n".join(item["content"] for item in get_document_chunks(document["user_id"], document_id=document["id"]))
    return source


@st.dialog("编辑资料正文", width="large")
def show_document_editor(user_id: int, document: dict, admin: bool) -> None:
    """Let an owner or administrator correct rendered Markdown and rebuild the document index."""
    st.caption("保存后会立即更新阅读器正文与本资料的 RAG 索引；原始上传文件保持不变。")
    current = _document_markdown(user_id, document)
    content = st.text_area(
        "Markdown 正文",
        value=current,
        height=560,
        key=f"document_editor_{document['id']}",
    )
    cancel, save = st.columns(2)
    if cancel.button("取消", use_container_width=True):
        st.session_state.pop("library_edit_document", None)
        st.rerun()
    if save.button("保存正文修改", type="primary", use_container_width=True):
        if update_document_markdown(user_id, int(document["id"]), content, admin=admin):
            st.session_state.pop("library_edit_document", None)
            st.success("正文和索引已更新。")
            st.rerun()
        st.error("保存失败：你没有权限，或正文不能为空。")


def _render_hall(user_id: int, documents: list[dict], admin: bool) -> None:
    event = render_library_hall(_category_data(documents, admin))
    if _event_is_new("hall", event):
        st.session_state.library_category = event["key"]
        st.session_state.library_view = "collection"
        st.rerun()


def _render_collection(user_id: int, documents: list[dict], admin: bool) -> None:
    category = st.session_state.get("library_category", "custom")
    if admin and category not in {"all", *SHARED_LIBRARY_SCOPES}:
        category = "all"
        st.session_state.library_category = category
    categories = _category_data(documents, admin)
    filtered = _filtered_documents(documents, category)
    jobs_by_document = get_active_document_jobs(user_id)
    result = render_collection(
        categories,
        _document_rows(filtered, user_id, admin, jobs_by_document),
        category,
        CATEGORY_LABELS.get(category, "自定义资料库"),
        can_add=True,
        active_job=None,
    )
    if _event_is_new("collection_command", result.command):
        if result.command["name"] == "back":
            st.session_state.library_view = "hall"
            st.rerun()
        if result.command["name"] == "add":
            show_document_builder(user_id, category, admin)
    if _event_is_new("collection_category", result.category):
        st.session_state.library_category = result.category["key"]
        st.rerun()
    if _event_is_new("collection_open", result.open_document):
        document_id = int(result.open_document["id"])
        document = get_library_document(user_id, document_id)
        if document and (document.get("processing_status") or "ready") == "ready":
            st.session_state.library_document_id = document_id
            st.session_state.library_view = "workspace"
            st.rerun()
        else:
            st.toast("这份资料尚未处理完成。")
    if _event_is_new("collection_reprocess", result.reprocess_document):
        document_id = int(result.reprocess_document["id"])
        document = get_library_document(user_id, document_id)
        if document and int(document["user_id"]) == user_id:
            start_reprocess_job(user_id, document_id)
            st.toast("已加入后台整理队列；断连后会自动继续。")
        else:
            st.error("只有资料所有者可以重新整理。")
        st.rerun()
    if _event_is_new("collection_delete", result.delete_document):
        document_id = int(result.delete_document["id"])
        document = get_library_document(user_id, document_id)
        if document and delete_library_document(user_id, document_id, admin=admin):
            path = Path(document.get("file_path") or "")
            if path.is_file() and path.resolve().is_relative_to(UPLOAD_DIR.resolve()):
                path.unlink(missing_ok=True)
            st.toast("资料已删除。")
        else:
            st.error("你没有删除这份资料的权限。")
        st.rerun()
    if _event_is_new("collection_reprocess_job", result.reprocess_job):
        event = result.reprocess_job
        if event.get("action") == "cancel":
            if cancel_document_job(str(event.get("job_id") or ""), user_id):
                st.toast("已请求取消，当前模型调用结束后会保留原有版本。")
        st.rerun()


def _workspace_models(user_id: int) -> tuple[list[dict], str]:
    configs = list_model_configs(user_id)
    models = [
        {"id": item["id"], "label": item["model_name"], "current": bool(item.get("is_default"))}
        for item in configs
    ]
    current = next((item["label"] for item in models if item["current"]), "尚未配置模型")
    return models, current


def _workspace_nodes(user_id: int, document_id: int) -> list[dict]:
    nodes = []
    for question in list_document_questions(user_id, document_id):
        nodes.append(
            {
                "id": question["id"],
                "type": "question",
                "title": ACTION_LABELS.get(question.get("action_type"), "阅读笔记"),
                "content": question.get("answer") or "",
                "selectedText": question.get("selected_text") or "",
                "x": int(question.get("canvas_x") or 28),
                "y": int(question.get("canvas_y") or 72),
                "width": int(question.get("canvas_width") or 520),
                "height": int(question.get("canvas_height") or 520),
            }
        )
    for mindmap in list_document_mindmaps(user_id, document_id):
        nodes.append(
            {
                "id": mindmap["id"],
                "type": "mindmap",
                "title": "思维导图",
                "content": mindmap.get("content") or "",
                "selectedText": "",
                "x": int(mindmap.get("canvas_x") or 48),
                "y": int(mindmap.get("canvas_y") or 96),
                "width": int(mindmap.get("canvas_width") or 520),
                "height": int(mindmap.get("canvas_height") or 520),
            }
        )
    return nodes


def _render_workspace(user_id: int) -> None:
    inject_library_theme(workspace=True)
    document_id = st.session_state.get("library_document_id")
    document = get_library_document(user_id, document_id) if document_id else None
    if not document:
        st.session_state.library_view = "collection"
        st.rerun()
    admin = is_admin(user_id)
    can_edit_document = can_edit_library_document(user_id, document, admin=admin)
    if st.session_state.get("library_edit_document") == int(document["id"]):
        show_document_editor(user_id, document, admin)
    models, current_model = _workspace_models(user_id)
    highlights = list_highlights(user_id, document["id"])
    reader_api = ensure_reader_api_server()
    markdown_source = _document_markdown(user_id, document)
    refreshed_markdown = ensure_document_images(document["id"], document.get("file_path") or "", markdown_source)
    if refreshed_markdown != markdown_source:
        update_document_assets_markdown(document["id"], refreshed_markdown)
        document["processed_markdown"] = refreshed_markdown
        markdown_source = refreshed_markdown
    result = render_study_workspace(
        title=document["title"],
        markdown_source=markdown_source,
        models=models,
        current_model=current_model,
        nodes=_workspace_nodes(user_id, document["id"]),
        highlights=highlights,
        context_mode=st.session_state.get("workspace_context", "section"),
        is_paper=document["doc_type"] == "paper",
        document_id=document["id"],
        completed_action=st.session_state.get("workspace_completed_action"),
        agent_error=st.session_state.get("workspace_agent_error", ""),
        active_job=st.session_state.get("workspace_reading_job", ""),
        active_action=st.session_state.get("workspace_reading_action"),
        reader_scroll=st.session_state.get("workspace_reader_scroll"),
        canvas_scroll=st.session_state.get("workspace_canvas_scroll"),
        user_id=user_id,
        api_base=reader_api["base_url"],
        api_token=reader_api["token"],
        asset_base_url=f"{reader_api['base_url']}/assets/{document['id']}/?token={reader_api['token']}&user_id={user_id}",
        can_edit_document=can_edit_document,
    )
    if _event_is_new("workspace_command", result.command):
        if result.command["name"] == "back":
            st.session_state.library_view = "collection"
            st.rerun()
        if result.command["name"] == "subscription":
            st.session_state.library_view = "collection"
            st.session_state.active_page = "订阅"
            st.session_state.pop("top_navigation_pills", None)
            st.rerun()
        if result.command["name"] == "edit-document":
            if can_edit_document:
                st.session_state.library_edit_document = int(document["id"])
                st.rerun()
            st.error("这份全局资料仅管理员可以修改。")
    if _event_is_new("workspace_model", result.model):
        activate_model_config(user_id, int(result.model["id"]))
        st.rerun()
    if _event_is_new("workspace_context", result.context):
        st.session_state.workspace_context = result.context["value"]
        st.rerun()
    if _event_is_new("workspace_action", result.action):
        event = result.action
        action = event["action"]
        selected_text = event.get("selected_text", "")
        if action == "highlight":
            added = toggle_highlight(user_id, document["id"], selected_text)
            st.toast("已保存为本资料重点。" if added else "已取消这段原文的标记。")
            return
        st.session_state.workspace_agent_error = ""
        action_nonce = int(event.get("nonce") or 0)
        job_id = start_reading_job(
            user_id,
            document["id"],
            selected_text,
            action,
            st.session_state.get("workspace_context", "section"),
            event.get("custom_question", ""),
            action_nonce,
        )
        st.session_state.workspace_reading_job = job_id
        st.session_state.workspace_reading_action = action_nonce
        st.rerun()
    if _event_is_new("workspace_job", result.job_event):
        event = result.job_event
        job_id = str(event.get("job_id") or st.session_state.get("workspace_reading_job") or "")
        action_nonce = st.session_state.get("workspace_reading_action")
        if event.get("action") == "cancel":
            cancel_reading_job(job_id, user_id)
            st.session_state.workspace_completed_action = action_nonce
            st.session_state.workspace_agent_error = ""
            st.session_state.pop("workspace_reading_job", None)
            st.session_state.pop("workspace_reading_action", None)
            discard_reading_job(job_id, user_id)
            st.rerun()
        job = get_reading_job(job_id, user_id)
        if not job:
            st.session_state.workspace_completed_action = action_nonce
            st.session_state.workspace_agent_error = "阅读任务已失效，请重新划选后提问。"
            st.session_state.pop("workspace_reading_job", None)
            st.session_state.pop("workspace_reading_action", None)
            st.rerun()
        if job["status"] in {"completed", "cancelled", "failed"}:
            st.session_state.workspace_completed_action = action_nonce
            st.session_state.workspace_agent_error = f"生成失败：{job['error']}" if job["status"] == "failed" else ""
            st.session_state.pop("workspace_reading_job", None)
            st.session_state.pop("workspace_reading_action", None)
            discard_reading_job(job_id, user_id)
            st.rerun()
    if _event_is_new("workspace_tool", result.tool):
        tool = result.tool["name"]
        with st.spinner("正在整理资料结构..."):
            if tool == "mindmap":
                generate_mindmap(user_id, document["id"])
            else:
                answer = summarize_paper(user_id, document["id"])
                add_canvas_note(user_id, document["id"], "5 分钟速读", answer, "paper_summary")
        st.rerun()
    if _event_is_new("workspace_node", result.node_event):
        event = result.node_event
        node_type = event.get("node_type")
        node_id = event.get("id")
        if node_type not in {"question", "mindmap"} or not node_id:
            return
        if event["action"] == "delete":
            delete_canvas_node(user_id, node_type, int(node_id))
            return
        elif event["action"] == "save":
            update_canvas_node(
                user_id,
                node_type,
                int(node_id),
                content=event.get("content", ""),
            )
        elif event["action"] == "layout":
            update_canvas_node(
                user_id,
                node_type,
                int(node_id),
                x=max(0, int(event.get("x", 0))),
                y=max(0, int(event.get("y", 0))),
                width=max(300, int(event.get("width", 520))),
                height=max(180, int(event.get("height", 520))),
            )
            return
        st.rerun()
    if _event_is_new("workspace_highlight", result.highlight_event):
        if result.highlight_event["action"] == "delete":
            delete_highlight(user_id, int(result.highlight_event["id"]))
        return


def render_library_page(user_id: int) -> None:
    admin = is_admin(user_id)
    view = st.session_state.get("library_view", "hall")
    if view == "workspace":
        _render_workspace(user_id)
        return
    inject_library_theme()
    documents = list_library_documents(user_id, admin=admin)
    if view == "collection":
        _render_collection(user_id, documents, admin)
    else:
        _render_hall(user_id, documents, admin)
