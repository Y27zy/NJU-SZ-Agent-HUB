"""Project background and technical boundaries."""

import streamlit as st


def render_about_page() -> None:
    """Render a concise, project-appropriate about page."""
    st.markdown(
        """
        <style>
        .about-hero{padding:42px 0 30px;border-bottom:1px solid #dfe3ea}.about-hero h1{margin:10px 0 14px;font-size:48px;line-height:1.12}.about-hero p{max-width:780px;margin:0;color:#667085;line-height:1.85;font-size:1.04rem}
        .about-grid{display:grid;grid-template-columns:repeat(4,1fr);margin:28px 0 44px;border:1px solid #dfe3ea;border-right:0}.about-grid div{min-height:164px;padding:20px;border-right:1px solid #dfe3ea;background:#fff}.about-grid span{display:block;color:#087f78;font-size:.72rem;font-weight:780;letter-spacing:.08em}.about-grid strong{display:block;margin:17px 0 8px;font-size:1.08rem}.about-grid p{margin:0;color:#667085;font-size:.86rem;line-height:1.65}
        .about-section{padding:28px 0;border-top:1px solid #dfe3ea}.about-section h2{margin:0 0 14px;font-size:1.7rem}.about-section p{max-width:860px;color:#667085;line-height:1.8}.about-flow{display:grid;grid-template-columns:repeat(3,1fr);gap:0;border:1px solid #dfe3ea}.about-flow div{padding:20px;border-right:1px solid #dfe3ea;background:#fff}.about-flow div:last-child{border-right:0}.about-flow b{color:#5b2a86}.about-flow p{margin:8px 0 0;font-size:.9rem}.about-note{padding:18px 20px;border-left:4px solid #087f78;background:#eaf6f4;color:#314255;line-height:1.75}
        @media(max-width:900px){.about-grid{grid-template-columns:1fr 1fr}.about-flow{grid-template-columns:1fr}.about-grid div,.about-flow div{border-bottom:1px solid #dfe3ea}.about-hero h1{font-size:38px}}@media(max-width:620px){.about-grid{grid-template-columns:1fr}}
        </style>
        <section class="about-hero">
          <div class="page-eyebrow">COURSE PROJECT · AGENT SYSTEM</div>
          <h1>NJU-SZ Agent Hub</h1>
          <p>南京大学苏州校区学生 Agent 平台原型，为阅读、研究、规划和校园生活分别配置资料、工具、上下文与可追溯的执行流程。</p>
        </section>
        <section class="about-grid">
          <div><span>01 · READ</span><strong>课程阅读</strong><p>将课程资料整理为可划选、可提问、可继续编辑的学习原文。</p></div>
          <div><span>02 · RESEARCH</span><strong>论文研读</strong><p>围绕研究问题、方法、实验和复现任务组织辅助能力。</p></div>
          <div><span>03 · PLAN</span><strong>任务规划</strong><p>把自然语言待办拆为独立任务与步骤，并用轻量方案比较支持安排。</p></div>
          <div><span>04 · LIFE</span><strong>校园生活</strong><p>不知道吃什么？我们来替你摆脱选择困难！</p></div>
        </section>
        <section class="about-section">
          <div class="page-eyebrow">HOW IT WORKS</div>
          <h2>从资料到行动，而不是只生成一段答案</h2>
          <div class="about-flow">
            <div><b>资料与检索</b><p>文档会被解析、切分并建立轻量检索索引，让回答优先依据当前资料。</p></div>
            <div><b>记忆与上下文</b><p>会话状态、用户长期偏好与资料知识分层保存，避免把全部历史聊天硬塞进提示词。</p></div>
            <div><b>Agent 与工具</b><p>不同任务由相应 Agent 调用检索、规划、数据筛选等工具，模型不代替确定性逻辑。</p></div>
          </div>
        </section>
        <section class="about-section">
          <div class="page-eyebrow">PROJECT BOUNDARY</div>
          <h2>项目支持</h2>
          <p>平台支持用户自行配置 Qwen、Kimi、DeepSeek、智谱或 OpenAI-compatible API。资料和个人数据默认保存在本地；“订阅”页面仅用于展示平台托管模型的产品形态，不创建真实订单或支付。</p>
          <div class="about-note">当前重点是工程结构、Agent 编排和学生场景的可用性。更大规模的向量数据库、统一权限服务、在线协作与正式支付均属于后续扩展方向。</div>
        </section>
        """,
        unsafe_allow_html=True,
    )
