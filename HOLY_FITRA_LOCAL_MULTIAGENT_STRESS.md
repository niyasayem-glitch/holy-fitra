# Holy Fitra Local Neural Multi-Agent Stress System

`holyfitra_multiagent_stress.py` is a **local-only, test-oriented** multi-agent system. It is intended to exercise bounded sub-agent orchestration and a shared compact neural scorer; it is not a coding agent, an online service, or an autonomous deployment system.

## Model and agent boundaries

Six deterministic sub-agent roles run in a bounded local thread pool: **planner**, **researcher**, **trainer**, **reviewer**, **verifier**, and **governor**. They share an HMAC-authenticated int8 MLP scorer trained on synthetic data. Every proposal contains a typed decision, neural score, and evidence digest; the verifier and governor must both approve before a task is counted as accepted.

The runner has no provider calls, no network capability, no shell capability, no repository writes, no file-writing action, and no publishing path. Tasks containing mutating or external-action terms are rejected before proposal generation.

```bash
HOLY_FITRA_MULTI_AGENT_KEY="$YOUR_MULTI_AGENT_KEY" \
  python3 holyfitra_multiagent_stress.py --task-count 512 --work-iterations 128

python3 -m unittest -v test_holyfitra_multiagent_stress.py
```

| Local stress ceiling | Enforced value |
|---|---:|
| Sub-agent roles | 6 |
| Tasks per run | 1–512 |
| Concurrent workers | 1–6 |
| Neural work iterations per proposal | 1–128 |
| Task byte budget | 32–4,096 B |
| Default elapsed-time budget | 30 s |
| External side effects | 0 by policy |

The maximum validated local run used 512 tasks, 6 roles, and 128 work iterations, generating 3,072 proposals with zero side effects. Repeating the same workload produced the same canonical report digest.

## What this does not prove

This harness does not prove reasoning quality, provider independence, safe code modification, production security, real-world evaluation, Android performance, distributed reliability, or behavior under untrusted tools. It tests bounded local coordination mechanics only. A production agent system still needs authenticated identities, authorization policy, secret management, audit retention, rate limits, sandboxing, human approval, model evaluation, incident response, and physical-device validation.
