#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
BUILD=${HOLYFITRA_BOOTSTRAP_BUILD:-/tmp/holyfitra_bootstrap_gate}
WORK=${HOLYFITRA_BOOTSTRAP_WORK:-/tmp/holyfitra_bootstrap_work}
mkdir -p "$WORK"

clang++ -std=c++17 -O2 -Wall -Wextra -pedantic "$ROOT/holyfitra_bootstrap.cpp" -o "$BUILD"

"$BUILD" "$ROOT/bootstrap/hello.hf" -o "$WORK/hello.ll"
clang -O2 "$WORK/hello.ll" -o "$WORK/hello"
set +e
"$WORK/hello"
hello_status=$?
set -e
test "$hello_status" -eq 42

"$BUILD" "$ROOT/bootstrap/control.hf" -o "$WORK/control.ll"
clang -O2 "$WORK/control.ll" -o "$WORK/control"
set +e
"$WORK/control"
control_status=$?
set -e
test "$control_status" -eq 1

"$BUILD" "$ROOT/bootstrap/aggregates.hf" -o "$WORK/aggregates.ll"
clang -O2 "$WORK/aggregates.ll" -o "$WORK/aggregates"
set +e
"$WORK/aggregates"
aggregate_status=$?
set -e
test "$aggregate_status" -eq 42

"$BUILD" "$ROOT/bootstrap/io.hf" -o "$WORK/io.ll"
clang -O2 "$WORK/io.ll" "$ROOT/bootstrap/holyfitra_runtime.c" -o "$WORK/io"
set +e
(cd "$ROOT" && "$WORK/io")
io_status=$?
set -e
test "$io_status" -eq 2
"$BUILD" --target=aarch64-linux-android21 "$ROOT/bootstrap/io.hf" -o "$WORK/io.aarch64.ll"
clang --target=aarch64-linux-android21 -c "$WORK/io.aarch64.ll" -o "$WORK/io.aarch64.o"
test -s "$WORK/io.aarch64.o"

clang -O1 -g -fno-omit-frame-pointer -fsanitize=address,undefined -fno-sanitize-recover=all \
  "$ROOT/bootstrap/holyfitra_runtime.c" "$ROOT/bootstrap/test_holyfitra_runtime.c" \
  -o "$WORK/runtime_san"
ASAN_OPTIONS=detect_leaks=1:halt_on_error=1 UBSAN_OPTIONS=halt_on_error=1 "$WORK/runtime_san" >/dev/null

"$BUILD" --target=aarch64-linux-android21 "$ROOT/bootstrap/hello.hf" -o "$WORK/hello.aarch64.ll"
clang --target=aarch64-linux-android21 -c "$WORK/hello.aarch64.ll" -o "$WORK/hello.aarch64.o"
test -s "$WORK/hello.aarch64.o"

if "$BUILD" "$ROOT/bootstrap/invalid_type.hf" >"$WORK/invalid.out" 2>"$WORK/invalid.err"; then
  echo "invalid fixture unexpectedly accepted" >&2
  exit 1
fi
grep -F "declared type does not match initializer" "$WORK/invalid.err" >/dev/null

# Verify the seed command itself works without Python in PATH or environment.
env -i PATH="$(dirname "$(command -v clang)"):$(dirname "$(command -v clang++)"):/usr/bin:/bin" HOME="$WORK/home" "$BUILD" --help >/dev/null

printf 'bootstrap_host=passed\\nbootstrap_aggregate=passed\\nbootstrap_io=passed\\nbootstrap_runtime_sanitizer=passed\\nbootstrap_invalid=passed\\nbootstrap_aarch64_object_bytes=%s\nbootstrap_python_free_help=passed\n' "$(stat -c%s "$WORK/hello.aarch64.o")"
