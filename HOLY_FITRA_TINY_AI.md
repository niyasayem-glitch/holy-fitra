# Holy Fitra Tiny AI: Verified Reference Build

## What was built

`holyfitra_tiny_ai.py` is a deterministic, from-scratch **XOR binary classifier**. It trains a two-layer multilayer perceptron with 33 trainable parameters using Holy Fitra's existing Tensor/autodiff, Adam optimizer, quantization-aware training, and deployment modules. It then exports an int8 quantized `holyfitra.deployment` artifact, reloads that artifact, and verifies all four XOR predictions.

This is a real, bounded learning example. It is **not** a language model, a general-purpose assistant, or native Holy Fitra tensor execution.

```bash
HOLY_FITRA_DEPLOYMENT_KEY="$YOUR_DEPLOYMENT_KEY" python3 holyfitra_tiny_ai.py --output build/tiny_xor.hfbin --seed 17 --epochs 900
python3 -m unittest -v test_holyfitra_tiny_ai.py
```

The deployment key is required and is never written into the artifact, source tree, or report. Store a high-entropy key in the platform's secret manager rather than in a command history or committed configuration file.

The fixed test run used seed `17` and produced the following outcome:

| Measure | Result |
|---|---:|
| Training examples | 4 XOR truth-table rows |
| Trainable parameters | 33 |
| Initial MSE | 0.5769450068 |
| Final MSE | 0.0000072178 |
| Float-model accuracy | 100% (4/4) |
| Reloaded int8 deployment accuracy | 100% (4/4) |
| Deployment artifact | 1,283 B |
| Deployment digest | `a5e132d830d440cfbf642db3f8d7e13afdcc1a92b92e93966cbc4baacc9c1bd4` |

The companion declaration at `examples/tiny_xor_inference.hf` is accepted by the current tensor planner and lowers two `neon.f16_matmul` plan operations. It describes the intended inference shape; it does not train or load the exported weights inside the Holy Fitra language runtime.

## Problems encountered and current limitations

The table records every issue encountered in this scoped build, together with the precise boundary that remains after the example passes.

| Area | Problem or limitation | Status |
|---|---|---|
| Core language execution | The native Holy Fitra compiler currently supports the scalar subset. Tensor syntax is validated and lowered into a plan, but tensor values, autograd, optimizer updates, and model execution are not lowered to native code. | Unresolved architectural gap |
| Training runtime | The successful trainer runs through the Python/NumPy reference runtime, not through a self-hosted Holy Fitra executable. | Unresolved runtime gap |
| Weight connection | `tiny_xor_inference.hf` has typed weight declarations, but there is no current language-level loader that binds `tiny_xor.hfbin` weights to those tensors. | Unresolved integration gap |
| Model type | The supported deployment path is a fixed two-layer ReLU MLP. It does not support convolution, recurrence, attention, transformers, tokenization, embeddings, or a language-model decoder. | Intentional current scope |
| Classification semantics | The reference classifier uses MSE regression targets and an external `>= 0.5` threshold. There is no native sigmoid, softmax, cross-entropy, calibration, or multiclass metric path in this example. | Unresolved model-library gap |
| Dataset realism | XOR is a four-row proof fixture. It establishes that gradients, updates, QAT, export, and reload work together; it says nothing about data ingestion, generalization, robustness, fairness, or production accuracy. | Intentional test limitation |
| Quantization | The proven path uses symmetric int8 quantization with an explicit quality gate. Current quantization support is bounded to symmetric int4/int8 contracts; broader formats and hardware-specific calibration remain outside this example. | Current feature limit |
| Native acceleration | The classifier does not use the ARM64 NibbleFlow/ragged kernels. No inference latency, memory, NEON/SVE, big.LITTLE, or thermal claim is made. | Unresolved integration and measurement gap |
| Android delivery | The generated `.hfbin` is not yet wired through the Android JNI/Kotlin Workbench or the Expo companion. | Unresolved product integration gap |
| Artifact integrity | Deployment format v2 now authenticates the manifest and every weight byte with an HMAC-SHA-256 tag. A wrong key, missing tag, or any payload mutation fails before decoding. | Implemented; managed key rotation and public-key distribution remain open |
| Deployment input validation | Deployment inference now rejects non-finite inputs, empty or over-limit batches, oversized input byte payloads, and non-finite outputs. | Implemented for the reference API |
| Checkpoint interoperability | Training checkpoints and deployment artifacts use distinct formats. The language-level module system has no unified model registry, version migration, signing-key rotation policy, or package-to-runtime loader for them. | Unresolved platform gap |
| Scaling | The example has no batching benchmark, streaming data loader exercise, distributed training, mixed precision strategy, memory allocator integration, or optimizer-kernel lowering. | Unresolved scaling gap |
| Safety and operations | The model artifact is deterministic and validated structurally, but this example does not add evaluation governance, data consent workflow, model-card generation, red-team testing, online monitoring, or rollback policy. | Unresolved operational gap |

## What passed

The current full regression suite runs **248 tests**. It includes deterministic repeated authenticated exports, HMAC failure on tampered payloads or wrong keys, finite/bounded deployment inference, exact XOR predictions, malformed quantization rejection, failed quality gates, checkpoint restoration, and non-finite optimizer-update rejection.

## Next implementation milestones

The smallest path from this reference model toward a genuine Holy Fitra-native AI is:

1. Implement a tensor-buffer ABI and deployment loader that binds a verified `.hfbin` artifact to typed Holy Fitra tensor declarations.
2. Lower dense matmul, ReLU, and quantized linear inference from HyperIR into the existing ARM64 runtime with numerical equivalence tests.
3. Add native classification operators and losses, followed by deterministic minibatch/streaming-data interfaces.
4. Integrate the verified loader into Android JNI, then measure only on a physical ARM64 device with a defined model, batch size, and thermal protocol.
