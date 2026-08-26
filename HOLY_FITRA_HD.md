# Holy Fitra HD Copilot

## Purpose

**HD** is Holy Fitra’s supervised coding copilot. It can use a configured AI provider to draft a complete, structured code-change plan and can enrich that plan with a selected local Obsidian-compatible Markdown vault. HD is a workflow layer over the existing transactional coding agent; it is not an unrestricted background controller.

> HD can propose, inspect, write, validate, and roll back a project change only through the explicit workflow described below. It does not receive shell, network, credential, repository-administration, or unrestricted filesystem authority.

## Workflow

First request a plan. This default mode does not write files or run checks.

```bash
holyfitra hd ./my-project \
  'Add a tested project command that preserves existing behavior.' \
  --vault ./my-notes \
  --provider openrouter
```

Review the JSON receipt. When and only when the proposed write digests, validation commands, and source-note provenance are acceptable, rerun the same bounded request with `--apply`.

```bash
holyfitra hd ./my-project \
  'Add a tested project command that preserves existing behavior.' \
  --vault ./my-notes \
  --provider openrouter \
  --apply
```

Each plan/apply receipt now contains a `changes` list. Every proposed file includes its create/modify operation, before/after SHA-256 identity, byte counts, and a bounded unified diff. The preview is created before apply, so the receipt preserves what HD proposed even when later validation rolls the workspace back.

## Interactive advice and bounded build campaigns

Use `--mode advise` for a conversational, read-only coding explanation. Advice never produces an action plan, runs a command, or changes a workspace.

```bash
holyfitra hd ./my-project \
  'Explain how this Fitra module handles imports and what I should change first.' \
  --mode advise \
  --vault ./my-notes \
  --provider openrouter
```

For a larger feature, HD can run a short foreground campaign. This is an explicit, finite batch of independent plan → visible preview → apply → validation → receipt cycles; it never becomes a background service. The current hard limit is three cycles, and HD stops at the first rejected, failed-validation, or rollback receipt.

```bash
holyfitra hd ./my-project \
  'Implement a tested feature in small safe steps.' \
  --provider openrouter \
  --apply \
  --rounds 2 \
  --approve-campaign
```

`--rounds` is rejected unless both `--apply` and `--approve-campaign` are present. A campaign-wide approval is not an unrestricted permission: every round still uses workspace confinement, protected-path denial, the write-validation review gate, only allowlisted validation commands, transactional rollback, and a separate receipt. Inspect the resulting per-round `changes`, `agent_run.review`, validation output, and rollback state before requesting another campaign.

The `--vault` argument is optional. HD does not accept a provider secret as a command argument. For a local provider setup, copy the tracked `hd.providers.env.example` to the ignored `hd.providers.env`, enter only newly generated credentials, and pass it explicitly with `--provider-env`.

```bash
holyfitra hd ./my-project 'Draft a tested change.' \
  --provider cohere \
  --provider-env ./hd.providers.env
```

The loader accepts only the supported provider keys, model selectors, and HTTPS base-URL overrides. It prints no credential value, reports only the names of loaded variables, and the supervised workspace treats `hd.providers.env` as a protected file. See [`HOLY_FITRA_AI.md`](HOLY_FITRA_AI.md) for the supported provider matrix and local-file template.

## GitHub repository secrets

For credentials that should be entered directly in GitHub rather than shared with HD, the repository includes a manual-only **HD provider secret check** workflow. Add new, rotated values in GitHub’s **Settings → Secrets and variables → Actions** under the exact names below. The workflow verifies only whether the selected secret is available; it does not call a provider, print a value, write a file, run on `push`, or run on pull requests.

| Provider | GitHub Actions repository secret |
|---|---|
| OpenRouter | `HD_OPENROUTER_API_KEY` |
| Gemini | `HD_GEMINI_API_KEY` |
| Cerebras | `HD_CEREBRAS_API_KEY` |
| Groq | `HD_GROQ_API_KEY` |
| Cohere | `HD_COHERE_API_KEY` |

After entering a secret directly in GitHub, open **Actions → HD provider secret check → Run workflow**, select the matching provider, and run the check. A successful run confirms only secret availability; it does not validate quota, billing, model access, or response quality.

## Receipt contract

Every HD response is a `holyfitra.hd/v1` object. Its `knowledge` list contains vault-relative note paths, note SHA-256 digests, deterministic relevance scores, excerpts, and Obsidian provenance. Its `knowledge_digest` binds the selected retrieval result. The nested `agent_run.review` is the existing plan-review receipt: it binds proposed file contents by SHA-256 digest and identifies the proposed allowlisted validation commands.

| Stage | What HD may do | Required safeguard |
|---|---|---|
| Retrieval | Search a local Markdown vault through `ObsidianVaultIndex` | Read-only index, hidden/configuration-path exclusion, bounded note size, deterministic rank/order, and provenance |
| Planning | Ask a configured provider for JSON actions | Notes are labelled **untrusted context**, action schema is parsed and policy-checked |
| Advice | Explain the selected workspace and bounded second-brain context | `--mode advise` has no plan, write, or command authority |
| Inspection | Read/search the selected workspace and show proposed writes/checks | Default mode has no write or command permission; `changes` supplies a bounded file-by-file unified diff |
| Apply | Write workspace-relative files and execute validation | Literal `--apply`, allowlisted command shapes, bounded environment/output/time, and validation after the final write |
| Campaign | Run a small user-approved foreground sequence of apply cycles | Literal `--apply --rounds N --approve-campaign`, maximum three cycles, stop on any non-applied receipt |
| Failure | Restore modified files | Transactional rollback receipt records the failure reason and changed-file set |

## Second-brain boundary

HD reuses the repository’s existing local [`ObsidianVaultIndex`](HOLY_FITRA_OBSIDIAN_INTEGRATION.md). It reads ordinary Markdown directly; the Obsidian desktop application, a cloud account, a live Obsidian REST service, and an external connector are not required for this local workflow. HD does not call the vault’s write capability, export a Canvas/Base artifact, or treat a note as a verified fact or executable instruction.

There is currently no configured external Obsidian connector. Consequently, this capability is **local-vault retrieval**, not a claim of live Obsidian synchronization. The separately requested long-term Mem connection remains authorization-blocked; see [`HF_LONG_TERM_MEMORY_LEDGER.md`](HF_LONG_TERM_MEMORY_LEDGER.md) for the committed pending-sync record.

## Non-goals

HD does not silently apply changes, run indefinitely, execute arbitrary commands, delete source, access `.git` or environment files, read provider keys, call network tools, modify its own policy, or make any claim that a provider plan is correct. A campaign runs only in the foreground of the invoking command and never resumes itself. A passing allowlisted check is evidence only for that check; it does not certify an entire project or replace human review.
