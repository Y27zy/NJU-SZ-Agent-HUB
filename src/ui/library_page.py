from pathlib import Path

import streamlit as st

from src.auth.auth_service import activate_model_config, get_default_model_config, list_model_configs
from src.modules.library_agent import (
    add_canvas_note,
    add_highlight,
    ask_about_selection,
    create_folder,
    delete_canvas_node,
    delete_highlight,
    generate_mindmap,
    list_document_mindmaps,
    list_document_questions,
    list_folders,
    list_highlights,
    update_canvas_node,
)
from src.modules.paper_agent import summarize_paper
from src.rag.document_processor import process_document, reprocess_document
from src.rag.simple_vector_store import get_document, get_document_chunks, list_documents
from src.ui.library_components import render_collection, render_library_hall, render_study_workspace
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
ACTION_LABELS = {
    "explain": "解释这一步",
    "example": "给一个例子",
    "solve": "提问与解题",
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
        .stApp:has(.library-page-marker) .block-container { max-width:1480px !important; padding:0 2.4rem 3rem !important; }
        .stApp:has(.workspace-page-marker) .block-container { max-width:none !important; padding:0 !important; }
        .stApp:has(.workspace-page-marker) [data-testid="stMainBlockContainer"] { gap:0 !important; }
        .stApp:has(.workspace-page-marker) [data-testid="stMainBlockContainer"] > div,
        .stApp:has(.workspace-page-marker) [data-testid="stVerticalBlock"] { gap:0 !important; }
        .stApp:has(.workspace-page-marker) .st-key-top_nav { display:none !important; }
        .stApp:has(.library-page-marker) .st-key-top_nav { margin-bottom:0 !important; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _category_data(documents: list[dict]) -> list[dict]:
    counts = {
        "all": len(documents),
        "course": sum(doc["doc_type"] == "course" for doc in documents),
        "paper": sum(doc["doc_type"] == "paper" for doc in documents),
        "other": sum(doc["doc_type"] == "other" for doc in documents),
        "custom": len(documents),
        "public": 0,
        "exam": 0,
        "shared": 0,
    }
    return [
        {"key": key, "label": CATEGORY_LABELS[key], "count": counts[key], "featured": key == "custom", "disabled": key in {"public", "exam", "shared"}, "note": "筹备中" if key in {"public", "exam", "shared"} else ""}
        for key in CATEGORY_LABELS
    ]


def _filtered_documents(documents: list[dict], category: str) -> list[dict]:
    if category in {"all", "custom"}:
        return documents
    if category in {"course", "paper", "other"}:
        return [doc for doc in documents if doc["doc_type"] == category]
    return []


def _document_rows(documents: list[dict]) -> list[dict]:
    kind_labels = {"course": "课程", "paper": "论文", "other": "资料"}
    status_labels = {"ready": "可学习", "processing": "处理中", "error": "处理失败"}
    return [
        {
            "id": doc["id"],
            "title": doc["title"],
            "kind": kind_labels.get(doc["doc_type"], "资料"),
            "status": status_labels.get(doc.get("processing_status"), "可学习"),
            "pages": doc.get("page_count") or 0,
        }
        for doc in documents
    ]


def _save_upload(user_id: int, uploaded) -> str:
    path = safe_upload_path(user_id, "library", uploaded.name)
    path.write_bytes(uploaded.getbuffer())
    return str(path)


@st.dialog("构建新资料", width="large")
def show_document_builder(user_id: int) -> None:
    st.markdown("### 从原文件构建可交互资料")
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
            format_func=lambda value: {"course": "课程学习", "paper": "论文研读", "other": "其他资料"}[value],
        )
    with right:
        folders = list_folders(user_id)
        folder_options = [None, *[folder["id"] for folder in folders]]
        folder_id = st.selectbox(
            "保存到",
            folder_options,
            format_func=lambda value: "自定义资料库" if value is None else next(folder["name"] for folder in folders if folder["id"] == value),
        )
    with st.expander("新建文件夹"):
        folder_name = st.text_input("文件夹名称")
        if st.button("创建文件夹", disabled=not folder_name.strip(), use_container_width=True):
            create_folder(user_id, folder_name)
            st.rerun()
    st.markdown("**处理方案**")
    st.markdown(
        """
        <div style="padding:14px 16px;border:1px solid #5d4034;background:#211713;color:#e9ddd6;border-radius:5px">
        <strong style="color:#e2a58d">AI 结构化原文</strong><br>
        <span style="color:#a79b94">逐页提取/OCR → 版面与公式清洗 → Markdown → RAG 索引。处理时间与页数、模型速度有关。</span>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if st.button("开始构建资料", type="primary", disabled=uploaded is None, use_container_width=True):
        progress = st.progress(0, text="准备解析原文件")

        def update_progress(current: int, total: int, message: str) -> None:
            progress.progress(current / max(total, 1), text=message)

        try:
            document_id = process_document(
                user_id,
                _save_upload(user_id, uploaded),
                uploaded.name,
                doc_type,
                folder_id,
                update_progress,
            )
            st.session_state.library_document_id = document_id
            st.session_state.library_view = "collection"
            st.success("资料构建完成，已加入自定义资料库。")
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
    return True


def _document_markdown(user_id: int, document: dict) -> str:
    source = document.get("processed_markdown") or document.get("original_text") or ""
    if not source:
        source = "\n\n".join(item["content"] for item in get_document_chunks(user_id, document_id=document["id"]))
    return source


def _render_hall(user_id: int, documents: list[dict]) -> None:
    event = render_library_hall(_category_data(documents))
    if _event_is_new("hall", event):
        st.session_state.library_category = event["key"]
        st.session_state.library_view = "collection"
        st.rerun()


def _render_collection(user_id: int, documents: list[dict]) -> None:
    category = st.session_state.get("library_category", "custom")
    categories = _category_data(documents)
    filtered = _filtered_documents(documents, category)
    result = render_collection(categories, _document_rows(filtered), category, CATEGORY_LABELS.get(category, "自定义资料库"))
    if _event_is_new("collection_command", result.command):
        if result.command["name"] == "back":
            st.session_state.library_view = "hall"
            st.rerun()
        if result.command["name"] == "add":
            show_document_builder(user_id)
    if _event_is_new("collection_category", result.category):
        st.session_state.library_category = result.category["key"]
        st.rerun()
    if _event_is_new("collection_open", result.open_document):
        document_id = int(result.open_document["id"])
        document = get_document(user_id, document_id)
        if document and (document.get("processing_status") or "ready") == "ready":
            st.session_state.library_document_id = document_id
            st.session_state.library_view = "workspace"
            st.rerun()
        else:
            st.toast("这份资料尚未处理完成。")
    if _event_is_new("collection_reprocess", result.reprocess_document):
        document_id = int(result.reprocess_document["id"])
        with st.spinner("正在重新识别整份资料的章节结构并排版，请不要关闭页面..."):
            reprocess_document(user_id, document_id)
        st.success("资料已按章节重新整理。")
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
    document = get_document(user_id, document_id) if document_id else None
    if not document:
        st.session_state.library_view = "collection"
        st.rerun()
    models, current_model = _workspace_models(user_id)
    highlights = list_highlights(user_id, document["id"])
    result = render_study_workspace(
        title=document["title"],
        markdown_source=_document_markdown(user_id, document),
        models=models,
        current_model=current_model,
        nodes=_workspace_nodes(user_id, document["id"]),
        highlights=highlights,
        context_mode=st.session_state.get("workspace_context", "section"),
        is_paper=document["doc_type"] == "paper",
        document_id=document["id"],
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
            add_highlight(user_id, document["id"], selected_text)
            st.toast("已保存为本资料重点。")
            st.rerun()
        with st.spinner("正在结合原文思考..."):
            ask_about_selection(
                user_id,
                document["id"],
                selected_text,
                action,
                st.session_state.get("workspace_context", "section"),
                event.get("custom_question", ""),
            )
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
        if event["action"] == "delete":
            delete_canvas_node(user_id, event["node_type"], int(event["id"]))
        elif event["action"] == "save":
            update_canvas_node(
                user_id,
                event["node_type"],
                int(event["id"]),
                content=event.get("content", ""),
            )
        elif event["action"] == "layout":
            update_canvas_node(
                user_id,
                event["node_type"],
                int(event["id"]),
                x=max(0, int(event.get("x", 0))),
                y=max(0, int(event.get("y", 0))),
                width=max(300, int(event.get("width", 520))),
                height=max(180, int(event.get("height", 520))),
            )
        st.rerun()
    if _event_is_new("workspace_highlight", result.highlight_event):
        if result.highlight_event["action"] == "delete":
            delete_highlight(user_id, int(result.highlight_event["id"]))
        st.rerun()


def render_library_page(user_id: int) -> None:
    view = st.session_state.get("library_view", "hall")
    if view == "workspace":
        _render_workspace(user_id)
        return
    inject_library_theme()
    documents = list_documents(user_id)
    if view == "collection":
        _render_collection(user_id, documents)
    else:
        _render_hall(user_id, documents)
