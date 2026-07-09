from typing import Any

import requests

from src.config import USE_SYSTEM_PROXY
from src.llm.base import BaseLLMProvider


class LLMProviderError(RuntimeError):
    pass


class MockLLMProvider(BaseLLMProvider):
    def chat(self, messages: list[dict], temperature: float = 0.7) -> str:
        user_text = next((m["content"] for m in reversed(messages) if m.get("role") == "user"), "")
        system_text = next((m["content"] for m in messages if m.get("role") == "system"), "")
        if "练习题" in user_text or "quiz" in user_text.lower():
            return (
                "## Mock 练习题\n\n"
                "### 练习题 1：PCA 的优化目标\n\n"
                "**题目**：PCA 希望找到投影方向 $\\mathbf{w}$，使投影后样本方差最大。"
                "请写出单位向量约束下的优化目标。\n\n"
                "**参考答案**：\n\n"
                "$$\n"
                "\\max_{\\mathbf{w}} \\; \\mathbf{w}^\\top S \\mathbf{w}, "
                "\\quad \\text{s.t. } \\|\\mathbf{w}\\|_2 = 1\n"
                "$$\n\n"
                "其中 $S$ 是样本协方差矩阵，最优方向对应最大特征值的特征向量。\n\n"
                "### 练习题 2：PCA 与 LDA 的区别\n\n"
                "**题目**：简述 PCA 与 LDA 的目标差异。\n\n"
                "**参考答案**：PCA 是无监督降维，关注总体方差最大；LDA 是有监督降维，"
                "关注类间距离尽可能大、类内距离尽可能小。"
            )
        if "计划" in user_text or "todo" in system_text.lower():
            return (
                "【Mock 计划】\n"
                "上午：处理最高优先级任务并拆分子任务。\n"
                "下午：完成资料阅读和作业推进。\n"
                "晚上：复盘进度，更新明日安排。"
            )
        if "论文" in user_text or "paper" in system_text.lower():
            return (
                "【Mock 论文分析】这篇论文可从研究问题、方法设计、实验设置、贡献和局限五个角度阅读。"
                "建议先读摘要和图表，再看方法细节，最后整理复现 checklist。"
            )
        return (
            "【MockLLMProvider 离线回答】我会根据当前上下文给出一个课程项目 Demo 级回答。\n\n"
            f"你的问题：{user_text[:300]}\n\n"
            "如果配置真实 API Base、API Key 和模型名，本模块会自动切换到真实大模型调用。"
        )


class OpenAICompatibleProvider(BaseLLMProvider):
    def _chat_url(self) -> str:
        base = (self.api_base or "").strip().rstrip("/")
        if base.endswith("/chat/completions"):
            return base
        return f"{base}/chat/completions"

    def _friendly_error(self, exc: Exception) -> str:
        if isinstance(exc, requests.exceptions.Timeout):
            return "请求超时。请检查 API Base 是否正确，或稍后重试。"
        if isinstance(exc, requests.exceptions.ConnectionError):
            return (
                "无法连接到模型服务。常见原因是 API Base 写错、系统代理/防火墙拦截，"
                "或当前 Python 环境没有外网访问权限。"
            )
        return str(exc)

    def chat(self, messages: list[dict], temperature: float = 0.7) -> str:
        if not (self.api_base and self.api_key and self.model_name):
            return MockLLMProvider(self.model_name).chat(messages, temperature)
        url = self._chat_url()
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "User-Agent": "NJU-SZ-Agent-Hub/0.1",
        }
        payload: dict[str, Any] = {
            "model": self.model_name,
            "messages": messages,
            "temperature": temperature,
        }
        try:
            session = requests.Session()
            session.trust_env = USE_SYSTEM_PROXY
            resp = session.post(url, headers=headers, json=payload, timeout=(10, 90))
            resp.raise_for_status()
            data = resp.json()
            return data.get("choices", [{}])[0].get("message", {}).get("content", "")
        except requests.exceptions.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else "unknown"
            body = exc.response.text[:500] if exc.response is not None else ""
            raise LLMProviderError(f"模型服务返回 HTTP {status}：{body}") from exc
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
            if answer:
                return True, f"连接成功，模型返回：{answer[:100]}"
            return False, "连接成功但模型返回为空，请检查模型名称是否正确。"
        except LLMProviderError as exc:
            return False, str(exc)


class QwenProvider(OpenAICompatibleProvider):
    """Qwen-compatible endpoint using OpenAI-style chat completions."""


class KimiProvider(OpenAICompatibleProvider):
    """Kimi-compatible endpoint using OpenAI-style chat completions."""


class DeepSeekProvider(OpenAICompatibleProvider):
    """DeepSeek-compatible endpoint using OpenAI-style chat completions."""


class ZhipuProvider(OpenAICompatibleProvider):
    """Zhipu-compatible endpoint using OpenAI-style chat completions."""
