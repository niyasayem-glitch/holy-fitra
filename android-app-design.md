# Holy Fitra Android Workbench

## Product contract

The main repository will ship a native Android application module named `holyfitra-app`. Its first release is a local-first workbench for validating the packaged Holy Fitra native stack on an ARM64 phone. It provides a capability report, a bounded native benchmark, persistent last-result recovery, and a permission-free report export action.

The app does not require an account, network access, storage permission, microphone, location, accessibility service, or background service. Benchmark execution always occurs on a dedicated worker thread. The UI never claims physical-device performance until the native benchmark has actually completed on the current device.

## Screens and states

| Screen/state | Primary content | Primary action |
|---|---|---|
| Ready | Device ABI, NEON capability, native library status, and evidence note | Run quick check or sustained benchmark |
| Running | Progress message, disabled duplicate-run actions, and cancellation-safe lifecycle state | Wait for completion or leave/reopen the app |
| Completed | p50/p95/p99 latency, throughput, selected kernel, thermal signal, and raw-result availability | Export report or run again |
| Error | Human-readable failure and recovery guidance | Retry without losing the last successful result |

## Data model

The app stores only a versioned last-result JSON envelope in private app storage and a small preference containing the last run identifier. It does not send telemetry anywhere. A report export uses Android’s share sheet and happens only after the user presses the export action.

## Native boundary

The app consumes the existing `android-lib` module and its `HolyFitraBenchmark` Kotlin facade. The module remains the owner of CMake, NDK, JNI, and ABI policy. The app is arm64-v8a only, uses the pinned NDK and Java 17 contract, and packages `c++_shared` consistently with the library.

Thermal and frequency fields may be unavailable on production devices. The UI displays unavailable values as unavailable; it does not convert missing telemetry into zero or infer vendor-specific throttling.

## Visual and accessibility system

The UI uses platform widgets with a dark navy background, a raised slate surface, cyan primary action, green healthy state, amber warning state, and red failure state. Buttons use practical 48dp minimum touch targets. Every action has a content description, status changes are announced through the status text, and no essential information depends on color alone.

## Completion criteria

The app is ready for remote APK validation when the release build compiles, the APK contains only `arm64-v8a` native libraries, `zipalign -c -P 16 -v 4` passes, the application manifest has no unnecessary permissions, the local Kotlin/Gradle module checks pass, and the remote workflow uploads the release APK. Device execution, ART/JNI lifecycle, NEON throughput, and thermal results remain separate physical-device evidence gates.
