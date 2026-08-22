#!/usr/bin/env bash
set -euo pipefail

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
OUTPUT="${1:-$ROOT/dist/holyfitra-v1.0.0-host.tar.gz}"
VERSION="1.0.0-host"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/holyfitra-v1-release.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT

command -v tar >/dev/null 2>&1 || { echo 'make-holyfitra-v1-release: tar is required' >&2; exit 127; }
command -v gzip >/dev/null 2>&1 || { echo 'make-holyfitra-v1-release: gzip is required' >&2; exit 127; }
command -v sha256sum >/dev/null 2>&1 || { echo 'make-holyfitra-v1-release: sha256sum is required' >&2; exit 127; }

bash -n "$ROOT/holyfitra" "$ROOT/holyfitra-v1.sh" "$ROOT/install-holyfitra-v1.sh" "$ROOT/termux-setup.sh" "$ROOT/termux-build.sh" "$ROOT/test_holyfitra_v1.sh"
HOLYFITRA_V1_BUILD_DIR="$WORK/build" "$ROOT/test_holyfitra_v1.sh" >/dev/null 2>&1

STAGE="$WORK/holyfitra-v1"
mkdir -p "$STAGE/bootstrap" "$STAGE/docs" "$STAGE/tools"
cp "$ROOT/holyfitra-v1.sh" "$STAGE/holyfitra-v1.sh"
cp "$ROOT/install-holyfitra-v1.sh" "$STAGE/install-holyfitra-v1.sh"
cp "$ROOT/test_holyfitra_v1.sh" "$STAGE/test_holyfitra_v1.sh"
cp "$ROOT/holyfitra_bootstrap.cpp" "$STAGE/holyfitra_bootstrap.cpp"
cp "$ROOT/bootstrap/holyfitra_runtime.c" "$STAGE/bootstrap/holyfitra_runtime.c"
cp "$ROOT/bootstrap/hello.hf" "$STAGE/bootstrap/hello.hf"
cp "$ROOT/HOLY_FITRA_V1_RELEASE_SPEC.md" "$STAGE/docs/HOLY_FITRA_V1_RELEASE_SPEC.md"
cp "$ROOT/HOLY_FITRA_V1_HOST_CANDIDATE_REPORT.md" "$STAGE/docs/HOLY_FITRA_V1_HOST_CANDIDATE_REPORT.md"
cp "$ROOT/HOLY_FITRA_STRESS_REPORT_2026-08-22.md" "$STAGE/docs/HOLY_FITRA_STRESS_REPORT_2026-08-22.md"
cp "$ROOT/HOLY_FITRA_MILLION_LINE_BENCHMARK_SPEC.md" "$STAGE/docs/HOLY_FITRA_MILLION_LINE_BENCHMARK_SPEC.md"
cp "$ROOT/HOLY_FITRA_MILLION_LINE_PERFORMANCE_REPORT_2026-08-22.md" "$STAGE/docs/HOLY_FITRA_MILLION_LINE_PERFORMANCE_REPORT_2026-08-22.md"
cp "$ROOT/stress_million_line.py" "$STAGE/tools/stress_million_line.py"
cp "$ROOT/measure_million_line.py" "$STAGE/tools/measure_million_line.py"
cp "$ROOT/README.md" "$STAGE/docs/README.md"
chmod 755 "$STAGE/holyfitra-v1.sh" "$STAGE/install-holyfitra-v1.sh" "$STAGE/test_holyfitra_v1.sh"
printf 'Holy Fitra v1\nversion=%s\npython_required=false\nandroid_execution=false\nplatform=host-or-Termux-native-cli\ntermux_native_target=aarch64-linux-android\nfixed_point_self_hosting=false\naarch64_status=artifact-only\n' "$VERSION" >"$STAGE/RELEASE_METADATA.txt"

mkdir -p "$(dirname -- "$OUTPUT")"
ARCHIVE="$WORK/holyfitra-v1.tar"
tar --sort=name --mtime='UTC 1970-01-01' --owner=0 --group=0 --numeric-owner -cf "$ARCHIVE" -C "$WORK" holyfitra-v1
gzip -n -c "$ARCHIVE" >"$OUTPUT"
printf '{"ok":true,"version":"%s","archive":"%s","sha256":"%s","python_required":false,"android_execution":false}\n' "$VERSION" "$OUTPUT" "$(sha256sum "$OUTPUT" | cut -d ' ' -f1)"
