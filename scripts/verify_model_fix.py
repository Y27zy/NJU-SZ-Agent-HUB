from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.llm.gateway import normalize_model_config
from src.llm.gateway import test_model_config
from src.llm.providers import OpenAICompatibleProvider


def assert_contains(path: Path, expected: str) -> None:
    text = path.read_text(encoding="utf-8")
    if expected not in text:
        raise AssertionError(f"{path} missing expected text: {expected}")


def assert_not_contains(path: Path, forbidden: str) -> None:
    text = path.read_text(encoding="utf-8")
    if forbidden in text:
        raise AssertionError(f"{path} still contains forbidden text: {forbidden}")


def main() -> None:
    ui_path = ROOT / "src" / "ui" / "model_settings_page.py"
    provider_path = ROOT / "src" / "llm" / "providers.py"

    assert_contains(ui_path, "MODEL_SETTINGS_UI_VERSION")
    assert_contains(ui_path, "选择已保存模型")
    assert_contains(ui_path, "st.radio")
    assert_contains(ui_path, "测试所选模型连接")
    assert_contains(ui_path, "删除所选模型")
    assert_not_contains(ui_path, "历史配置")
    assert_not_contains(ui_path, "保存为默认模型")
    assert_not_contains(ui_path, "st.selectbox(\"当前记录的模型\"")
    assert_not_contains(ui_path, "设为当前使用模型")

    assert_contains(provider_path, "session.trust_env = USE_SYSTEM_PROXY")
    assert_contains(provider_path, "json=payload")

    normalized = normalize_model_config(
        "deepseek",
        "https://api.deepseek.com/chat/completions",
        "fake-key",
        "deepseek-chat",
    )
    assert normalized["api_base"] == "https://api.deepseek.com", normalized

    provider = OpenAICompatibleProvider(
        model_name="deepseek-chat",
        api_base="https://api.deepseek.com/chat/completions",
        api_key="fake-key",
    )
    assert provider._chat_url() == "https://api.deepseek.com/chat/completions"

    ok, message = test_model_config(
        {
            "provider": "deepseek",
            "api_base": "https://api.deepseek.com",
            "api_key": "",
            "model_name": "deepseek-chat",
        }
    )
    assert not ok, message
    assert "API Key" in message, message

    print("Model settings fix verified.")
    print("UI marker: MODEL_SETTINGS_UI_VERSION")
    print("Old strings removed: 历史配置 / 保存为默认模型")
    print("HTTP client: json=payload, trust_env controlled by USE_SYSTEM_PROXY")
    print("DeepSeek base normalized: https://api.deepseek.com")
    print("DeepSeek without API Key is reported as invalid, not Mock.")


if __name__ == "__main__":
    main()
