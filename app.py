import streamlit as st

from src.config import ensure_runtime_dirs
from src.database import init_db
from src.ui.about_page import render_about_page
from src.ui.course_page import render_course_page
from src.ui.dashboard_page import render_dashboard_page
from src.ui.food_page import render_food_page
from src.ui.login_page import render_login_page, render_logout_button
from src.ui.memory_page import render_memory_page
from src.ui.model_settings_page import render_model_settings_page
from src.ui.paper_page import render_paper_page
from src.ui.todo_page import render_todo_page


PAGES = [
    ("首页 Dashboard", "首页 Dashboard", render_dashboard_page),
    ("模型配置 Model Settings", "模型配置 Model Settings", render_model_settings_page),
    ("课程学习 Course Agent", "课程学习 Course Agent", render_course_page),
    ("科研论文 Paper Agent", "科研论文 Paper Agent", render_paper_page),
    ("Todo 规划 Todo Agent", "Todo 规划 Todo Agent", render_todo_page),
    ("美食推荐 Food Agent", "美食推荐 Food Agent", render_food_page),
    ("记忆管理 Memory", "记忆管理 Memory", render_memory_page),
    ("关于项目 About", "关于项目 About", render_about_page),
]


def inject_app_css() -> None:
    st.markdown(
        """
        <style>
        [data-testid="stToolbar"], [data-testid="stDecoration"], [data-testid="stStatusWidget"],
        .stDeployButton, header [data-testid="stToolbar"] {
            display: none !important;
            visibility: hidden !important;
        }
        .block-container {
            padding-top: 2.2rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def main() -> None:
    ensure_runtime_dirs()
    init_db()

    st.set_page_config(
        page_title="NJU-SZ Agent Hub",
        page_icon="🎓",
        layout="wide",
        initial_sidebar_state="expanded",
        menu_items={},
    )
    inject_app_css()

    if "user" not in st.session_state:
        st.session_state.user = None

    if st.session_state.user is None:
        render_login_page()
        return

    user = st.session_state.user
    st.sidebar.title("NJU-SZ Agent Hub")
    st.sidebar.caption(f"当前用户：{user['username']}")
    labels = [label for label, _, _ in PAGES]
    page = st.sidebar.radio(
        "导航",
        labels,
    )
    render_logout_button()

    _, title, renderer = next(item for item in PAGES if item[0] == page)
    st.title(title)
    if page == "关于项目 About":
        renderer()
    else:
        renderer(user["id"])


if __name__ == "__main__":
    main()
