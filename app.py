import streamlit as st

from src.config import ensure_runtime_dirs
from src.database import init_db
from src.ui.about_page import render_about_page
from src.ui.dashboard_page import render_dashboard_page
from src.ui.food_page import render_food_page
from src.ui.library_page import render_library_page
from src.auth.auth_service import get_user_profile
from src.ui.login_page import logout, show_auth_dialog
from src.ui.model_settings_page import render_model_settings_page
from src.ui.theme import inject_theme
from src.ui.todo_page import render_todo_page


NAVIGATION = {
    "首页": render_dashboard_page,
    "资料库": render_library_page,
    "任务规划": render_todo_page,
    "美食推荐": render_food_page,
    "订阅": render_model_settings_page,
    "关于": render_about_page,
}
PUBLIC_PAGES = {"首页", "关于"}


def render_top_navigation() -> str:
    user = st.session_state.user
    with st.container(key="top_nav"):
        brand, navigation, account = st.columns([0.24, 0.58, 0.18], vertical_alignment="center")
        with brand:
            st.markdown(
                '<div class="brand-lockup"><span class="brand-mark">N</span><span><div class="brand-name">NJU-SZ Agent Hub</div><div class="brand-sub">南京大学苏州校区</div></span></div>',
                unsafe_allow_html=True,
            )
        with navigation:
            page = st.pills(
                "导航",
                list(NAVIGATION),
                default=st.session_state.get("active_page", "首页"),
                label_visibility="collapsed",
                key="top_navigation_pills",
            ) or "首页"
        with account:
            if user:
                with st.popover(user["username"], use_container_width=True):
                    st.caption("管理员账户" if user.get("is_admin") else "个人账号")
                    if st.button("退出登录", use_container_width=True):
                        logout()
            elif st.button("登录 / 注册", type="primary", use_container_width=True):
                show_auth_dialog()
    st.session_state.active_page = page
    return page


def main() -> None:
    ensure_runtime_dirs()
    init_db()
    st.set_page_config(page_title="NJU-SZ Agent Hub", page_icon="N", layout="wide", initial_sidebar_state="collapsed", menu_items={})
    inject_theme()
    if "user" not in st.session_state:
        st.session_state.user = None
    user = st.session_state.user
    if user:
        refreshed_user = get_user_profile(int(user["id"]))
        st.session_state.user = refreshed_user
        user = refreshed_user
    in_workspace = bool(
        user
        and st.session_state.get("active_page") == "资料库"
        and st.session_state.get("library_view") == "workspace"
    )
    page = "资料库" if in_workspace else render_top_navigation()

    if page not in PUBLIC_PAGES and user is None:
        st.warning("该模块会保存个人资料，请先登录。")
        show_auth_dialog()
        render_dashboard_page(None)
        return

    renderer = NAVIGATION[page]
    if page == "关于":
        renderer()
    else:
        renderer(user["id"] if user else None)


if __name__ == "__main__":
    main()
