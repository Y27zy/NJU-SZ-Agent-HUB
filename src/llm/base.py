from abc import ABC, abstractmethod


class BaseLLMProvider(ABC):
    def __init__(self, model_name: str = "mock-agent", api_base: str = "", api_key: str = "") -> None:
        self.model_name = model_name
        self.api_base = api_base.rstrip("/") if api_base else ""
        self.api_key = api_key

    @abstractmethod
    def chat(self, messages: list[dict], temperature: float = 0.7) -> str:
        """Return a chat completion string."""
