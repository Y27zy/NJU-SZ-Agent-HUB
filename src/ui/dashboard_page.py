import streamlit as st

from src.auth.auth_service import get_default_model_config
from src.database import fetch_all
from src.rag.simple_vector_store import list_documents


def _hero() -> None:
    st.markdown(
        """
        <section class="hub-hero">
          <div class="hero-copy">
            <div class="page-eyebrow">NANJING UNIVERSITY · SUZHOU</div>
            <h1>把校园生活，交给一个真正懂场景的 <span>Agent Hub</span></h1>
            <p>从课件阅读、论文研读到任务规划与日常决策，把资料、上下文和模型能力放进同一个学生工作台。</p>
          </div>
          <div class="campus-board" aria-label="Agent Hub 工作流">
            <div class="board-head">TODAY AT NJU-SZ</div>
            <div class="board-title">今天，从一份资料开始。</div>
            <div class="board-flow">
              <div class="board-row"><span class="board-no">01</span><span>上传课件或论文</span><span class="board-tag">资料库</span></div>
              <div class="board-row"><span class="board-no">02</span><span>划选原文，原地提问</span><span class="board-tag">阅读器</span></div>
              <div class="board-row"><span class="board-no">03</span><span>安排计划与校园生活</span><span class="board-tag">Hub</span></div>
            </div>
          </div>
        </section>
        """,
        unsafe_allow_html=True,
    )


def _module_band() -> None:
    st.markdown(
        """
        <section class="module-band">
          <div class="page-eyebrow">STUDENT WORKSPACE</div>
          <h2>一站式学生工作台</h2>
          <div class="module-grid">
            <div class="module-item"><span class="module-index">01 · READ</span><strong>交互式资料库</strong><p>把 PDF 和课件整理成可划选、可追问的结构化原文。</p></div>
            <div class="module-item"><span class="module-index">02 · RESEARCH</span><strong>论文研读</strong><p>速读、方法拆解、创新点、组会大纲和复现清单。</p></div>
            <div class="module-item"><span class="module-index">03 · PLAN</span><strong>任务规划</strong><p>从自然语言待办生成日程，并用动态思维树比较方案。</p></div>
            <div class="module-item"><span class="module-index">04 · LIFE</span><strong>校园生活</strong><p>完成餐饮推荐和轻量生活决策。</p></div>
          </div>
        </section>
        """,
        unsafe_allow_html=True,
    )


def render_dashboard_page(user_id: int | None = None) -> None:
    _hero()
    if user_id is None:
        _module_band()
        st.info("首页和项目介绍可直接浏览。登录后可进入资料库并保存个人数据。")
        return

    config = get_default_model_config(user_id)
    docs = list_documents(user_id)
    todos = fetch_all("SELECT * FROM todos WHERE user_id = ? AND status != 'done'", (user_id,))
    st.markdown('<div class="module-band"><div class="page-eyebrow">MY CAMPUS DESK</div><h2>我的学习桌</h2></div>', unsafe_allow_html=True)
    col1, col2, col3 = st.columns(3)
    col1.metric("资料", len(docs))
    col2.metric("未完成任务", len(todos))
    col3.metric("当前模型", config["model_name"] if config else "未配置")
    _module_band()
