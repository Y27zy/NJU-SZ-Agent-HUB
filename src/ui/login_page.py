import streamlit as st

from src.auth.auth_service import login_user, register_user


def render_login_page() -> None:
    st.title("NJU-SZ Agent Hub")
    st.caption("南京大学苏州校区学生 Agent Hub")
    tab_login, tab_register = st.tabs(["登录", "注册"])

    with tab_login:
        username = st.text_input("用户名", key="login_username")
        password = st.text_input("密码", type="password", key="login_password")
        if st.button("登录", type="primary"):
            user = login_user(username, password)
            if user:
                st.session_state.user = user
                st.rerun()
            st.error("用户名或密码错误。")

    with tab_register:
        username = st.text_input("新用户名", key="register_username")
        password = st.text_input("新密码", type="password", key="register_password")
        if st.button("注册"):
            ok, message = register_user(username, password)
            if ok:
                st.success(message)
            else:
                st.warning(message)


def render_logout_button() -> None:
    if st.sidebar.button("退出登录"):
        st.session_state.user = None
        st.rerun()
