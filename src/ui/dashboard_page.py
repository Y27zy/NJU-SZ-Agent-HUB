"""The public dashboard and signed-in campus desk."""

from html import escape

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
            <h1>NJU-SZ <span>Agent Hub</span></h1>
            <p>一个为南大苏州校区学生准备的学习工作台。把资料阅读、论文研读、任务安排与校园生活决策放进同一个清晰的 Agent 体验里。</p>
            <div class="hero-note">从一份资料、一条待办或一顿饭开始</div>
          </div>
          <div class="campus-board" aria-label="学生工作流">
            <div class="board-head">TODAY AT NJU-SZ</div>
            <div class="board-title">让每一步，都回到你正在做的事。</div>
            <div class="board-flow">
              <div class="board-row"><span class="board-no">01</span><span>上传课件或论文</span><span class="board-tag">资料库</span></div>
              <div class="board-row"><span class="board-no">02</span><span>划选原文，原地追问</span><span class="board-tag">阅读器</span></div>
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
            <div class="module-item"><span class="module-index">03 · PLAN</span><strong>任务规划</strong><p>从自然语言待办生成日程，并比较不同执行方案。</p></div>
            <div class="module-item"><span class="module-index">04 · LIFE</span><strong>校园生活</strong><p>从审核过的本地数据中，替你做明确的餐饮决定。</p></div>
          </div>
        </section>
        """,
        unsafe_allow_html=True,
    )


def _desk_strip(user_id: int) -> None:
    config = get_default_model_config(user_id)
    docs = [doc for doc in list_documents(user_id) if doc.get("document_role", "standalone") != "section"]
    todos = fetch_all("SELECT id FROM todos WHERE user_id = ? AND status != 'done'", (user_id,))
    model_name = escape(str(config["model_name"])) if config else "尚未配置"
    st.markdown(
        f"""
        <section class="module-band">
          <div class="page-eyebrow">MY CAMPUS DESK</div>
          <h2>我的学习桌</h2>
          <div class="desk-strip">
            <div class="desk-stat"><span>资料</span><strong>{len(docs)}</strong></div>
            <div class="desk-stat"><span>待完成任务</span><strong>{len(todos)}</strong></div>
            <div class="desk-stat model"><span>当前模型</span><strong>{model_name}</strong></div>
          </div>
        </section>
        """,
        unsafe_allow_html=True,
    )


def render_dashboard_page(user_id: int | None = None) -> None:
    """Render the landing experience and authenticated user summary."""
    _hero()
    if user_id is not None:
        _desk_strip(user_id)
    _module_band()
    if user_id is None:
        st.info("登录后即可保存个人资料、模型设置与任务记录。")
