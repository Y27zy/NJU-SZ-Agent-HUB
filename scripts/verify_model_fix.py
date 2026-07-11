from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.llm.gateway import normalize_model_config, test_model_config
from src.llm.providers import OpenAICompatibleProvider


def main() -> None:
    source_files = [
        ROOT / "src" / "llm" / "gateway.py",
        ROOT / "src" / "llm" / "providers.py",
        ROOT / "src" / "ui" / "model_settings_page.py",
    ]
    for path in source_files:
        assert "MockLLMProvider" not in path.read_text(encoding="utf-8"), path

    normalized = normalize_model_config(
        "deepseek", "https://api.deepseek.com/chat/completions", "fake-key", "deepseek-chat"
    )
    assert normalized["api_base"] == "https://api.deepseek.com"
    provider = OpenAICompatibleProvider("deepseek-chat", "https://api.deepseek.com/chat/completions", "fake-key")
    assert provider._chat_url() == "https://api.deepseek.com/chat/completions"
    ok, message = test_model_config({**normalized, "api_key": ""})
    assert not ok and "API Key" in message
    print("Model gateway verified: no Mock fallback, URL normalized, missing key rejected.")


if __name__ == "__main__":
    main()
