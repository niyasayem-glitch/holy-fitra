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

The `--vault` argument is optional. HD does not accept a provider secret as a command argument. For a local provider setup, copy the tracked `hd.providers.env.example` to the ignored `hd.providers.env`, enter only newly generated credentials, and pass it explicitly with `--provider-env`.

```bash
holyfitra hd ./my-project 'Draft a tested change.' \
  --provider cohere \
  --provider-env ./hd.providers.env
```

The loader accepts only the supported provider keys, model selectors, and HTTPS base-URL overrides. It prints no credential value, reports only the names of loaded variables, and the supervised workspace treats `hd.providers.env` as a protected file. See [`HOLY_FITRA_AI.md`](HOLY_FITRA_AI.md) for the supported provider matrix and local-file template.

## Receipt contract

Every HD response is a `holyfitra.hd/v1` object. Its `knowledge` list contains vault-relative note paths, note SHA-256 digests, deterministic relevance scores, excerpts, and Obsidian provenance. Its `knowledge_digest` binds the selected retrieval result. The nested `agent_run.review` is the existing plan-review receipt: it binds proposed file contents by SHA-256 digest and identifies the proposed allowlisted validation commands.

| Stage | What HD may do | Required safeguard |
|---|---|---|
| Retrieval | Search a local Markdown vault through `ObsidianVaultIndex` | Read-only index, hidden/configuration-path exclusion, bounded note size, deterministic rank/order, and provenance |
| Planning | Ask a configured provider for JSON actions | Notes are labelled **untrusted context**, action schema is parsed and policy-checked |
| Inspection | Read/search the selected workspace and show proposed writes/checks | Default mode has no write or command permission |
| Apply | Write workspace-relative files and execute validation | Literal `--apply`, allowlisted command shapes, bounded environment/output/time, and validation after the final write |
| Failure | Restore modified files | Transactional rollback receipt records the failure reason and changed-file set |

## Second-brain boundary

HD reuses the repository’s existing local [`ObsidianVaultIndex`](HOLY_FITRA_OBSIDIAN_INTEGRATION.md). It reads ordinary Markdown directly; the Obsidian desktop application, a cloud account, a live Obsidian REST service, and an external connector are not required for this local workflow. HD does not call the vault’s write capability, export a Canvas/Base artifact, or treat a note as a verified fact or executable instruction.

There is currently no configured external Obsidian connector. Consequently, this capability is **local-vault retrieval**, not a claim of live Obsidian synchronization. The separately requested long-term Mem connection remains authorization-blocked; see [`HF_LONG_TERM_MEMORY_LEDGER.md`](HF_LONG_TERM_MEMORY_LEDGER.md) for the committed pending-sync record.

## Non-goals

HD does not silently apply changes, run indefinitely, execute arbitrary commands, delete source, access `.git` or environment files, read provider keys, call network tools, modify its own policy, or make any claim that a provider plan is correct. A passing allowlisted check is evidence only for that check; it does not certify an entire project or replace human review.
