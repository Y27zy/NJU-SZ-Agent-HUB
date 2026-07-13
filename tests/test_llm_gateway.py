import unittest
from unittest.mock import Mock, patch

from src.llm.gateway import chat_with_user_messages
from src.llm.providers import LLMProviderError


class LLMGatewayRetryTests(unittest.TestCase):
    @patch("src.llm.gateway.time.sleep")
    @patch("src.llm.gateway.get_llm_for_user")
    def test_retries_transient_connection_error(self, mock_provider_factory: Mock, mock_sleep: Mock) -> None:
        provider = Mock()
        provider.chat.side_effect = [
            LLMProviderError("无法连接模型服务，请稍后重试。"),
            "OK",
        ]
        mock_provider_factory.return_value = provider

        answer = chat_with_user_messages(1, [{"role": "user", "content": "hello"}])

        self.assertEqual(answer, "OK")
        self.assertEqual(provider.chat.call_count, 2)
        mock_sleep.assert_called_once_with(1)

    @patch("src.llm.gateway.time.sleep")
    @patch("src.llm.gateway.get_llm_for_user")
    def test_does_not_retry_configuration_error(self, mock_provider_factory: Mock, mock_sleep: Mock) -> None:
        provider = Mock()
        provider.chat.side_effect = LLMProviderError("模型配置不完整")
        mock_provider_factory.return_value = provider

        with self.assertRaises(LLMProviderError):
            chat_with_user_messages(1, [{"role": "user", "content": "hello"}])

        self.assertEqual(provider.chat.call_count, 1)
        mock_sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()
