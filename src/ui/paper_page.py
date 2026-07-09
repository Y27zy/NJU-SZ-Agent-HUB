import streamlit as st

from src.memory.working_memory import update_working_memory
from src.modules.paper_agent import (
    extract_contributions,
    extract_experiment_setup,
    extract_limitations,
    extract_method,
    extract_research_question,
    generate_presentation_outline,
    generate_reproduction_checklist,
    ingest_paper,
    summarize_paper,
    translate_text,
)
from src.rag.simple_vector_store import list_documents
from src.utils.file_storage import safe_upload_path
from src.utils.markdown import split_markdown_math_blocks


def _save_uploaded_file(user_id: int, uploaded_file, subdir: str):
    target = safe_upload_path(user_id, subdir, uploaded_file.name)
    target.write_bytes(uploaded_file.getbuffer())
    return target


def _render_markdown_with_latex(text: str) -> None:
    for kind, block in split_markdown_math_blocks(text):
        if kind == "math":
            st.latex(block)
        else:
            st.markdown(block)


def _set_paper_output(title: str, body: str) -> None:
    st.session_state.paper_output_title = title
    st.session_state.paper_output_body = body


def render_paper_page(user_id: int) -> None:
    if "paper_output_title" not in st.session_state:
        st.session_state.paper_output_title = "等待分析"
    if "paper_output_body" not in st.session_state:
        st.session_state.paper_output_body = "上传或选择论文后，可以在左侧选择速读、提取信息、生成大纲或翻译片段。"

    left, right = st.columns([0.42, 0.58], gap="large")

    with left:
        st.subheader("论文与操作")
        uploaded = st.file_uploader("上传论文 PDF", type=["pdf"])
        if uploaded and st.button("解析并加入论文知识库", use_container_width=True):
            path = _save_uploaded_file(user_id, uploaded, "paper")
            doc_id = ingest_paper(user_id, path, uploaded.name)
            update_working_memory(st.session_state, current_task_type="paper", current_document=uploaded.name)
            st.success(f"论文已加入知识库，document_id={doc_id}")

        docs = list_documents(user_id, "paper")
        selected_doc = st.selectbox("选择论文", docs, format_func=lambda d: f"{d['id']} - {d['title']}") if docs else None
        doc_id = selected_doc["id"] if selected_doc else None
        disabled = doc_id is None
        if disabled:
            st.info("还没有论文资料。请先上传 PDF。")

        st.divider()
        st.markdown("**阅读分析**")
        col1, col2 = st.columns(2)
        with col1:
            if st.button("5 分钟速读", disabled=disabled, use_container_width=True):
                result = summarize_paper(user_id, doc_id)
                _set_paper_output("5 分钟速读", result)
                update_working_memory(st.session_state, current_task_type="paper_summary", current_document=selected_doc["title"], last_user_input="5 分钟速读", last_agent_output=result[:500])
            if st.button("提取方法", disabled=disabled, use_container_width=True):
                result = extract_method(user_id, doc_id)
                _set_paper_output("论文方法", result)
                update_working_memory(st.session_state, current_task_type="paper_method", current_document=selected_doc["title"], last_user_input="提取方法", last_agent_output=result[:500])
            if st.button("提取局限性", disabled=disabled, use_container_width=True):
                result = extract_limitations(user_id, doc_id)
                _set_paper_output("论文局限性", result)
                update_working_memory(st.session_state, current_task_type="paper_limitations", current_document=selected_doc["title"], last_user_input="提取局限性", last_agent_output=result[:500])
        with col2:
            if st.button("研究问题", disabled=disabled, use_container_width=True):
                result = extract_research_question(user_id, doc_id)
                _set_paper_output("研究问题", result)
                update_working_memory(st.session_state, current_task_type="paper_research_question", current_document=selected_doc["title"], last_user_input="提取研究问题", last_agent_output=result[:500])
            if st.button("创新点", disabled=disabled, use_container_width=True):
                result = extract_contributions(user_id, doc_id)
                _set_paper_output("论文创新点", result)
                update_working_memory(st.session_state, current_task_type="paper_contributions", current_document=selected_doc["title"], last_user_input="提取创新点", last_agent_output=result[:500])
            if st.button("实验设置", disabled=disabled, use_container_width=True):
                result = extract_experiment_setup(user_id, doc_id)
                _set_paper_output("实验设置", result)
                update_working_memory(st.session_state, current_task_type="paper_experiment", current_document=selected_doc["title"], last_user_input="提取实验设置", last_agent_output=result[:500])

        st.markdown("**汇报与复现**")
        outline_col, checklist_col = st.columns(2)
        with outline_col:
            if st.button("组会大纲", disabled=disabled, use_container_width=True):
                result = generate_presentation_outline(user_id, doc_id)
                _set_paper_output("组会汇报大纲", result)
                update_working_memory(st.session_state, current_task_type="paper_outline", current_document=selected_doc["title"], last_user_input="生成组会汇报大纲", last_agent_output=result[:500])
        with checklist_col:
            if st.button("复现 checklist", disabled=disabled, use_container_width=True):
                result = generate_reproduction_checklist(user_id, doc_id)
                _set_paper_output("复现 checklist", result)
                update_working_memory(st.session_state, current_task_type="paper_reproduction", current_document=selected_doc["title"], last_user_input="生成复现 checklist", last_agent_output=result[:500])

        st.markdown("**翻译片段**")
        text = st.text_area("论文片段", height=130)
        if st.button("翻译为中文", disabled=not text, use_container_width=True):
            result = translate_text(user_id, text, "中文")
            _set_paper_output("论文片段翻译", result)
            update_working_memory(st.session_state, current_task_type="paper_translation", last_user_input=text[:500], last_agent_output=result[:500])

    with right:
        st.subheader(st.session_state.paper_output_title)
        _render_markdown_with_latex(st.session_state.paper_output_body)
