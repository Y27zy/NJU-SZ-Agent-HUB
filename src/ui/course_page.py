import streamlit as st

from src.memory.working_memory import update_working_memory
from src.modules.course_agent import answer_course_question, generate_course_summary, generate_quiz, ingest_course_document
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


def render_course_page(user_id: int) -> None:
    if "course_output_title" not in st.session_state:
        st.session_state.course_output_title = "等待生成"
    if "course_output_body" not in st.session_state:
        st.session_state.course_output_body = "上传或选择课程资料后，可以在左侧提问、总结重点或生成练习题。"

    left, right = st.columns([0.42, 0.58], gap="large")

    with left:
        st.subheader("资料与操作")
        uploaded = st.file_uploader(
            "上传课程 PDF / PPTX / TXT / Markdown",
            type=["pdf", "pptx", "txt", "md", "markdown"],
        )
        if uploaded and st.button("解析并加入课程知识库", use_container_width=True):
            path = _save_uploaded_file(user_id, uploaded, "course")
            doc_id = ingest_course_document(user_id, path, uploaded.name)
            update_working_memory(st.session_state, current_task_type="course", current_document=uploaded.name)
            st.success(f"已加入知识库，document_id={doc_id}")

        docs = list_documents(user_id, "course")
        selected_doc = None
        if docs:
            selected_doc = st.selectbox("选择课程资料", docs, format_func=lambda d: f"{d['id']} - {d['title']}")
        else:
            st.info("还没有课程资料。可以先上传 data/sample_course.txt 测试。")

        st.divider()
        with st.form("course_question_form"):
            query = st.text_area("课程问题", placeholder="PCA 和 LDA 有什么区别？", height=110)
            ask_submitted = st.form_submit_button("提问", use_container_width=True)
        if ask_submitted and query:
            answer = answer_course_question(user_id, query)
            st.session_state.course_output_title = "课程问答"
            st.session_state.course_output_body = answer
            update_working_memory(
                st.session_state,
                current_task_type="course_qa",
                current_document=selected_doc["title"] if selected_doc else "",
                last_user_input=query,
                last_agent_output=answer[:500],
            )

        if st.button("总结重点", disabled=selected_doc is None, use_container_width=True):
            summary = generate_course_summary(user_id, selected_doc["id"])
            st.session_state.course_output_title = "课程重点总结"
            st.session_state.course_output_body = summary
            update_working_memory(
                st.session_state,
                current_task_type="course_summary",
                current_document=selected_doc["title"],
                last_user_input="总结重点",
                last_agent_output=summary[:500],
            )

        st.markdown("**练习题生成**")
        topic = st.text_input("练习题主题", value="PCA、LDA、决策树")
        if st.button("生成练习题", use_container_width=True):
            quiz = generate_quiz(user_id, topic)
            st.session_state.course_output_title = "练习题与参考答案"
            st.session_state.course_output_body = quiz
            update_working_memory(
                st.session_state,
                current_task_type="course_quiz",
                last_user_input=topic,
                last_agent_output=quiz[:500],
            )

    with right:
        st.subheader(st.session_state.course_output_title)
        _render_markdown_with_latex(st.session_state.course_output_body)
