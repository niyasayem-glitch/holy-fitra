# Pix Studio Embedded Holy Fitra Runtime Contract

## Purpose

This integration packages the **existing Android Bionic/JNI NibbleFlow runtime** inside a local Expo Android module for Pix Studio. It establishes a real native-library loading path for a custom Android build. It does **not** embed the Python compiler driver or claim that arbitrary Holy Fitra project source can be compiled or run on a phone.

| Surface | Included in first module | Deliberately excluded |
|---|---|---|
| Runtime | `holyfitra_runtime` JNI library, streamed block dispatch, direct-buffer model runtime | Model download, arbitrary file execution, background execution |
| Bridge | Expo Kotlin module exposes a bounded native-library status probe | Silent native fallback or fabricated device receipt |
| Compiler | None | Python compiler driver, LLVM toolchain, bootstrap compiler execution/linking |
| Platform | Android arm64-v8a, API 26+, custom Expo build | Expo Go, web, iOS, physical-device performance claim |

## Native contract

The module is named `ExpoHolyFitra`. Its initial API is deliberately read-only:

```ts
type HolyFitraNativeStatus = {
  state: "available" | "unavailable";
  runtime: "holyfitra_runtime";
  abi: "arm64-v8a";
  hasNeon: boolean | null;
  boundary: string;
  detail: string;
};
```

`available` means that a **custom Android build** loaded the packaged JNI library and completed its bounded feature probe. It does not mean a model was loaded, a source file was compiled, NibbleFlow inference succeeded, or a physical device performance result was measured. On web and Expo Go, the JavaScript wrapper reports `unavailable` without throwing.

## Source and build provenance

The local Expo module vendors the seven-source Android runtime graph from this repository under `modules/expo-holy-fitra/android/src/main/cpp/holyfitra`. The copy is attributed in `UPSTREAM_REVISION.md` and must be refreshed only with a reviewed Holy Fitra commit. CMake retains arm64-v8a, API 26, C++17, 16 KB ELF alignment, RELRO/NOW, hidden visibility, and `c++_shared` requirements from the established Android library graph.

Expo recommends local modules for custom native code inside a single application and requires a native development or production build for code not included in Expo Go.[1] [2]

## Validation gate

The scaffold is valid only after all of the following occur:

1. Expo autolinking resolves the local module during Android prebuild.
2. The Android Gradle/NDK build compiles the vendored graph for arm64-v8a.
3. A custom Android build loads `holyfitra_runtime` and returns the native status probe.
4. A physical device records a signed execution receipt before any runtime, NEON, scheduler, or performance statement.

This sandbox currently lacks a full Android NDK application build path and a connected device. Therefore the work may validate TypeScript, source contracts, and host/QEMU safeguards, but cannot claim steps 2–4 have passed.

## Scaffold validation record

The first scaffold validation completed with the following limited evidence:

| Check | Result | What it establishes | What it does not establish |
|---|---|---|---|
| Expo public configuration | Pass | Pix Studio requests `arm64-v8a` and Android API 26 | A generated Gradle project or APK |
| Expo autolinking resolution | Pass | `expo.modules.holyfitra.ExpoHolyFitraModule` resolves from the local module directory | Kotlin compilation or native library packaging |
| Vendored graph comparison | Pass | All seven native sources and five direct headers byte-match revision `6ec80c6542c9a9093c48b6da0fb8c297886fdf52` | Runtime execution on Bionic |
| Android NDK/Gradle build | Blocked | The module’s CMake gate is present | No NDK/sysroot is installed in this sandbox |
| Device receipt | Blocked | None | No phone, Android Bionic load, model execution, NEON behavior, or performance result |

The QEMU Linux AArch64 result recorded elsewhere is useful portability evidence for the i64 fixture only. It does not substitute for Android Bionic compilation, APK packaging, or a direct module receipt.

## References

[1]: https://docs.expo.dev/modules/get-started/ "Expo Modules API: Get started"
[2]: https://docs.expo.dev/workflow/customizing/ "Expo: Add custom native code"
