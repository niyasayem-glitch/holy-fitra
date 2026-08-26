# Holy Fitra Local-Model Capability Baseline

## Purpose

This document prevents an invalid claim that the current Holy Fitra prototype already competes with Qwen-class local models. It defines the capabilities that must be measured before any such comparison and selects an achievable first implementation boundary.

## External reference boundary

Qwen3 spans dense models from 0.6B to 32B parameters and two MoE models, exposes up to 32K or 128K context depending on the released model, supports hybrid thinking modes, and was trained on approximately 36T tokens across 119 languages. The Qwen team describes a staged post-training pipeline including long chain-of-thought cold start, reasoning RL, thinking-mode fusion, and general RL.[1]

The current Qwen3.8-27B model card describes a 27B vision-language model with a 262K native context length, multi-token prediction, configurable reasoning effort, agentic coding evaluations, and multimodal inputs.[2] These are **reference capabilities**, not a fair immediate parity target for HF’s currently bounded Python learning components and native scalar runtime.

| Comparison tier | Reference | Required proof before HF comparison | Current HF status |
|---|---|---|---|
| Functional local-model baseline | A declared small local decoder model and a fixed task set | Tokenizer, autoregressive decoding, deterministic checkpoint, task-level accuracy and resource receipts | Not yet established |
| Small-model capability target | Qwen3 0.6B–4B family | Same tokenizer/task protocol, parameter count, context length, precision, hardware, and sampling configuration | Not comparable yet |
| Qwen-class general or agentic capability | Qwen3/Qwen3.8 claims | Matched public benchmark harness, model size/data/training disclosure, repeated local runs, quality and resource reporting | Not claimed |

## First justified HF capability

The next bounded upgrade should be a **deterministic token-level causal language-model contract**. It must define a vocabulary, sequence shape, causal next-token objective, stable checkpoint identity, and an evaluation receipt. This is a prerequisite for honest local language-model comparisons; it does not itself establish Qwen parity, high-quality natural language, coding competence, long context, tool use, or multimodality.

## Retained initial implementation

HF now implements that prerequisite as `holyfitra local-lm`: a UTF-8 byte tokenizer with 257 vocabulary entries including one begin token, a one-token-context causal bigram probability table, deterministic greedy decoding, SHA-256 corpus and model identities, tamper-detecting NumPy checkpoint loading, and negative-log-likelihood receipts. It uses no provider, external model, shell capability, or automatic file mutation.

On 2026-08-26, the CLI trained and evaluated the baseline on the repository’s `README.md` and `HOLY_FITRA_CAPABILITIES.md` documents. The receipt covered 2 documents, 28,646 UTF-8 bytes and transitions, model digest `84507886cc2028fe8b071b468f646ead87a49b118e1885948c443badce71527e`, and in-corpus mean next-byte NLL `2.624217972399485`. This is a **sanity receipt on training data**, not a held-out quality result, a language-understanding score, a coding benchmark, a throughput metric, or a comparison with Qwen.

## Measurement protocol

Each future retained model result must declare model architecture, parameter count, vocabulary, context length, tokenizer, dataset provenance and license, split hashes, precision, seed, training steps, hardware, wall time, peak memory, decoding settings, and the exact task harness. Compare only identical task sets and report failures as well as successes.

## References

[1] [Qwen3: Think Deeper, Act Faster](https://qwenlm.github.io/blog/qwen3/)

[2] [Qwen3.8-27B Model Card](https://huggingface.co/Qwen/Qwen3.8-27B)
