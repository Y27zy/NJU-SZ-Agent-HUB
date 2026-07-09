import streamlit as st

from src.memory.memory_service import build_context_with_memory, list_memories, update_user_memory
from src.memory.working_memory import format_working_memory, init_working_memory


def render_memory_page(user_id: int) -> None:
    st.markdown("三层记忆：Working Memory 存在 session_state，User Memory 存在 memory_items，Knowledge Memory 来自文档 chunks。")

    st.subheader("Working Memory")
    st.text(format_working_memory(init_working_memory(st.session_state)))

    with st.form("memory_form"):
        memory_type = st.selectbox("记忆类型", ["user", "working", "knowledge"])
        importance = st.slider("重要性", 1, 5, 3)
        content = st.text_area("记忆内容")
        if st.form_submit_button("保存记忆") and content:
            update_user_memory(user_id, content, memory_type, importance)
            st.success("记忆已保存。")

    query = st.text_input("构建带记忆的上下文", placeholder="例如：我今天应该怎么复习机器学习？")
    if st.button("检索记忆上下文") and query:
        st.text(build_context_with_memory(user_id, query))

    st.subheader("全部记忆")
    for item in list_memories(user_id):
        st.write(f"- [{item['memory_type']}] importance={item['importance']} | {item['content']}")
