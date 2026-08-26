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

### Retained bounded context expansion

`holyfitra local-lm train --order 2` now builds a sparse causal n-gram table with deterministic longest-context interpolation plus a global fallback for unseen prompts. Context order is bounded to 2–4 and stored contexts are bounded to 32,768. Checkpoints encode the order, context limit, context keys, counts, receipt schema, and a digest over all of those values. The feature does not enable arbitrary unbounded context, attention, embeddings, transformer layers, or model capabilities beyond next-byte statistics.

On the identical current repository-document corpus, the order-1 bigram produced mean NLL `2.6247765502432703`; order 2 produced `1.6327421523496604`. The absolute reduction was `0.9920343978936099` NLL, or `37.79500383%` relative to the bigram. Both receipts covered the same 2 documents, 28,855 transitions, and corpus digest `7352350aefb7778ee19e6f1427887f5fde69c72f03c443732231e83de7c34a5b`. This is retained as an **in-corpus conditional-likelihood improvement only**. It does not measure held-out quality, generalization, language understanding, coding, reasoning, or Qwen comparability.

### Retained structural attention baseline; rejected as NLL default

HF now also exposes `holyfitra local-lm train --architecture attention`. It is a deterministic, trainable single-head causal self-attention reference with learned byte embeddings, learned positions, `Q/K/V/O` matrices, residual output, and a next-byte projection. Its bounds are intentionally small: 257 vocabulary entries, context 2–32, embedding width 4–64, 1–16 epochs, and at most 160,000 parameters. Causal-mask tests confirm that adding a future token does not change any prior logits; checkpoints persist all weights and a digest.

On the same then-current two-document corpus (`ff31abb84e39ba90ebc9a3e7cadf64e7b88406d824adb8916fa93a1c5ee160d0`, 28,905 transitions), the bounded configuration with width 16, context 16, 9,744 parameters, seed 17, learning rate 0.1, and 12 epochs produced in-corpus NLL `2.623819122090098`. The retained sparse order-2 n-gram scored `1.6326092371555752` on that same corpus. Therefore attention is retained as an **opt-in structural and causal-training baseline**, but rejected as the default NLL model. This does not establish transformer-scale training, attention efficiency, generalization, or Qwen comparability.

## Measurement protocol

Each future retained model result must declare model architecture, parameter count, vocabulary, context length, tokenizer, dataset provenance and license, split hashes, precision, seed, training steps, hardware, wall time, peak memory, decoding settings, and the exact task harness. Compare only identical task sets and report failures as well as successes.

## References

[1] [Qwen3: Think Deeper, Act Faster](https://qwenlm.github.io/blog/qwen3/)

[2] [Qwen3.8-27B Model Card](https://huggingface.co/Qwen/Qwen3.8-27B)
