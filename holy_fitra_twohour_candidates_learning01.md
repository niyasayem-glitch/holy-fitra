# Holy Fitra Training and Continual Learning — Candidate Matrix

## Selection context

The existing `hyperc_nn.py` contains scalar autograd primitives and a single dense layer demo, but it has no optimizer, repeated update loop, replay, checkpoint recovery, evaluation protocol, or continual-learning safeguards. The selected foundation adds these capabilities without introducing a heavyweight dependency or changing the existing tensor API.

| Rank | Candidate | Expected impact | Risk | Decision |
|---:|---|---|---|---|
| 1 | Trainable MLP + Adam + mini-batch loop + evaluation | Actual parameter learning with deterministic convergence evidence | Low/medium | **Selected** |
| 2 | Bounded replay buffer with deterministic reservoir sampling | Reduces catastrophic forgetting during task updates | Medium | **Selected** |
| 3 | Atomic checkpoint save/load with optimizer state | Resume training without losing momentum | Medium | **Selected** |
| 4 | Gradient clipping and non-finite update rejection | Training safety and stability | Low | **Selected** |
| 5 | Early stopping and best-checkpoint retention | Avoids overfitting | Low | Defer |
| 6 | Experience replay prioritization | Better sample efficiency | Medium | Defer |
| 7 | Elastic weight consolidation | Stronger continual retention | High | Defer |
| 8 | Contrastive representation training | Broader learning objective | Medium/high | Defer |
| 9 | Transformer fine-tuning loop | Full-model learning | High | Defer |
| 10 | Quantization-aware training | Mobile deployment value | High | Defer |
| 11 | Mixed-precision gradient scaler | Android value | Medium | Defer |
| 12 | Data-loader prefetching | Throughput value | Medium | Defer |
| 13 | Distributed/sharded optimizer | Scale value | High | Defer |
| 14 | Automatic curriculum scheduler | Learning quality | Medium/high | Defer |
| 15 | Native ARM64 training kernels | Device performance | High without physical hardware | Defer |

## Retention rule

Retain only if a deterministic supervised task converges, checkpoint reload reproduces predictions and optimizer state, replay improves retention on a prior task relative to no replay, non-finite updates are rejected, and the complete existing regression/native/Termux gates remain green. All measurements must be labeled as x86-64 sandbox results.

## Learning milestone result

The selected foundation is implemented in `holyfitra_learning.py`. It adds `TrainableMLP`, Adam with serializable first/second moments, deterministic mini-batch training, gradient clipping, non-finite update rejection, bounded reservoir replay, MSE evaluation, and atomic compressed NumPy checkpoints containing model, optimizer, replay, and manifest state.

The focused learning suite passes **5 tests**. The complete applicable Holy Fitra suite passes **111 tests with 0 failures**. Termux-compatible host validation passes, including AArch64 NibbleFlow object emission, ragged scalar/NEON/SVE checks, scheduler execution, CLI workflows, and benchmark invocation. ASAN/UBSAN validation passes for the ragged scheduler and sanitized NibbleFlow build.

On the x86-64 sandbox, the benchmark measured:

| Metric | Result |
|---|---:|
| Initial regression MSE | 9.6338300705 |
| First supervised task final MSE | 0.0090440707 |
| Continual first-task MSE after replay update | 0.0005090825 |
| Continual second-task MSE | 0.0002022217 |
| Replay items retained | 80 |
| Checkpoint maximum prediction error after reload | 0.0 |
| Checkpoint manifest version | 1 |

The results demonstrate actual parameter updates, convergence, replay-assisted continual updates, and exact checkpoint prediction recovery. They do not establish general intelligence, large-model training capability, or Android-device training performance. All measurements are sandbox reference-runtime results.

## Learning milestone retention decision

Retain the training foundation. It adds real learning behavior without changing existing inference APIs, keeps dependency requirements compatible with Termux, rejects unsafe numerical states, and passes complete regression/native/sanitizer/Termux validation.
