"""Provider-neutral AI API access for Holy Fitra.

The module intentionally uses only Python's standard library so it works in
Termux without installing provider SDKs. API keys are read from environment
variables and are never included in diagnostics or URLs except where Gemini's
REST API requires a query parameter internally.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import re
import time
from typing import Any, Callable, Iterable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen


MAX_REQUEST_BYTES = 8 * 1024 * 1024
MAX_RESPONSE_BYTES = 16 * 1024 * 1024
DEFAULT_TIMEOUT_SECONDS = 90.0


class AIProviderError(RuntimeError):
    """A provider request failed or returned an invalid response."""


class AICredentialError(AIProviderError):
    """A configured provider does not have the required credential."""


class AIConfigurationError(ValueError):
    """A request or provider configuration is invalid."""


@dataclass(frozen=True)
class AIRequest:
    model: str
    messages: tuple[dict[str, Any], ...]
    temperature: float | None = 0.2
    max_tokens: int = 1024
    response_format: dict[str, Any] | None = None
    tools: tuple[dict[str, Any], ...] = ()
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.model or not isinstance(self.model, str):
            raise AIConfigurationError("AI model must be a non-empty string")
        if not self.messages or any(not isinstance(message, dict) for message in self.messages):
            raise AIConfigurationError("AI messages must be non-empty objects")
        if self.temperature is not None and (not isinstance(self.temperature, (int, float)) or not 0.0 <= float(self.temperature) <= 2.0):
            raise AIConfigurationError("temperature must be between 0 and 2")
        if not isinstance(self.max_tokens, int) or isinstance(self.max_tokens, bool) or not 1 <= self.max_tokens <= 1_000_000:
            raise AIConfigurationError("max_tokens must be between 1 and 1000000")
        if not isinstance(self.timeout_seconds, (int, float)) or not 0.1 <= float(self.timeout_seconds) <= 600.0:
            raise AIConfigurationError("timeout_seconds must be between 0.1 and 600")


@dataclass(frozen=True)
class AIResponse:
    provider: str
    model: str
    text: str
    finish_reason: str | None = None
    request_id: str | None = None
    usage: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.provider or not self.model or not isinstance(self.text, str):
            raise AIConfigurationError("invalid AI response")


@dataclass(frozen=True)
class ProviderStatus:
    name: str
    kind: str
    configured: bool
    endpoint: str
    credential_env: str | None
    default_model: str
    note: str


class _HTTP:
    def __init__(self, opener: Callable[..., Any] = urlopen) -> None:
        self.opener = opener

    @staticmethod
    def _validate_url(url: str) -> None:
        allow_http = os.environ.get("HOLYFITRA_AI_ALLOW_HTTP") == "1"
        parsed = urlsplit(url)
        loopback = parsed.hostname in {"127.0.0.1", "localhost", "::1"}
        if not (parsed.scheme == "https" or (parsed.scheme == "http" and (allow_http or loopback))):
            raise AIConfigurationError("AI endpoints must use HTTPS; loopback HTTP is allowed for local development")

    def post_json(self, url: str, payload: dict[str, Any], headers: Mapping[str, str], *, timeout: float) -> tuple[dict[str, Any], dict[str, str]]:
        self._validate_url(url)
        encoded = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        if len(encoded) > MAX_REQUEST_BYTES:
            raise AIConfigurationError("AI request exceeds the 8 MiB safety limit")
        request = Request(url, data=encoded, method="POST")
        request.add_header("Content-Type", "application/json")
        request.add_header("Accept", "application/json")
        request.add_header("User-Agent", "holyfitra-ai/1")
        for name, value in headers.items():
            request.add_header(name, value)
        try:
            with self.opener(request, timeout=float(timeout)) as response:
                body = response.read(MAX_RESPONSE_BYTES + 1)
                response_headers = {str(key).lower(): str(value) for key, value in response.headers.items()}
        except HTTPError as error:
            body = error.read(MAX_RESPONSE_BYTES + 1)
            detail = body[:4096].decode("utf-8", errors="replace")
            raise AIProviderError(f"AI provider HTTP {error.code}: {detail}") from error
        except (URLError, TimeoutError, OSError) as error:
            raise AIProviderError(f"AI provider connection failed: {error}") from error
        if len(body) > MAX_RESPONSE_BYTES:
            raise AIProviderError("AI provider response exceeds the 16 MiB safety limit")
        try:
            decoded = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise AIProviderError("AI provider returned non-JSON data") from error
        if not isinstance(decoded, dict):
            raise AIProviderError("AI provider response must be a JSON object")
        return decoded, response_headers


def _credential(name: str, *, required: bool = True) -> str | None:
    value = os.environ.get(name, "").strip()
    if value:
        return value
    if required:
        raise AICredentialError(f"missing {name}; export it before calling the provider")
    return None


def _content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "".join(parts)
    return ""


def _messages_text(messages: Iterable[dict[str, Any]]) -> str:
    return "\n".join(f"{message.get('role', 'user')}: {_content_to_text(message.get('content', ''))}" for message in messages)


class AIProvider:
    name = "provider"
    kind = "generic"
    endpoint = ""
    credential_env: str | None = None
    default_model = ""

    def __init__(self, http: _HTTP | None = None) -> None:
        self.http = http or _HTTP()

    def status(self) -> ProviderStatus:
        configured = bool(self.credential_env is None or os.environ.get(self.credential_env, "").strip())
        note = "local endpoint; not probed" if self.credential_env is None else ("credential configured" if configured else f"set {self.credential_env}")
        return ProviderStatus(self.name, self.kind, configured, self.endpoint, self.credential_env, self.default_model, note)

    def chat(self, request: AIRequest) -> AIResponse:
        raise NotImplementedError

    def embed(self, texts: tuple[str, ...], *, model: str, timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS) -> tuple[tuple[float, ...], ...]:
        raise AIProviderError(f"provider {self.name} does not implement embeddings")


class OpenAICompatibleProvider(AIProvider):
    kind = "openai-compatible"

    def __init__(self, name: str = "openai", *, base_url: str | None = None, api_key_env: str | None = None, default_model: str | None = None, http: _HTTP | None = None) -> None:
        super().__init__(http)
        self.name = name
        self.base_url = (base_url or os.environ.get(f"HOLYFITRA_{name.upper()}_BASE_URL") or ("https://api.openai.com/v1" if name == "openai" else "http://127.0.0.1:11434/v1")).rstrip("/")
        self.endpoint = self.base_url
        self.credential_env = api_key_env or ("OPENAI_API_KEY" if name == "openai" else None)
        self.default_model = default_model or os.environ.get(f"HOLYFITRA_{name.upper()}_MODEL", "gpt-4o-mini" if name == "openai" else "llama3.2")

    def _headers(self) -> dict[str, str]:
        headers = {}
        if self.credential_env:
            key = _credential(self.credential_env)
            headers["Authorization"] = f"Bearer {key}"
        return headers

    def chat(self, request: AIRequest) -> AIResponse:
        payload: dict[str, Any] = {"model": request.model, "messages": list(request.messages), "max_tokens": request.max_tokens}
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if request.response_format is not None:
            payload["response_format"] = request.response_format
        if request.tools:
            payload["tools"] = list(request.tools)
        response, headers = self.http.post_json(f"{self.base_url}/chat/completions", payload, self._headers(), timeout=request.timeout_seconds)
        try:
            choice = response["choices"][0]
            message = choice["message"]
            text = _content_to_text(message.get("content", ""))
            finish_reason = choice.get("finish_reason")
        except (KeyError, IndexError, TypeError) as error:
            raise AIProviderError("OpenAI-compatible response has no choices[0].message.content") from error
        return AIResponse(self.name, str(response.get("model", request.model)), text, finish_reason, headers.get("x-request-id"), dict(response.get("usage", {})), response)

    def embed(self, texts: tuple[str, ...], *, model: str, timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS) -> tuple[tuple[float, ...], ...]:
        if not texts or any(not isinstance(text, str) or not text for text in texts):
            raise AIConfigurationError("embedding inputs must be non-empty strings")
        response, _ = self.http.post_json(f"{self.base_url}/embeddings", {"model": model, "input": list(texts)}, self._headers(), timeout=timeout_seconds)
        try:
            ordered = sorted(response["data"], key=lambda item: int(item["index"]))
            return tuple(tuple(float(value) for value in item["embedding"]) for item in ordered)
        except (KeyError, TypeError, ValueError) as error:
            raise AIProviderError("OpenAI-compatible embedding response is invalid") from error


class GeminiProvider(AIProvider):
    name = "gemini"
    kind = "gemini"
    endpoint = "https://generativelanguage.googleapis.com/v1beta"
    credential_env = "GEMINI_API_KEY"
    default_model = "gemini-2.0-flash"

    @staticmethod
    def _contents(messages: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
        contents: list[dict[str, Any]] = []
        for message in messages:
            role = "model" if message.get("role") == "assistant" else "user"
            content = message.get("content", "")
            if isinstance(content, str):
                parts = [{"text": content}]
            elif isinstance(content, list):
                parts = []
                for item in content:
                    if isinstance(item, str):
                        parts.append({"text": item})
                    elif isinstance(item, dict):
                        if "text" in item:
                            parts.append({"text": str(item["text"])})
                        elif "inline_data" in item:
                            parts.append({"inlineData": item["inline_data"]})
            else:
                raise AIConfigurationError("Gemini message content must be text or parts")
            contents.append({"role": role, "parts": parts})
        return contents

    def chat(self, request: AIRequest) -> AIResponse:
        key = _credential(self.credential_env or "GEMINI_API_KEY")
        system_parts = [{"text": str(message.get("content", ""))} for message in request.messages if message.get("role") == "system"]
        messages = [message for message in request.messages if message.get("role") != "system"]
        payload: dict[str, Any] = {"contents": self._contents(messages), "generationConfig": {"maxOutputTokens": request.max_tokens}}
        if request.temperature is not None:
            payload["generationConfig"]["temperature"] = request.temperature
        if request.response_format and request.response_format.get("type") in {"json_object", "json"}:
            payload["generationConfig"]["responseMimeType"] = "application/json"
        if system_parts:
            payload["systemInstruction"] = {"parts": system_parts}
        if request.tools:
            payload["tools"] = [{"functionDeclarations": list(request.tools)}]
        url = f"{self.endpoint}/models/{quote(request.model, safe='')}:generateContent?key={quote(key, safe='')}"
        response, headers = self.http.post_json(url, payload, {}, timeout=request.timeout_seconds)
        try:
            candidate = response["candidates"][0]
            text = _content_to_text(candidate["content"]["parts"])
            finish_reason = candidate.get("finishReason")
        except (KeyError, IndexError, TypeError) as error:
            feedback = response.get("promptFeedback", {})
            raise AIProviderError(f"Gemini response has no text candidate: {feedback}") from error
        return AIResponse(self.name, request.model, text, finish_reason, headers.get("x-request-id"), dict(response.get("usageMetadata", {})), response)

    def embed(self, texts: tuple[str, ...], *, model: str, timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS) -> tuple[tuple[float, ...], ...]:
        key = _credential(self.credential_env or "GEMINI_API_KEY")
        vectors: list[tuple[float, ...]] = []
        for text in texts:
            if not text:
                raise AIConfigurationError("embedding inputs must be non-empty strings")
            url = f"{self.endpoint}/models/{quote(model, safe='')}:embedContent?key={quote(key, safe='')}"
            response, _ = self.http.post_json(url, {"content": {"parts": [{"text": text}]}}, {}, timeout=timeout_seconds)
            try:
                vectors.append(tuple(float(value) for value in response["embedding"]["values"]))
            except (KeyError, TypeError, ValueError) as error:
                raise AIProviderError("Gemini embedding response is invalid") from error
        return tuple(vectors)


class AnthropicProvider(AIProvider):
    name = "anthropic"
    kind = "anthropic"
    endpoint = "https://api.anthropic.com"
    credential_env = "ANTHROPIC_API_KEY"
    default_model = "claude-3-5-sonnet-latest"

    def chat(self, request: AIRequest) -> AIResponse:
        key = _credential(self.credential_env or "ANTHROPIC_API_KEY")
        system = "\n\n".join(_content_to_text(message.get("content", "")) for message in request.messages if message.get("role") == "system")
        messages = [{"role": message.get("role", "user"), "content": message.get("content", "")} for message in request.messages if message.get("role") != "system"]
        payload: dict[str, Any] = {"model": request.model, "max_tokens": request.max_tokens, "messages": messages}
        if system:
            payload["system"] = system
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if request.tools:
            payload["tools"] = list(request.tools)
        response, headers = self.http.post_json(f"{self.endpoint}/v1/messages", payload, {"x-api-key": key, "anthropic-version": "2023-06-01"}, timeout=request.timeout_seconds)
        try:
            text = _content_to_text(response["content"])
        except (KeyError, TypeError) as error:
            raise AIProviderError("Anthropic response has no content") from error
        return AIResponse(self.name, str(response.get("model", request.model)), text, response.get("stop_reason"), headers.get("request-id"), dict(response.get("usage", {})), response)


class ProviderRegistry:
    """Registry for direct providers, OpenAI-compatible gateways, and local models."""

    def __init__(self, providers: Iterable[AIProvider] | None = None) -> None:
        if providers is None:
            providers = (
                OpenAICompatibleProvider("openai"),
                GeminiProvider(),
                AnthropicProvider(),
                OpenAICompatibleProvider("openrouter", base_url=os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"), api_key_env="OPENROUTER_API_KEY", default_model=os.environ.get("OPENROUTER_MODEL", "openai/gpt-4o-mini")),
                OpenAICompatibleProvider("ollama", base_url=os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434/v1"), default_model=os.environ.get("OLLAMA_MODEL", "llama3.2")),
                OpenAICompatibleProvider("lmstudio", base_url=os.environ.get("LMSTUDIO_BASE_URL", "http://127.0.0.1:1234/v1"), default_model=os.environ.get("LMSTUDIO_MODEL", "local-model")),
            )
        self._providers = {provider.name: provider for provider in providers}

    def get(self, name: str) -> AIProvider:
        try:
            return self._providers[name]
        except KeyError as error:
            raise AIConfigurationError(f"unknown AI provider: {name}; available: {', '.join(sorted(self._providers))}") from error

    def statuses(self) -> tuple[ProviderStatus, ...]:
        return tuple(self._providers[name].status() for name in sorted(self._providers))

    def select(self, name: str | None = None) -> AIProvider:
        requested = name or os.environ.get("HOLYFITRA_AI_PROVIDER", "").strip()
        if requested:
            return self.get(requested)
        for provider in self._providers.values():
            if provider.status().configured and (provider.credential_env is not None or provider.name in {"ollama", "lmstudio"}):
                return provider
        raise AICredentialError("no configured AI provider; set HOLYFITRA_AI_PROVIDER and its API key, or start a local Ollama/LM Studio endpoint")


class AIClient:
    def __init__(self, registry: ProviderRegistry | None = None) -> None:
        self.registry = registry or ProviderRegistry()

    def chat(self, prompt: str, *, provider: str | None = None, model: str | None = None, system: str | None = None, temperature: float | None = 0.2, max_tokens: int = 1024, response_format: dict[str, Any] | None = None, tools: tuple[dict[str, Any], ...] = (), timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS) -> AIResponse:
        if not prompt or not prompt.strip():
            raise AIConfigurationError("prompt must be non-empty")
        selected = self.registry.select(provider)
        messages: list[dict[str, Any]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        request = AIRequest(model or selected.default_model, tuple(messages), temperature, max_tokens, response_format, tools, timeout_seconds)
        return selected.chat(request)

    def embed(self, texts: Iterable[str], *, provider: str | None = None, model: str | None = None, timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS) -> tuple[tuple[float, ...], ...]:
        selected = self.registry.select(provider)
        values = tuple(texts)
        return selected.embed(values, model=model or ("text-embedding-3-small" if selected.name in {"openai", "openrouter"} else "text-embedding-004"), timeout_seconds=timeout_seconds)

    def generate_fitra(self, request: str, *, provider: str | None = None, model: str | None = None, max_tokens: int = 4096) -> AIResponse:
        system = (
            "You are a Holy Fitra programming assistant. Return only one complete Holy Fitra source file in a fenced ```holyfitra block. "
            "Use the currently supported native subset: module declarations, i32/i64/bool/void, typed functions, locals, arithmetic, comparisons, if/else, while, direct calls, and returns. "
            "The executable entry point must be fn main() -> i32 with no parameters. Do not invent imports, libraries, or unsupported tensor syntax."
        )
        return self.chat(request, provider=provider, model=model, system=system, temperature=0.1, max_tokens=max_tokens)


def extract_fitra_source(text: str) -> str:
    matches = re.findall(r"```(?:holyfitra|fitra|hf)?\s*\n(.*?)```", text, flags=re.IGNORECASE | re.DOTALL)
    source = matches[0] if matches else text
    source = source.strip()
    if not source:
        raise AIProviderError("AI returned empty Fitra source")
    return source + "\n"


def write_validated_fitra(text: str, output: Path, validator: Callable[[str], Any]) -> str:
    source = extract_fitra_source(text)
    validator(source)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.tmp")
    temporary.write_text(source, encoding="utf-8")
    os.replace(temporary, output)
    return source


def provider_status_json(registry: ProviderRegistry | None = None) -> list[dict[str, Any]]:
    return [
        {
            "name": status.name,
            "kind": status.kind,
            "configured": status.configured,
            "endpoint": status.endpoint,
            "credential_env": status.credential_env,
            "default_model": status.default_model,
            "note": status.note,
        }
        for status in (registry or ProviderRegistry()).statuses()
    ]


__all__ = [
    "AIClient",
    "AIConfigurationError",
    "AICredentialError",
    "AIProviderError",
    "AIRequest",
    "AIResponse",
    "AIProvider",
    "AnthropicProvider",
    "GeminiProvider",
    "OpenAICompatibleProvider",
    "ProviderRegistry",
    "ProviderStatus",
    "extract_fitra_source",
    "provider_status_json",
    "write_validated_fitra",
]
