# Holy Fitra AI Development System

Holy Fitra now includes a provider-neutral AI API layer in `holyfitra_ai_api.py`. It lets the compiler driver talk to hosted models, OpenAI-compatible gateways, and local models without installing provider SDKs. The implementation uses Python’s standard-library HTTP client, so the same path works on Linux and Termux.

## Supported provider families

| Provider | API surface | Credential or endpoint | Default model behavior |
|---|---|---|---|
| OpenAI | OpenAI-compatible chat completions and embeddings | `OPENAI_API_KEY` | `gpt-4o-mini` |
| OpenRouter | OpenAI-compatible chat completions and embeddings | `OPENROUTER_API_KEY`, optional `OPENROUTER_BASE_URL` | `openai/gpt-4o-mini` |
| Gemini | `generateContent` and `embedContent` REST APIs | `GEMINI_API_KEY` | `gemini-2.0-flash` and `text-embedding-004` |
| Anthropic | Claude Messages API | `ANTHROPIC_API_KEY` | `claude-3-5-sonnet-latest` |
| Ollama | Local OpenAI-compatible endpoint | `OLLAMA_BASE_URL`, default `http://127.0.0.1:11434/v1` | `llama3.2` |
| LM Studio | Local OpenAI-compatible endpoint | `LMSTUDIO_BASE_URL`, default `http://127.0.0.1:1234/v1` | `local-model` |

The provider registry is deliberately extensible. Any service that implements the OpenAI-compatible `/chat/completions` and `/embeddings` shapes can be registered with a base URL and credential environment variable without changing the Fitra compiler.

## CLI usage

List provider configuration without printing secret values:

```bash
holyfitra ai providers
```

Send a prompt to a selected provider:

```bash
export OPENAI_API_KEY='your-key'
holyfitra ai chat 'Explain this Holy Fitra function in plain language.' \
  --provider openai --model gpt-4o-mini
```

Use Gemini or Claude by changing the provider and environment variable:

```bash
export GEMINI_API_KEY='your-key'
holyfitra ai chat 'Design a bounded parser test.' --provider gemini

export ANTHROPIC_API_KEY='your-key'
holyfitra ai chat 'Review this Fitra error message.' --provider anthropic
```

Use a local model in Termux or Linux. Loopback HTTP is allowed; remote HTTP endpoints are rejected unless explicitly enabled for development:

```bash
export OLLAMA_MODEL='llama3.2'
holyfitra ai chat 'Write a small checked example.' --provider ollama
```

Create embeddings for retrieval or the existing evidence/memory layer:

```bash
holyfitra ai embed 'compiler cache integrity' 'Android Bionic portability' \
  --provider openai --model text-embedding-3-small
```

## AI-assisted Fitra generation

The generation command asks the model for the currently supported native scalar subset, extracts a Fitra code block, parses it with the real native parser, validates it, and only then writes the output file atomically:

```bash
holyfitra ai generate-fitra \
  'Create a program that returns 42 from main.' \
  --provider openai \
  --model gpt-4o-mini \
  --output generated/main.hf

holyfitra check generated/main.hf
holyfitra build generated/main.hf -o generated/main
```

A model response that is empty, malformed, or outside the current native subset is rejected before it can overwrite the requested file. This is intentionally safer than executing arbitrary model output.

## Python API

Fitra tools can use the same provider layer directly:

```python
from holyfitra_ai_api import AIClient

client = AIClient()
answer = client.chat(
    "Summarize this compiler diagnostic.",
    provider="gemini",
    model="gemini-2.0-flash",
    system="Be concise and preserve error codes.",
)
print(answer.text)
```

The normalized response includes the provider, model, text, finish reason, request ID, usage metadata, and raw provider response. Raw responses are returned to the caller for debugging but are not written to disk by the CLI.

## Safety and operational rules

API keys are read from environment variables and are not printed by `holyfitra ai providers`. Remote providers require HTTPS. Loopback HTTP is permitted for local Ollama and LM Studio because those services normally bind to a local address; arbitrary remote HTTP requires the explicit `HOLYFITRA_AI_ALLOW_HTTP=1` override.

Requests and responses are bounded at 8 MiB and 16 MiB respectively. Timeouts are bounded between 0.1 and 600 seconds. Provider errors are converted into actionable CLI errors. The AI layer does not automatically execute model-supplied tools, write arbitrary files, or run generated code.

The existing `ToolRegistry`, capability grants, evidence ledger, claim verifier, and bounded `AgentRuntime` remain the authority for tool execution. The supervised coding agent in [`HOLY_FITRA_AGENT.md`](HOLY_FITRA_AGENT.md) currently uses a stricter allowlisted workspace runner and can plan, edit, validate, and roll back project changes. Any future model tool-call bridge must connect to `ToolRegistry.invoke` only after explicit capability grants and claim/evidence checks.

## Current boundary

The provider layer supports text chat, structured JSON request hints, function/tool declarations, embeddings, and validated native Fitra generation. It does not yet add an `ai.chat` expression to the compiled Fitra language itself, and it does not claim compatibility with every provider-specific batch, realtime, video, image-generation, speech, or managed-agent API. Those features require separate normalized contracts and should be added without weakening the current parser, capability, and evidence gates.
