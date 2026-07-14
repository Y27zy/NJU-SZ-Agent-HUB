import time

from src.auth.auth_service import get_default_model_config
from src.llm.base import BaseLLMProvider
from src.llm.providers import (
    DeepSeekProvider,
    KimiProvider,
    LLMProviderError,
    OpenAICompatibleProvider,
    QwenProvider,
    ZhipuProvider,
)


PROVIDER_MAP = {
    "openai-compatible": OpenAICompatibleProvider,
    "qwen": QwenProvider,
    "kimi": KimiProvider,
    "deepseek": DeepSeekProvider,
    "zhipu": ZhipuProvider,
    "custom": OpenAICompatibleProvider,
}

PROVIDER_DEFAULTS = {
    "openai-compatible": {"api_base": "https://api.openai.com/v1", "model_name": "gpt-4.1-mini"},
    "qwen": {"api_base": "https://dashscope.aliyuncs.com/compatible-mode/v1", "model_name": "qwen-plus"},
    "kimi": {"api_base": "https://api.moonshot.cn/v1", "model_name": "moonshot-v1-8k"},
    "deepseek": {"api_base": "https://api.deepseek.com", "model_name": "deepseek-chat"},
    "zhipu": {"api_base": "https://open.bigmodel.cn/api/paas/v4", "model_name": "glm-4-flash"},
    "custom": {"api_base": "", "model_name": ""},
}

_TRANSIENT_MODEL_ERROR_MARKERS = (
    "无法连接模型服务",
    "模型请求超时",
    "connection",
    "timeout",
    "temporarily",
    "http 429",
    "http 500",
    "http 502",
    "http 503",
    "http 504",
)


def _is_transient_model_error(error: LLMProviderError) -> bool:
    """Return whether a model failure is appropriate for a short retry."""
    message = str(error).lower()
    return any(marker in message for marker in _TRANSIENT_MODEL_ERROR_MARKERS)


def build_provider(config: dict | None = None) -> BaseLLMProvider:
    if not config:
        raise LLMProviderError("尚未配置可用模型，请先在“订阅”页面添加并测试 API。")
    provider_name = (config.get("provider") or "").strip().lower()
    cls = PROVIDER_MAP.get(provider_name)
    if cls is None:
        raise LLMProviderError(f"不支持的模型服务商：{provider_name or '空'}。")
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
        raise LLMProviderError(f"当前模型配置缺少：{', '.join(missing_fields)}。")
    return cls(
        model_name=config["model_name"],
        api_base=config["api_base"],
        api_key=config["api_key"],
    )


def normalize_model_config(provider: str, api_base: str, api_key: str, model_name: str) -> dict:
    provider_name = (provider or "custom").strip().lower()
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
        return provider.test_connection()
    except LLMProviderError as exc:
        return False, str(exc)


def get_llm_for_user(user_id: int) -> BaseLLMProvider:
    return build_provider(get_default_model_config(user_id))


def chat_with_user_messages(
    user_id: int,
    messages: list[dict],
    temperature: float = 0.7,
    max_attempts: int = 3,
) -> str:
    """Call the selected real model with bounded retries for transient network failures."""
    provider = get_llm_for_user(user_id)
    last_error: LLMProviderError | None = None
    attempts = max(1, min(int(max_attempts), 6))
    for attempt in range(attempts):
        try:
            return provider.chat(messages, temperature=temperature)
        except LLMProviderError as exc:
            last_error = exc
            if not _is_transient_model_error(exc) or attempt == attempts - 1:
                raise
            # Spread retries out instead of immediately hammering an unavailable
            # endpoint. Long-document callers may request a larger bounded budget.
            time.sleep(min(30, 2 ** attempt))
    raise last_error or LLMProviderError("模型调用失败。")


def chat_with_user_model(
    user_id: int,
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.7,
    max_attempts: int = 3,
) -> str:
    return chat_with_user_messages(
        user_id,
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=temperature,
        max_attempts=max_attempts,
    )
