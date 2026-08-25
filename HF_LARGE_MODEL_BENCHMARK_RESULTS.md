# HF Large-Model Native vs Pure-Python Results

## Result

The same deterministic 1,024 × 1,024 packed-INT4 matvec model was evaluated over a batch of 32 rows in HF’s native runtime and a pure-Python scalar reference. Each measured batch contains 33,554,432 dense-equivalent multiply-accumulate operations. Fixture construction and one warm-up were excluded from timing; each sample is itself the mean of three measured batches.

| Engine | Samples | Mean batch time | Range | Throughput | Output check |
|---|---:|---:|---:|---:|---|
| HF native INT4 + bounded range scheduler | 3 | 8.723 ms | 6.883–11.316 ms | 3.847 GMAC/s | Exact within 1e-6 |
| Pure-Python scalar reference | 3 | 3,954.443 ms | 3,925.022–4,000.134 ms | 0.008485 GMAC/s | Exact within 1e-6 |

On this host and fixture, HF completed the identical operation approximately **453.36× faster** than the pure-Python loop. The HF receipt for the observed batch reported three planned, admitted, and completed local ranges. The native fixture also completed under AddressSanitizer and UndefinedBehaviorSanitizer; instrumentation increased the observed native average to 30.685 ms and is not used in the comparison figure.

## What this comparison does and does not establish

The comparison honestly shows a native C/C++ INT4 path versus Python interpreter-loop overhead for one deterministic workload. It is not a comparison against NumPy, PyTorch, Numba, Cython, BLAS, XNNPACK, or any Python package with compiled kernels. It is not an Android, ARM64, NEON, GPU/NPU, power, thermal, JNI, APK, or physical-device result. The host’s load and scheduler activity explain the native timing range, so the mean is reported together with its observed range rather than as a universal claim.

## Next measured work

The most useful next comparison is HF against an optimized numerical baseline such as NumPy/OpenBLAS or an Android-targeted XNNPACK/ONNX Runtime configuration—but only after matching precision, model format, threading policy, and operator coverage. A separate physical Android campaign is required before making mobile latency or efficiency claims.
