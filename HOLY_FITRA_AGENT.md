# Holy Fitra Coding Agent

Holy Fitra now includes a supervised coding agent that can understand a project workspace, plan changes, write Fitra or supporting files, run bounded validation commands, diagnose failures, and keep only changes whose checks pass. The agent is designed to help build applications with Holy Fitra rather than merely answer questions about the language.

## Workflow

The normal workflow is intentionally two-stage. Without `--apply`, the model can inspect the bounded workspace context and return a plan, but it cannot write files or execute commands:

```bash
holyfitra agent ./my-project \
  'Add a command-line task list with persistent local storage and tests.' \
  --provider openai
```

Review the JSON plan. To permit writes and allowlisted checks, use explicit apply mode:

```bash
holyfitra agent ./my-project \
  'Add a command-line task list with persistent local storage and tests.' \
  --provider openai \
  --apply
```

The agent may use only workspace-relative paths, bounded file contents, and approved validation commands. A failed validation restores every file changed during that run.

## Self-improvement rounds

The `--improve-rounds` option performs repeated model-plan/apply/validate cycles. Each round receives the changed workspace as context. A round is retained only if all requested validation actions pass; a failed round is rolled back and the loop stops:

```bash
holyfitra agent ./my-project \
  'Improve compilation speed without changing observable behavior; add a regression test.' \
  --provider openrouter \
  --model openai/gpt-4o-mini \
  --apply \
  --improve-rounds 3
```

This is **supervised self-improvement**, not unrestricted self-modification. The model cannot grant itself additional capabilities, change protected files, execute arbitrary shell strings, read API keys, call network tools through the validation runner, or silently retain an unvalidated patch.

## Allowlisted actions

The model can propose `read_file`, `search`, `write_file`, `run_check`, and `finish`. Validation commands are restricted to Holy Fitra checks/builds/tests, Python unit tests, the unified Termux test gate, and `git diff --check`. Shell execution uses `shell=False`, a timeout, a bounded environment, and a bounded output buffer.

Workspace reads exclude `.git`, virtual environments, dependency trees, caches, environment files, and common private-key filenames. File paths are canonicalized before access, and traversal outside the selected project is rejected. Generated files are written through a temporary file and atomic replacement.

## Relationship to the AI provider layer

The coding agent uses the provider-neutral API layer described in [`HOLY_FITRA_AI.md`](HOLY_FITRA_AI.md). It can use OpenAI-compatible providers, OpenRouter, Gemini, Anthropic, Ollama, and LM Studio. Provider API keys remain outside the agent’s command environment. The agent receives model text only through the normalized response contract.

## Relationship to Fitra

The current agent can create and validate the supported native scalar Fitra subset and can modify supporting Python, C, C++, and documentation files when the requested project policy permits it. The native Fitra compiler still has a deliberately bounded language surface. Tensor/AI runtime features remain separate HyperIR and native-runtime components until their ABI and lowering contracts are complete.

The next expansion is to add a Fitra standard-library bridge such as `ai.chat`, `ai.embed`, and capability-aware tool calls. Such calls must lower into the existing provider, `ToolRegistry`, evidence, consent, and runtime-budget contracts rather than becoming unrestricted network operations inside compiled programs.
