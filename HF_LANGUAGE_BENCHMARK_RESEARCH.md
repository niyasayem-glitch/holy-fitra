# Cross-Language Benchmark Method Notes

The local HF comparison will use a fixed scalar state-machine workload, rotating execution order, repeated samples, exact result checks, and separately reported build versus runtime timing. It must not describe its results as a universal language ranking. The Computer Language Benchmarks Game explicitly characterizes its examples as microbenchmarks that are easy to measure but far from realistic, while still useful as tools.[1]

The local test therefore separates four observations: available-toolchain coverage, HF scalar-language contract coverage, optimized cold/warm build time, and loop-only runtime for implementations that can accept dynamic command-line input. A current HF scalar `main` must be parameterless and has no supported input/side-effect bridge for this loop, so it will be functionally tested but excluded from the runtime ranking rather than given a fabricated or constant-folded timing.

The methodology also follows the broader point from Lion et al. that runtime performance depends on interactions among compilation, JIT behavior, thread libraries, garbage collection, workload compute intensity, memory, I/O, and concurrency.[2] That paper’s published results are not used as HF results; it only motivates explicit scope and result boundaries.

## References

[1]: https://benchmarksgame-team.pages.debian.net/benchmarksgame/index.html "The Computer Language Benchmarks Game"
[2]: https://www.usenix.org/conference/atc22/presentation/lion "Lion et al., Investigating Managed Language Runtime Performance"
