import streamlit as st

from src.auth.auth_service import login_user, register_user


@st.dialog("登录 NJU-SZ Agent Hub", width="small")
def show_auth_dialog() -> None:
    st.caption("登录后可保存资料、模型配置、学习记录和个人偏好。")
    login_tab, register_tab = st.tabs(["登录", "注册"])
    with login_tab:
        with st.form("dialog_login_form"):
            username = st.text_input("用户名")
            password = st.text_input("密码", type="password")
            submitted = st.form_submit_button("登录", type="primary", use_container_width=True)
        if submitted:
            user = login_user(username, password)
            if user:
                st.session_state.user = user
                st.session_state.active_page = "首页"
                st.rerun()
            st.error("用户名或密码错误。")
    with register_tab:
        with st.form("dialog_register_form"):
            username = st.text_input("新用户名")
            password = st.text_input("新密码", type="password")
            submitted = st.form_submit_button("创建账号", type="primary", use_container_width=True)
        if submitted:
            ok, message = register_user(username, password)
            st.success(message) if ok else st.warning(message)


def logout() -> None:
    st.session_state.user = None
    st.session_state.active_page = "首页"
    st.rerun()
