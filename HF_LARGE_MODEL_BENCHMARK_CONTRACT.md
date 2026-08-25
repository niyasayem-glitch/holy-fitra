# HF Large-Model Native vs Pure-Python Benchmark Contract

## Purpose

This benchmark compares one equivalent deterministic INT4 matrix-vector batch fixture through HF’s native NibbleFlow runtime and a **pure-Python scalar reference**. It measures host wall-clock time only.

## Shared fixture

| Property | Fixed value |
|---|---:|
| Input dimension | 1,024 |
| Output dimension | 1,024 |
| Group size | 32 |
| Batch rows | 32 |
| Dense-equivalent multiply-accumulate operations per batch | 33,554,432 |
| Weight representation | Same deterministic packed signed INT4 bytes, per-group scales, and float bias |
| Input representation | Same deterministic float32-like values in both implementations |
| Correctness signal | Output sum and weighted checksum, compared with a documented tolerance |
| Timing | One warm-up plus three measured batch runs; mean batch time reported |

## Fairness boundaries

HF uses its existing native C/C++ NibbleFlow kernel and bounded scheduler micro-batching. The Python comparator deliberately uses no NumPy, PyTorch, Numba, Cython, or native extension: it is a transparent scalar reference. Therefore the result shows the cost difference between HF’s current native runtime path and **pure Python loops**; it does not compare HF with optimized Python numerical stacks, mobile devices, GPU/NPU backends, or end-to-end language compilation.

The fixture is large enough to exceed the prior 64×64 example substantially while staying within this sandbox’s memory and run-time budget. Results are meaningful only for this host, compiler flags, and generated deterministic fixture.
