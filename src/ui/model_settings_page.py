import streamlit as st

from src.auth.auth_service import (
    activate_model_config,
    delete_model_config,
    get_default_model_config,
    list_model_configs,
    set_default_model_config,
)
from src.llm.gateway import PROVIDER_DEFAULTS, normalize_model_config, test_model_config


PROVIDERS = ["mock", "openai-compatible", "qwen", "kimi", "deepseek", "zhipu", "custom"]
MODEL_SETTINGS_UI_VERSION = "model-settings-ui-v2"


def _model_label(config: dict) -> str:
    default_mark = "当前使用" if config.get("is_default") else "可选"
    base = config.get("api_base") or "无需 API Base"
    key_mark = "API Key 已保存" if config.get("api_key") else "API Key 缺失"
    return f"{default_mark} | {config['provider']} | {config['model_name']} | {key_mark} | {base}"


def _selected_config(configs: list[dict]) -> dict:
    default_index = next((i for i, cfg in enumerate(configs) if cfg.get("is_default")), 0)
    selected = st.radio(
        "当前记录的模型",
        configs,
        index=default_index,
        format_func=_model_label,
        label_visibility="collapsed",
        key="model_config_radio",
    )
    if selected and not selected.get("is_default"):
        if activate_model_config(st.session_state.user["id"], selected["id"]):
            st.toast("已切换当前模型。")
            st.rerun()
    return selected


def render_model_settings_page(user_id: int) -> None:
    st.caption(f"界面版本：{MODEL_SETTINGS_UI_VERSION}")
    current = get_default_model_config(user_id)
    if current:
        st.success(f"当前默认模型：{current['provider']} / {current['model_name']}")
    else:
        st.info("当前使用离线 MockLLMProvider。")

    configs = list_model_configs(user_id)
    if configs:
        st.subheader("选择已保存模型")
        selected = _selected_config(configs)
        col_test, col_delete = st.columns(2)
        with col_test:
            if st.button("测试所选模型连接", use_container_width=True):
                ok, message = test_model_config(selected)
                if ok:
                    st.success(message)
                else:
                    st.warning(message)
        with col_delete:
            if st.button("删除所选模型", use_container_width=True):
                if delete_model_config(user_id, selected["id"]):
                    st.success("已删除所选模型。")
                    st.rerun()
                st.error("删除失败：没有找到这条模型配置。")

    st.divider()
    st.subheader("保存新模型")
    with st.form("model_config_form"):
        provider = st.selectbox("Provider", PROVIDERS)
        defaults = PROVIDER_DEFAULTS.get(provider, PROVIDER_DEFAULTS["custom"])
        api_base = st.text_input(
            "API Base URL",
            value="" if provider == "mock" else defaults["api_base"],
            placeholder=defaults["api_base"] or "https://api.example.com/v1",
            help="填写 Base URL 即可，不需要手动加 /chat/completions；如果填了，系统也会自动修正。",
        )
        api_key = st.text_input("API Key", type="password")
        model_name = st.text_input("Model Name", value=defaults["model_name"])
        col_save, col_save_test = st.columns(2)
        submitted = col_save.form_submit_button("保存并设为当前模型", type="primary", use_container_width=True)
        submitted_test = col_save_test.form_submit_button("仅测试本次填写", use_container_width=True)
        normalized = normalize_model_config(provider, api_base, api_key, model_name)
        if submitted_test:
            ok, message = test_model_config(normalized)
            if ok:
                st.success(message)
            else:
                st.warning(message)
        if submitted:
            set_default_model_config(
                user_id,
                normalized["provider"],
                normalized["api_base"],
                normalized["api_key"],
                normalized["model_name"],
            )
            st.success("模型配置已保存。")
            st.rerun()

    st.caption(
        "提示：默认不读取系统代理环境变量，避免 Windows 错误代理导致 WinError 10013。"
        "如果必须使用系统代理，可在 .env 中设置 USE_SYSTEM_PROXY=true。"
    )
    st.caption("课程 Demo 中 API Key 明文保存在本地 SQLite；正式部署应使用加密存储或密钥管理服务。")
