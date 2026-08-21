# Holy Fitra Reinforcement Learning for Dynamic Threshold Tuning

## Selected implementation

Holy Fitra now includes `hyperc_rl.py`, a bounded linear-softmax REINFORCE controller. The controller observes access-frequency EWMA, hot streak, batch-size load, promotion state, and cache-memory ratio. It chooses among nine bounded actions that adjust promotion threshold and large-batch bonus by at most one step per decision. Hard bounds prevent thresholds and bonuses from leaving configured safety ranges.

The controller uses a moving-average baseline, advantage clipping, entropy regularization, deterministic seeded exploration, finite-value checks, and serializable policy state. The cache integration exposes `QuantizedMatrix.set_adaptive_policy()`, which changes only adaptive policy integers and preserves the existing reconstruction-error gate, memory accounting, promotion, and demotion behavior. Training checkpoints can now include and restore the policy controller state.

## Validation and benchmark evidence

The focused RL suite passes **5 tests**, and the complete applicable Holy Fitra suite passes **116 tests with 0 failures**. Termux-compatible validation passes, including AArch64 NibbleFlow object emission, ragged scalar/NEON/SVE checks, scheduler execution, CLI workflows, and benchmark invocation. ASAN/UBSAN validation passes for the ragged scheduler and sanitized NibbleFlow build.

On the x86-64 sandbox, the live mixed-trace benchmark executed policy decisions against an actual `QuantizedMatrix` adaptive cache. The controller changed bounded thresholds and bonuses, updated policy weights from measured latency/memory rewards, and preserved valid cache modes. Representative events included a 24-row cold access remaining at 24,576 bytes and 512-row burst accesses promoting to float32 at 49,152 bytes. The benchmark completed eight online policy updates; controller weight norm became non-zero and all rewards/advantages remained finite.

Policy checkpoint coverage proves model, optimizer, replay, and policy state reload together. The restored controller had the same update count and identical policy weights as the saved controller.

## Retention decision

Retain the bounded policy-gradient controller. It provides actual online policy updates for dynamic threshold tuning while keeping model parameters, quantization quality gates, cache memory limits, and native safety contracts outside the policy’s authority. This is an online controller for the supported cache runtime, not a claim of general reinforcement-learning intelligence.

All performance and live-trace measurements are **x86-64 sandbox results**. AArch64 object emission is cross-compilation evidence only; no physical Android training, Android latency, thermal, or device-throughput claim was made.
