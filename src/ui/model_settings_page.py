import streamlit as st

from src.auth.auth_service import (
    activate_model_config,
    delete_model_config,
    get_default_model_config,
    list_model_configs,
    set_default_model_config,
)
from src.llm.gateway import PROVIDER_DEFAULTS, normalize_model_config, test_model_config


PROVIDERS = ["openai-compatible", "qwen", "kimi", "deepseek", "zhipu", "custom"]
PROVIDER_NAMES = {
    "openai-compatible": "OpenAI-compatible",
    "qwen": "Qwen 通义千问",
    "kimi": "Kimi",
    "deepseek": "DeepSeek",
    "zhipu": "智谱 GLM",
    "custom": "自定义服务",
}


def inject_subscription_theme() -> None:
    st.markdown('<span class="subscription-page-marker"></span>', unsafe_allow_html=True)
    st.markdown(
        """
        <style>
        .stApp:has(.subscription-page-marker) .block-container { max-width:var(--page-max) !important; }
        .stApp:has(.subscription-page-marker) .st-key-model_manager,
        .stApp:has(.subscription-page-marker) .st-key-subscription_preview { background:white;border:1px solid #e1e2e6;border-radius:6px;padding:22px; }
        .stApp:has(.subscription-page-marker) [data-testid="stForm"],
        .stApp:has(.subscription-page-marker) [data-testid="stExpander"] { background:#fcfcfd;border-color:#e1e2e6 !important; }
        .subscription-plans { display:grid;gap:10px;margin-top:18px; }
        .subscription-plan { padding:16px;border:1px solid #e1e2e6;background:#fcfcfd;border-radius:5px; }
        .subscription-plan.is-featured { border-color:#cbb8dc;background:#f5f0f8; }
        .subscription-plan strong { display:flex;justify-content:space-between;color:#20232a;font-size:16px; }
        .subscription-plan span { color:#686c75;font-size:13px;line-height:1.65; }
        .subscription-price { color:#5b2a86 !important;font-family:Georgia,serif;font-size:23px !important; }
        .subscription-demo-note { margin:0 0 16px;padding:10px 12px;border-left:3px solid #e7b93f;background:#fff9e8;color:#686c75;font-size:13px; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _model_label(config: dict) -> str:
    current = "当前使用" if config.get("is_default") else "可切换"
    provider = PROVIDER_NAMES.get(config["provider"], config["provider"])
    return f"{config['model_name']}  ·  {provider}  ·  {current}"


def _render_saved_models(user_id: int) -> None:
    configs = list_model_configs(user_id)
    current = get_default_model_config(user_id)
    st.markdown("### 我的模型")
    st.caption("阅读器、资料转换、论文研读和任务规划都会调用这里选中的模型。")
    if current:
        st.success(f"当前使用：{current['model_name']} · {PROVIDER_NAMES.get(current['provider'], current['provider'])}")
    else:
        st.warning("尚未配置模型。请先添加并通过连接测试。")
    if not configs:
        st.info("还没有保存的模型。下方添加后，它会出现在阅读工作区左下角。")
        return
    default_index = next((index for index, config in enumerate(configs) if config.get("is_default")), 0)
    selected = st.radio("选择模型", configs, index=default_index, format_func=_model_label, label_visibility="collapsed")
    use_col, test_col, delete_col = st.columns(3)
    if use_col.button("设为当前", disabled=bool(selected.get("is_default")), use_container_width=True):
        activate_model_config(user_id, selected["id"])
        st.rerun()
    if test_col.button("测试连接", use_container_width=True):
        ok, message = test_model_config(selected)
        st.success(message) if ok else st.error(message)
    if delete_col.button("删除模型", use_container_width=True):
        delete_model_config(user_id, selected["id"])
        st.rerun()


def _render_add_model(user_id: int) -> None:
    st.divider()
    st.markdown("### 添加新模型")
    st.caption("支持 OpenAI-compatible Chat Completions。保存前必须先通过真实连接测试。")
    provider = st.selectbox("服务商", PROVIDERS, format_func=lambda value: PROVIDER_NAMES[value], key="new_model_provider")
    defaults = PROVIDER_DEFAULTS[provider]
    with st.form("add_model_form"):
        api_base = st.text_input(
            "API Base URL",
            value=defaults["api_base"],
            placeholder="https://api.example.com/v1",
            key=f"new_model_api_base_{provider}",
        )
        key_col, name_col = st.columns([1.25, 1])
        with key_col:
            api_key = st.text_input("API Key", type="password", key=f"new_model_api_key_{provider}")
        with name_col:
            model_name = st.text_input("模型名称", value=defaults["model_name"], key=f"new_model_name_{provider}")
        save_col, test_col = st.columns(2)
        save = save_col.form_submit_button("测试并保存", type="primary", use_container_width=True)
        test = test_col.form_submit_button("仅测试连接", use_container_width=True)
    if save or test:
        normalized = normalize_model_config(provider, api_base, api_key, model_name)
        ok, message = test_model_config(normalized)
        if not ok:
            st.error(message)
        elif test:
            st.success(message)
        else:
            set_default_model_config(user_id, **normalized)
            st.success("模型已保存，并设为当前使用模型。")
            st.rerun()
    st.caption("API Key 当前明文保存在本机 SQLite；课程展示之外的正式部署必须改用加密存储。")


def _render_subscription_preview() -> None:
    st.markdown("### 平台订阅")
    st.markdown('<div class="subscription-demo-note">课程展示模块，未接入支付，也不会创建订单。</div>', unsafe_allow_html=True)
    st.markdown(
        """
        <div class="subscription-plans">
          <div class="subscription-plan is-featured">
            <strong><span>Free</span><span class="subscription-price">0 元</span></strong>
            <span>使用自己的 API<br>个人资料与模型配置保存在本地</span>
          </div>
          <div class="subscription-plan">
            <strong><span>Campus Plus</span><span class="subscription-price">19 / 月</span></strong>
            <span>展示：平台托管模型、每日体验额度、免填 API Key</span>
          </div>
          <div class="subscription-plan">
            <strong><span>Research</span><span class="subscription-price">49 / 月</span></strong>
            <span>展示：更高额度、论文批处理和长文档支持</span>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.metric("展示余额", "100 积分")
    st.button("订阅功能暂未开放", disabled=True, use_container_width=True)
    st.caption("未来方案：由服务端代理平台模型并扣减额度。本项目当前不包含支付和真实收费。")


def render_model_settings_page(user_id: int) -> None:
    inject_subscription_theme()
    st.markdown('<div class="page-eyebrow">MODELS & SUBSCRIPTION</div>', unsafe_allow_html=True)
    st.markdown("## 订阅与模型")
    st.caption("添加并切换自己的 API；右侧仅展示未来可能提供的平台托管方案。")
    manager, subscription = st.columns([0.69, 0.31], gap="large")
    with manager:
        with st.container(key="model_manager"):
            _render_saved_models(user_id)
            _render_add_model(user_id)
    with subscription:
        with st.container(key="subscription_preview"):
            _render_subscription_preview()
