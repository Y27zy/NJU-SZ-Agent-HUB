import streamlit as st

from src.config import ensure_runtime_dirs
from src.database import init_db
from src.ui.about_page import render_about_page
from src.ui.dashboard_page import render_dashboard_page
from src.ui.food_page import render_food_page
from src.ui.library_page import render_library_page
from src.auth.auth_service import delete_personal_account, get_user_profile, list_deletable_users
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
        brand, navigation, account = st.columns([0.29, 0.55, 0.16], vertical_alignment="center")
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
                    if user.get("is_admin"):
                        with st.expander("账户管理", expanded=False):
                            candidates = list_deletable_users(int(user["id"]))
                            if not candidates:
                                st.caption("目前没有可注销的个人账户。")
                            else:
                                labels = {
                                    f"{item['username']} · 注册于 {str(item['created_at'])[:10]}": int(item["id"])
                                    for item in candidates
                                }
                                selected_label = st.selectbox(
                                    "选择要注销的个人账户",
                                    list(labels),
                                    key="admin_account_delete_target",
                                )
                                confirmed = st.checkbox(
                                    "我确认永久删除该账户及其个人资料、待办和模型配置",
                                    key="admin_account_delete_confirm",
                                )
                                if st.button(
                                    "永久注销所选账户",
                                    type="primary",
                                    use_container_width=True,
                                    disabled=not confirmed,
                                    key="admin_account_delete_button",
                                ):
                                    success, message = delete_personal_account(
                                        int(user["id"]), labels[selected_label]
                                    )
                                    if success:
                                        st.session_state.pop("admin_account_delete_confirm", None)
                                        st.success(message)
                                        st.rerun()
                                    else:
                                        st.error(message)
                    if st.button("退出登录", use_container_width=True):
                        logout()
            elif st.button("登录", type="secondary", use_container_width=True, help="登录已有账户或注册新账户"):
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
