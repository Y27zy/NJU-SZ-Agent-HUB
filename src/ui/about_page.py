import streamlit as st


def render_about_page() -> None:
    st.markdown(
        """
        **NJU-SZ Agent Hub** 是一个面向南京大学苏州校区学生的一站式校园 Agent 平台原型。

        它不是单一问答机器人，而是围绕课程学习、科研阅读、时间管理和饮食决策构建的多模块系统。
        项目默认使用 MockLLMProvider 离线运行；配置真实 API 后可以调用 Qwen、Kimi、DeepSeek、智谱或 OpenAI-compatible API。

        适用场景：
        - 机器学习导论课程大项目展示
        - Agent、RAG、记忆系统和轻量规划器原型验证
        - 后续扩展为校园个人 AI 助手
        """
    )
