# Holy Fitra Android NDK Ragged-Scheduler Benchmark Runner

## Purpose

This runner measures the end-to-end latency of Holy Fitra’s ragged attention scheduler on Android ARM64 devices, including scheduler admission, work-stealing execution, ragged kernel invocation, request completion, and thermal-policy updates. It is designed for Snapdragon and MediaTek big.LITTLE devices and emits machine-readable JSON suitable for repeated experiments.

The runner does not claim performance from host builds. A physical Android device is required for valid Snapdragon or MediaTek latency, frequency, and thermal conclusions.

## Native Components

The benchmark library is assembled from:

| Source | Responsibility |
|---|---|
| `holy_fitra_ragged_kernel.c` | Scalar, NEON, and SVE ragged attention kernels |
| `holy_fitra_dispatch.cpp` | Bounded work-stealing scheduler |
| `holy_fitra_android_topology.cpp` | Big/little topology and worker tuning |
| `holy_fitra_ragged_scheduler.cpp` | Sequence-chunk scheduler bridge |
| `holy_fitra_device_benchmark.cpp` | Workload generation, measurement, thermal sampling, and JSON |
| `holy_fitra_device_benchmark_jni.cpp` | JNI entry point |
| `android-lib/src/main/java/com/holyfitra/benchmark/HolyFitraBenchmark.kt` | Coroutine-safe Android API |

## Android Build Integration

The benchmark is already part of the checked-in `android-lib` library module. Use `android-lib/build.gradle.kts` for the module configuration and `android-lib/src/main/cpp/CMakeLists.txt` for the native graph; the benchmark target is `holyfitra_benchmark`. Build it with `./gradlew :android-lib:assembleRelease` when the Android SDK/NDK and Gradle wrapper are available. The legacy standalone Gradle fragment is intentionally not retained.

The release configuration intentionally filters to `arm64-v8a`. A future split ABI can add a scalar `armeabi-v7a` fallback, but the current ragged NEON/SVE target is ARM64-first.

The JNI library is named:

```text
libholyfitra_benchmark.so
```

The Kotlin class loads it with:

```kotlin
System.loadLibrary("holyfitra_benchmark")
```

## Kotlin Usage

The benchmark must run away from the Android main thread. The provided API uses `Dispatchers.Default`:

```kotlin
val result = benchmark.run(
    HolyFitraBenchmark.Config(
        dModel = 64,
        sequenceCount = 32,
        minLength = 16,
        maxLength = 256,
        sequencesPerTask = 2,
        warmupIterations = 20,
        measuredIterations = 500,
        pinThreads = true,
        thermalSamplePeriod = 1,
    )
)

Log.i("HolyFitra", result.toString())
Log.i("HolyFitra", "p99=${result.p99Ms} ms")
```

Do not run the benchmark on the UI thread. The workload is intentionally sustained and may heat the device.

## Measurement Protocol

Use three phases for each device and configuration:

| Phase | Purpose |
|---|---|
| Idle baseline | Record device model, battery, ambient state, initial thermal values, and initial frequency |
| Warm-up | Compile caches, start workers, establish CPU frequency, and discard startup samples |
| Measured run | Record every completed request latency, thermal sample, scheduler statistics, and checksum |

A recommended first run uses 20 warm-up iterations and 500 measured iterations. Repeat each configuration at least three times and report median run-level p50, p95, p99, throughput, and maximum temperature.

For sustained thermal behavior, use a separate long run with 5,000–20,000 measured iterations or a fixed wall-clock duration. Record the device battery percentage and charging state because charging can change thermal behavior.

## Metrics

The JSON result contains:

| Field | Meaning |
|---|---|
| `latency_ms.mean` | Mean request completion time |
| `latency_ms.p50` | Median end-to-end request latency |
| `latency_ms.p95` | 95th percentile latency |
| `latency_ms.p99` | 99th percentile latency |
| `throughput_tokens_per_second` | Packed tokens processed per second |
| `scheduler.submitted` | Scheduler tasks accepted during measurement |
| `scheduler.completed` | Scheduler tasks completed |
| `scheduler.stolen` | Tasks executed after work stealing |
| `thermal.max_temp_c` | Maximum sampled thermal-zone temperature |
| `thermal.min_freq_mhz` | Minimum sampled current CPU frequency when readable |
| `thermal.frequency_drop_detected` | Whether ending frequency fell below 90% of baseline |
| `thermal.temperature_rise_detected` | Whether sampled temperature rose more than 5°C |
| `checksum` | Deterministic output-use checksum to prevent dead-code elimination |

Some Android production builds restrict access to `scaling_cur_freq` or thermal zones. In that case, the corresponding fields are JSON `null`; this means unavailable, not zero.

## Snapdragon and MediaTek Notes

The topology detector first uses Linux CPU capacity information and falls back to maximum-frequency information. It reports the source in `device_topology_source` and whether the result came from sysfs.

Snapdragon devices may expose multiple performance clusters and vendor-specific thermal zones. MediaTek devices may expose different policy directories and frequency naming. The runner deliberately uses generic Linux interfaces and records missing data rather than guessing vendor-specific values.

For rigorous comparison, record:

```text
manufacturer and model
SoC name
Android version
kernel version
RAM size
battery percentage
charging state
screen state
thermal-zone availability
CPU capacity source
ABI and build fingerprint
```

## Thermal Throttling Interpretation

A frequency drop or temperature rise is a signal, not proof of a specific throttling mechanism. Report both raw signals and latency changes. A useful sustained-run comparison is:

```text
cold p50 / warm p50 / hot p50
cold p99 / warm p99 / hot p99
cold throughput / hot throughput
maximum temperature
minimum observed frequency
```

Do not compare a cold first run on one device with a hot sustained run on another. Keep screen, charging, ambient conditions, and background load consistent.

## Scheduler and Kernel Configurations

Measure at least these configurations:

| Configuration | Goal |
|---|---|
| Little-preferred scalar | Energy-oriented baseline |
| Little-preferred NEON | Low-power vector baseline |
| Big-preferred NEON | Throughput-oriented vector path |
| Big-preferred SVE | SVE-capable high-throughput path |
| Thermal feedback enabled | Production-like adaptive policy |
| Thermal feedback disabled | Isolate raw scheduler behavior |
| `sequences_per_task = 1` | Fine-grained scheduling |
| `sequences_per_task = 4` or `8` | Reduced scheduler overhead |

The current Kotlin wrapper selects the native policy automatically. For controlled experiments, expose a future explicit `kernel` and `coreClass` configuration rather than editing the native benchmark.

## JSON Export

The native API returns one JSON document. The Kotlin `Result.toCsvRow()` method provides a compact row for CSV aggregation. A production app should append the raw JSON and a CSV row to app-private storage, then export the files only after the benchmark completes.

Do not write benchmark output to public external storage unless the application has a deliberate data-export design. Benchmark files may contain device identifiers and should be handled as sensitive telemetry.

## Validation Boundaries

The sandbox host validates native compilation, benchmark completion, JSON structure, scheduler integration, and deterministic workload generation. It cannot validate Snapdragon or MediaTek frequencies, thermal-zone behavior, NEON execution speed, SVE availability, or Android power management.

A device run is required to establish:

1. Physical ARM64 kernel execution.
2. Real big/little worker placement.
3. Actual p50/p95/p99 latency.
4. Sustained thermal throttling behavior.
5. Energy per token.
6. Cancellation and deadline behavior under thermal pressure.

## References

[1]: https://developer.android.com/ndk/guides/abis "Android NDK ABI Management"
[2]: https://developer.android.com/topic/performance/vitals "Android performance guidance"
[3]: https://developer.android.com/reference/android/os/HardwarePropertiesManager "Android Hardware Properties Manager"
[4]: https://developer.arm.com/documentation/102467/latest "Arm A64 Instruction Set Architecture"
[5]: https://developer.arm.com/documentation/102476/latest "Arm Scalable Vector Extension"
