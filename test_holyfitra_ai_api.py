from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from holyfitra_ai_api import (
    AIClient,
    AIConfigurationError,
    AIRequest,
    AnthropicProvider,
    GeminiProvider,
    OpenAICompatibleProvider,
    ProviderRegistry,
    _HTTP,
    extract_fitra_source,
    provider_status_json,
    write_validated_fitra,
)


class FakeResponse:
    def __init__(self, payload: dict, headers: dict[str, str] | None = None) -> None:
        self.payload = payload
        self.headers = headers or {}

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, _limit: int) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


class FakeOpener:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.urls: list[str] = []
        self.requests: list[object] = []

    def __call__(self, request: object, timeout: float) -> FakeResponse:
        self.requests.append((request, timeout))
        self.urls.append(request.full_url)  # type: ignore[attr-defined]
        return FakeResponse(self.payload, {"x-request-id": "req-test", "request-id": "anthropic-test"})


class AIProviderTests(unittest.TestCase):
    def test_request_validation(self) -> None:
        with self.assertRaises(AIConfigurationError):
            AIRequest("", ({"role": "user", "content": "x"},))
        with self.assertRaises(AIConfigurationError):
            AIRequest("model", (), max_tokens=1)
        with self.assertRaises(AIConfigurationError):
            AIRequest("model", ({"role": "user", "content": "x"},), temperature=3.0)

    def test_openai_chat_and_embedding_normalization(self) -> None:
        opener = FakeOpener({"model": "test-model", "choices": [{"message": {"content": "hello"}, "finish_reason": "stop"}], "usage": {"total_tokens": 3}})
        provider = OpenAICompatibleProvider("openai", base_url="https://example.test/v1", api_key_env="TEST_OPENAI_KEY", http=_HTTP(opener))
        with patch.dict(os.environ, {"TEST_OPENAI_KEY": "secret-value"}, clear=False):
            response = provider.chat(AIRequest("test-model", ({"role": "user", "content": "hi"},)))
        self.assertEqual(response.text, "hello")
        self.assertEqual(response.request_id, "req-test")
        self.assertIn("/chat/completions", opener.urls[0])
        self.assertNotIn("secret-value", opener.urls[0])

        embedding_opener = FakeOpener({"data": [{"index": 1, "embedding": [2.0]}, {"index": 0, "embedding": [1.0]}]})
        embedding_provider = OpenAICompatibleProvider("openai", base_url="https://example.test/v1", api_key_env="TEST_OPENAI_KEY", http=_HTTP(embedding_opener))
        with patch.dict(os.environ, {"TEST_OPENAI_KEY": "secret-value"}, clear=False):
            vectors = embedding_provider.embed(("a", "b"), model="embed")
        self.assertEqual(vectors, ((1.0,), (2.0,)))

    def test_gemini_chat_and_embedding(self) -> None:
        opener = FakeOpener({"candidates": [{"content": {"parts": [{"text": "gemini"}]}, "finishReason": "STOP"}], "usageMetadata": {"totalTokenCount": 4}})
        provider = GeminiProvider(http=_HTTP(opener))
        request = AIRequest("gemini-test", ({"role": "system", "content": "be concise"}, {"role": "user", "content": "hi"}))
        with patch.dict(os.environ, {"GEMINI_API_KEY": "gemini-secret"}, clear=False):
            response = provider.chat(request)
        self.assertEqual(response.text, "gemini")
        self.assertIn("generateContent", opener.urls[0])
        self.assertNotIn("gemini-secret", response.text)

        embedding_opener = FakeOpener({"embedding": {"values": [0.25, 0.5]}})
        embedding_provider = GeminiProvider(http=_HTTP(embedding_opener))
        with patch.dict(os.environ, {"GEMINI_API_KEY": "gemini-secret"}, clear=False):
            vectors = embedding_provider.embed(("a",), model="embedding-test")
        self.assertEqual(vectors, ((0.25, 0.5),))

    def test_anthropic_chat_normalization(self) -> None:
        opener = FakeOpener({"model": "claude-test", "content": [{"type": "text", "text": "claude"}], "stop_reason": "end_turn", "usage": {"input_tokens": 2}})
        provider = AnthropicProvider(http=_HTTP(opener))
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "anthropic-secret"}, clear=False):
            response = provider.chat(AIRequest("claude-test", ({"role": "user", "content": "hi"},)))
        self.assertEqual(response.text, "claude")
        self.assertEqual(response.request_id, "anthropic-test")
        self.assertIn("/v1/messages", opener.urls[0])
        self.assertNotIn("anthropic-secret", opener.urls[0])

    def test_local_loopback_and_remote_http_policy(self) -> None:
        _HTTP._validate_url("http://127.0.0.1:11434/v1/chat/completions")
        with self.assertRaises(AIConfigurationError):
            _HTTP._validate_url("http://remote.example/v1/chat/completions")

    def test_fitra_extraction_validates_before_atomic_write(self) -> None:
        source = extract_fitra_source("Here is code:\n```holyfitra\nmodule demo\nfn main() -> i32 { return 0 }\n```")
        self.assertIn("module demo", source)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "main.hf"
            calls: list[str] = []
            written = write_validated_fitra(source, output, lambda value: calls.append(value))
            self.assertEqual(written, output.read_text(encoding="utf-8"))
            self.assertEqual(calls, [source])

    def test_status_does_not_expose_credentials(self) -> None:
        with patch.dict(os.environ, {"OPENAI_API_KEY": "do-not-print"}, clear=False):
            statuses = provider_status_json(ProviderRegistry())
        rendered = json.dumps(statuses)
        self.assertNotIn("do-not-print", rendered)
        self.assertTrue(any(item["name"] == "openai" and item["configured"] for item in statuses))

    def test_client_generation_uses_provider(self) -> None:
        class FakeProvider(OpenAICompatibleProvider):
            def __init__(self) -> None:
                super().__init__("fake", base_url="https://example.test/v1", api_key_env=None, default_model="fake-model")

            def chat(self, request: AIRequest):
                from holyfitra_ai_api import AIResponse
                return AIResponse("fake", request.model, "```holyfitra\nmodule generated\nfn main() -> i32 { return 0 }\n```")

        response = AIClient(ProviderRegistry([FakeProvider()])).generate_fitra("write a hello program", provider="fake")
        self.assertIn("module generated", response.text)


if __name__ == "__main__":
    unittest.main()
