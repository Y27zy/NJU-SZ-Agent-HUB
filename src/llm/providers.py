from typing import Any

import requests

from src.config import USE_SYSTEM_PROXY
from src.llm.base import BaseLLMProvider


class LLMProviderError(RuntimeError):
    """A user-facing model configuration or request error."""


class OpenAICompatibleProvider(BaseLLMProvider):
    def _chat_url(self) -> str:
        base = (self.api_base or "").strip().rstrip("/")
        return base if base.endswith("/chat/completions") else f"{base}/chat/completions"

    @staticmethod
    def _friendly_error(exc: Exception) -> str:
        if isinstance(exc, requests.exceptions.Timeout):
            return "模型请求超时，请检查 API Base、网络环境或稍后重试。"
        if isinstance(exc, requests.exceptions.ConnectionError):
            return "无法连接模型服务，请检查 API Base、代理、防火墙和当前 Python 环境的网络权限。"
        return str(exc)

    def chat(self, messages: list[dict], temperature: float = 0.7) -> str:
        if not (self.api_base and self.api_key and self.model_name):
            raise LLMProviderError("模型配置不完整，必须填写 API Base、API Key 和模型名称。")
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "User-Agent": "NJU-SZ-Agent-Hub/0.2",
        }
        payload: dict[str, Any] = {
            "model": self.model_name,
            "messages": messages,
            "temperature": temperature,
        }
        try:
            session = requests.Session()
            session.trust_env = USE_SYSTEM_PROXY
            response = session.post(self._chat_url(), headers=headers, json=payload, timeout=(15, 240))
            response.raise_for_status()
            data = response.json()
            answer = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            if not answer:
                raise LLMProviderError("模型返回了空内容，请检查模型名称和接口兼容性。")
            return answer
        except requests.exceptions.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else "unknown"
            body = exc.response.text[:500] if exc.response is not None else ""
            raise LLMProviderError(f"模型服务返回 HTTP {status}：{body}") from exc
        except LLMProviderError:
            raise
        except Exception as exc:
            raise LLMProviderError(self._friendly_error(exc)) from exc

    def test_connection(self) -> tuple[bool, str]:
        try:
            answer = self.chat(
                [
                    {"role": "system", "content": "You are a connection test assistant."},
                    {"role": "user", "content": "请只回复 OK。"},
                ],
                temperature=0,
            )
            return True, f"连接成功，模型返回：{answer[:100]}"
        except LLMProviderError as exc:
            return False, str(exc)


class QwenProvider(OpenAICompatibleProvider):
    """Qwen OpenAI-compatible endpoint."""


class KimiProvider(OpenAICompatibleProvider):
    """Kimi OpenAI-compatible endpoint."""


class DeepSeekProvider(OpenAICompatibleProvider):
    """DeepSeek OpenAI-compatible endpoint."""


class ZhipuProvider(OpenAICompatibleProvider):
    """Zhipu OpenAI-compatible endpoint."""
