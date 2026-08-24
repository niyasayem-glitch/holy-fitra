# ARM64 Mobile Runtime Research Notes

## Evidence-backed design constraints

The QLoRA paper describes frozen 4-bit quantized base weights with low-rank adapters and reports NF4, double quantization, and paged optimizers as memory-oriented training techniques.[1] QA-LoRA identifies the imbalance between quantization and adaptation degrees of freedom and proposes group-wise operators intended to integrate auxiliary weights back into a quantized model after tuning.[2]

For mobile deployment, the relevant system constraint is not compression alone. Arm’s mobile guidance states that optimized runtime support and numerical sensitivity determine whether a format is useful; it presents INT8 as a reliable production baseline and weight-only INT4 with higher-precision activations as a practical memory-oriented option. It also cautions that aggressive activation quantization can damage quality, so mixed precision requires model-specific validation.[3]

MobileQuant focuses on fixed-point mobile-friendly formats, static per-tensor/per-channel ranges, and minimizing unsupported dynamic per-token quantization. Its paper reports results on its own benchmark/device setup; those numbers are not Holy Fitra measurements and must not be reused as performance claims.[4]

## Holy Fitra implications

The implementation should favor a runtime-selectable, metadata-versioned precision plan with strict validation: preserve the existing int4-weight/float activation path as a safe baseline; add calibration acceptance gates before any lower-precision activation path; route sensitive operations to conservative precision; and ensure kernels consume packed group-aligned data without on-the-fly format guessing. Any claim about ARM64 speed, thermals, battery, or JNI behavior remains unproven until a physical-device campaign records it.

## Pre-change Holy Fitra baseline

On the x86_64 development host, `bash termux-build.sh test --native-tests` completed successfully before the implementation wave. The gate exercised the NibbleFlow validator, ragged validation, streamed-kernel numerical equivalence, native scheduler/ragged tests, the streamed benchmark fixture, bootstrap states, and cross-compilation of the streamed kernel to an AArch64 Android object. The streamed validator explicitly reported `host_arch: x86_64`, `native_backend: native-scalar`, and that no physical Android execution was performed. This is a regression baseline only, not an ARM64 performance result.

## References

[1]: [QLoRA: Efficient Finetuning of Quantized LLMs — arXiv](https://arxiv.org/abs/2305.14314)
[2]: [QA-LoRA: Quantization-Aware Low-Rank Adaptation of Large Language Models — ICLR 2024](https://proceedings.iclr.cc/paper_files/paper/2024/hash/e6c2e85db1f1039177c4495ccd399ac4-Abstract-Conference.html)
[3]: [A practical guide to LLM quantization on Arm Mobile CPUs — Arm](https://developer.arm.com/community/arm-community-blogs/b/ai-blog/posts/llm-quantization-for-mobile-deployment)
[4]: [MobileQuant: Mobile-friendly Quantization for On-device Language Models — arXiv](https://arxiv.org/html/2408.13933v1)
