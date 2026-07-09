import streamlit as st

from src.auth.auth_service import get_default_model_config
from src.database import fetch_all
from src.memory.memory_service import list_memories
from src.rag.simple_vector_store import list_documents


def render_dashboard_page(user_id: int) -> None:
    config = get_default_model_config(user_id)
    model_label = f"{config['provider']} / {config['model_name']}" if config else "MockLLMProvider / mock-agent"
    st.info(f"当前默认模型：{model_label}")

    col1, col2, col3 = st.columns(3)
    docs = list_documents(user_id)
    todos = fetch_all("SELECT * FROM todos WHERE user_id = ? AND status != 'done' ORDER BY id DESC LIMIT 5", (user_id,))
    memories = list_memories(user_id)[:5]

    with col1:
        st.subheader("最近上传文档")
        if docs:
            for doc in docs[:5]:
                st.write(f"- {doc['title']} ({doc['doc_type']})")
        else:
            st.caption("还没有上传资料。")

    with col2:
        st.subheader("未完成 Todo")
        if todos:
            for todo in todos:
                st.write(f"- {todo['title']} | {todo['priority']}")
        else:
            st.caption("暂无未完成任务。")

    with col3:
        st.subheader("最近记忆")
        if memories:
            for memory in memories:
                st.write(f"- [{memory['memory_type']}] {memory['content'][:40]}")
        else:
            st.caption("暂无记忆。")

    st.divider()
    st.markdown(
        """
        本 Demo 包含课程资料问答、论文辅助阅读、Todo 规划、饮食推荐、分层记忆和统一模型配置。
        默认离线 Mock 模型即可运行；配置真实 API 后可切换为真实大模型。
        """
    )
