from src.auth.auth_service import get_default_model_config
from src.config import DEFAULT_MODEL, DEFAULT_PROVIDER
from src.llm.base import BaseLLMProvider
from src.llm.providers import (
    DeepSeekProvider,
    KimiProvider,
    LLMProviderError,
    MockLLMProvider,
    OpenAICompatibleProvider,
    QwenProvider,
    ZhipuProvider,
)


PROVIDER_MAP = {
    "mock": MockLLMProvider,
    "openai-compatible": OpenAICompatibleProvider,
    "qwen": QwenProvider,
    "kimi": KimiProvider,
    "deepseek": DeepSeekProvider,
    "zhipu": ZhipuProvider,
    "custom": OpenAICompatibleProvider,
}

PROVIDER_DEFAULTS = {
    "mock": {"api_base": "", "model_name": "mock-agent"},
    "openai-compatible": {"api_base": "https://api.example.com/v1", "model_name": "gpt-compatible-model"},
    "qwen": {"api_base": "https://dashscope.aliyuncs.com/compatible-mode/v1", "model_name": "qwen-plus"},
    "kimi": {"api_base": "https://api.moonshot.cn/v1", "model_name": "moonshot-v1-8k"},
    "deepseek": {"api_base": "https://api.deepseek.com", "model_name": "deepseek-chat"},
    "zhipu": {"api_base": "https://open.bigmodel.cn/api/paas/v4", "model_name": "glm-4-flash"},
    "custom": {"api_base": "", "model_name": ""},
}


def build_provider(config: dict | None = None) -> BaseLLMProvider:
    if not config:
        return MockLLMProvider(DEFAULT_MODEL)
    provider_name = (config.get("provider") or DEFAULT_PROVIDER).lower()
    cls = PROVIDER_MAP.get(provider_name, OpenAICompatibleProvider)
    if provider_name == "mock":
        return MockLLMProvider(config.get("model_name") or DEFAULT_MODEL)
    missing_fields = [
        label
        for label, value in {
            "API Base URL": config.get("api_base"),
            "API Key": config.get("api_key"),
            "Model Name": config.get("model_name"),
        }.items()
        if not value
    ]
    if missing_fields:
        raise LLMProviderError(f"当前选择的是真实模型 {provider_name}，但配置缺少：{', '.join(missing_fields)}。")
    return cls(
        model_name=config.get("model_name") or DEFAULT_MODEL,
        api_base=config.get("api_base") or "",
        api_key=config.get("api_key") or "",
    )


def normalize_model_config(provider: str, api_base: str, api_key: str, model_name: str) -> dict:
    provider_name = (provider or DEFAULT_PROVIDER).strip().lower()
    defaults = PROVIDER_DEFAULTS.get(provider_name, PROVIDER_DEFAULTS["custom"])
    normalized_base = (api_base or defaults["api_base"]).strip().rstrip("/")
    if normalized_base.endswith("/chat/completions"):
        normalized_base = normalized_base[: -len("/chat/completions")]
    return {
        "provider": provider_name,
        "api_base": normalized_base,
        "api_key": (api_key or "").strip(),
        "model_name": (model_name or defaults["model_name"]).strip(),
    }


def test_model_config(config: dict) -> tuple[bool, str]:
    try:
        provider = build_provider(config)
        if isinstance(provider, MockLLMProvider):
            return True, "MockLLMProvider 可用。当前配置不会调用真实 API。"
        test_method = getattr(provider, "test_connection", None)
        if test_method:
            return test_method()
        provider.chat([{"role": "user", "content": "请只回复 OK。"}], temperature=0)
        return True, "连接成功。"
    except LLMProviderError as exc:
        return False, str(exc)


def get_llm_for_user(user_id: int) -> BaseLLMProvider:
    return build_provider(get_default_model_config(user_id))


def chat_with_user_model(user_id: int, system_prompt: str, user_prompt: str, temperature: float = 0.7) -> str:
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    try:
        provider = get_llm_for_user(user_id)
        return provider.chat(messages, temperature=temperature)
    except LLMProviderError as exc:
        fallback = MockLLMProvider(DEFAULT_MODEL).chat(messages, temperature=temperature)
        return (
            "真实模型连接失败，已自动切换到离线 MockLLMProvider，保证 Demo 可以继续运行。\n\n"
            f"失败原因：{exc}\n\n"
            f"{fallback}"
        )
