import json
import unittest
from unittest.mock import Mock, patch

import requests

from src.llm.providers import LLMProviderError, OpenAICompatibleProvider


class OpenAICompatibleProviderTests(unittest.TestCase):
    @patch("src.llm.providers.requests.Session")
    def test_chat_assembles_streamed_sse_content(self, session_factory: Mock) -> None:
        response = Mock()
        response.headers = {"Content-Type": "text/event-stream; charset=utf-8"}
        response.iter_lines.return_value = [
            "data: " + json.dumps({"choices": [{"delta": {"content": "第一段"}}]}, ensure_ascii=False),
            "data: " + json.dumps({"choices": [{"delta": {"content": "第二段"}}]}, ensure_ascii=False),
            "data: [DONE]",
        ]
        session_factory.return_value.post.return_value = response
        provider = OpenAICompatibleProvider("model", "https://example.test/v1", "secret")

        answer = provider.chat([{"role": "user", "content": "hello"}])

        self.assertEqual(answer, "第一段第二段")
        _, kwargs = session_factory.return_value.post.call_args
        self.assertTrue(kwargs["stream"])
        self.assertTrue(kwargs["json"]["stream"])

    @patch("src.llm.providers.requests.Session")
    def test_stream_read_timeout_keeps_cause_for_checkpoint_diagnostics(self, session_factory: Mock) -> None:
        response = Mock()
        response.headers = {"Content-Type": "text/event-stream"}
        response.iter_lines.side_effect = requests.exceptions.ReadTimeout("read timed out")
        session_factory.return_value.post.return_value = response
        provider = OpenAICompatibleProvider("model", "https://example.test/v1", "secret")

        with self.assertRaises(LLMProviderError) as raised:
            provider.chat([{"role": "user", "content": "hello"}])

        self.assertIsInstance(raised.exception.__cause__, requests.exceptions.ReadTimeout)


if __name__ == "__main__":
    unittest.main()
