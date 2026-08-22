# Holy Fitra multi-AI coding campaign

The multi-AI campaign is the orchestration layer for asking several AI providers to propose the next batch of Holy Fitra improvements. It is designed for supervised development: providers propose plans, the campaign compares them, and Holy Fitra—not the model—controls file access, validation, rollback, and promotion.

## Configure a campaign

Copy the repository template and edit the goal:

```bash
cp holyfitra_campaign.toml.example holyfitra_campaign.toml
```

The template defaults to three rounds, three concurrent provider calls, automatic discovery of configured providers, two-plan consensus, plan-only mode, and a workspace-local report at `.holyfitra/campaign/latest.json`.

Provider credentials remain environment variables. Do not put keys in the TOML file or commit them:

```bash
export OPENAI_API_KEY='...'
export ANTHROPIC_API_KEY='...'
export GEMINI_API_KEY='...'
```

For local models, start Ollama or LM Studio and leave the provider list empty so the campaign discovers whichever endpoints are available. Remote providers must use the existing provider-layer HTTPS policy.

## Plan-only launch

Plan-only mode is the default and makes no source-code changes:

```bash
holyfitra campaign holyfitra_campaign.toml
```

The output contains provider statuses, each candidate plan, the deterministic consensus result, and the report path. A candidate must contain at least one allowlisted validation command. If providers disagree, the round is recorded without selecting a plan.

## Apply launch

Apply mode requires explicit `--apply` and a Git branch beginning with `high-risk/`:

```bash
git switch -c high-risk/next-campaign origin/master
holyfitra campaign holyfitra_campaign.toml --apply
```

The campaign never applies on `master`, `safe/*`, or an unrecognized branch. The existing coding-agent workspace restricts paths and commands, protects credentials and VCS metadata, writes atomically, and restores the pre-run files when validation fails. A campaign round that rolls back stops the campaign.

Use a higher consensus threshold for particularly risky work:

```toml
providers = ["openai", "anthropic", "gemini"]
rounds = 5
max_workers = 3
min_consensus = 3
```

Consensus is exact over the proposed write set and validation commands. Similar natural-language explanations do not count as agreement. This deliberately favors reproducibility over majority voting on vague suggestions.

## What the campaign can improve

Good campaign goals are measurable and bounded. Examples include reducing compiler cold-start time without changing generated output, adding regression tests for a parser boundary, improving Termux diagnostics, hardening a native ownership check, or optimizing a cache path with a before/after benchmark.

Avoid goals such as “rewrite everything,” “remove all safety limits,” “grant unrestricted shell access,” or “self-modify without tests.” The agent cannot request those capabilities through the campaign contract.

## Promotion

After an apply campaign succeeds, commit the high-risk branch and push it:

```bash
git add -A
git commit -m 'experiment: describe the validated improvement'
git push -u origin high-risk/next-campaign
```

Promotion to `master` remains separate. Use the repository’s explicit high-risk workflow only after reviewing the campaign report and diff:

```bash
gh workflow run promote-high-risk.yml \
  --ref master \
  -f source_branch=high-risk/next-campaign \
  -f confirmation=PROMOTE \
  -f reason='Describe the measured benefit and reviewed risk.'
```

The remote workflow repeats the full Python suite, Termux-compatible native gate, deterministic release packaging, and the configured high-risk campaign gate before promotion. Host and CI results do not establish Android ARM64 device behavior; those claims require separate Android SDK/NDK and physical-device evidence.
