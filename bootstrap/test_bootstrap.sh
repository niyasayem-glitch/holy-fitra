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

"$BUILD" "$ROOT/bootstrap/short_circuit.hf" -o "$WORK/short_circuit.ll"
grep -F 'phi i1' "$WORK/short_circuit.ll" >/dev/null
clang -O2 "$WORK/short_circuit.ll" "$ROOT/bootstrap/holyfitra_runtime.c" -o "$WORK/short_circuit"
(cd "$ROOT" && "$WORK/short_circuit")
"$BUILD" --target=aarch64-linux-android21 "$ROOT/bootstrap/short_circuit.hf" -o "$WORK/short_circuit.aarch64.ll"
clang --target=aarch64-linux-android21 -c "$WORK/short_circuit.aarch64.ll" -o "$WORK/short_circuit.aarch64.o"
test -s "$WORK/short_circuit.aarch64.o"

"$BUILD" "$ROOT/bootstrap/aggregates.hf" -o "$WORK/aggregates.ll"
clang -O2 "$WORK/aggregates.ll" -o "$WORK/aggregates"
set +e
"$WORK/aggregates"
aggregate_status=$?
set -e
test "$aggregate_status" -eq 42

"$BUILD" "$ROOT/bootstrap/selfhost_frontend.hf" -o "$WORK/selfhost_frontend.ll"
clang -O2 "$WORK/selfhost_frontend.ll" "$ROOT/bootstrap/holyfitra_runtime.c" -o "$WORK/selfhost_frontend"
set +e
(cd "$ROOT" && "$WORK/selfhost_frontend")
selfhost_frontend_status=$?
set -e
test "$selfhost_frontend_status" -eq 0
clang -O1 -g -fno-omit-frame-pointer -fsanitize=address,undefined -fno-sanitize-recover=all \
  "$WORK/selfhost_frontend.ll" "$ROOT/bootstrap/holyfitra_runtime.c" -o "$WORK/selfhost_frontend_san"
(cd "$ROOT" && ASAN_OPTIONS=detect_leaks=0:halt_on_error=1 UBSAN_OPTIONS=halt_on_error=1 "$WORK/selfhost_frontend_san")
"$BUILD" --target=aarch64-linux-android21 "$ROOT/bootstrap/selfhost_frontend.hf" -o "$WORK/selfhost_frontend.aarch64.ll"
clang --target=aarch64-linux-android21 -c "$WORK/selfhost_frontend.aarch64.ll" -o "$WORK/selfhost_frontend.aarch64.o"
test -s "$WORK/selfhost_frontend.aarch64.o"

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

"$BUILD" "$ROOT/bootstrap/buffer.hf" -o "$WORK/buffer.ll"
clang -O2 "$WORK/buffer.ll" "$ROOT/bootstrap/holyfitra_runtime.c" -o "$WORK/buffer"
set +e
(cd "$ROOT" && "$WORK/buffer")
buffer_status=$?
set -e
test "$buffer_status" -eq 4
"$BUILD" --target=aarch64-linux-android21 "$ROOT/bootstrap/buffer.hf" -o "$WORK/buffer.aarch64.ll"
clang --target=aarch64-linux-android21 -c "$WORK/buffer.aarch64.ll" -o "$WORK/buffer.aarch64.o"
test -s "$WORK/buffer.aarch64.o"

"$BUILD" "$ROOT/bootstrap/selfhost_symtable.hf" -o "$WORK/selfhost_symtable.ll"
clang -O2 "$WORK/selfhost_symtable.ll" "$ROOT/bootstrap/holyfitra_runtime.c" -o "$WORK/selfhost_symtable"
set +e
(cd "$ROOT" && "$WORK/selfhost_symtable")
symtable_status=$?
set -e
test "$symtable_status" -eq 3
"$BUILD" --target=aarch64-linux-android21 "$ROOT/bootstrap/selfhost_symtable.hf" -o "$WORK/selfhost_symtable.aarch64.ll"
clang --target=aarch64-linux-android21 -c "$WORK/selfhost_symtable.aarch64.ll" -o "$WORK/selfhost_symtable.aarch64.o"
test -s "$WORK/selfhost_symtable.aarch64.o"

"$BUILD" "$ROOT/bootstrap/selfhost_typechecker.hf" -o "$WORK/selfhost_typechecker.ll"
clang -O2 "$WORK/selfhost_typechecker.ll" "$ROOT/bootstrap/holyfitra_runtime.c" -o "$WORK/selfhost_typechecker"
(cd "$ROOT" && "$WORK/selfhost_typechecker")
"$BUILD" --target=aarch64-linux-android21 "$ROOT/bootstrap/selfhost_typechecker.hf" -o "$WORK/selfhost_typechecker.aarch64.ll"
clang --target=aarch64-linux-android21 -c "$WORK/selfhost_typechecker.aarch64.ll" -o "$WORK/selfhost_typechecker.aarch64.o"
test -s "$WORK/selfhost_typechecker.aarch64.o"

"$BUILD" "$ROOT/bootstrap/selfhost_emitter.hf" -o "$WORK/selfhost_emitter.ll"
clang -O2 "$WORK/selfhost_emitter.ll" "$ROOT/bootstrap/holyfitra_runtime.c" -o "$WORK/selfhost_emitter"
(cd "$ROOT" && "$WORK/selfhost_emitter")
test -s /tmp/holyfitra_selfhost_emitted.ll
clang -O2 /tmp/holyfitra_selfhost_emitted.ll -o "$WORK/selfhost_emitted_program"
set +e
"$WORK/selfhost_emitted_program"
emitted_status=$?
set -e
test "$emitted_status" -eq 42
"$BUILD" --target=aarch64-linux-android21 "$ROOT/bootstrap/selfhost_emitter.hf" -o "$WORK/selfhost_emitter.aarch64.ll"
clang --target=aarch64-linux-android21 -c "$WORK/selfhost_emitter.aarch64.ll" -o "$WORK/selfhost_emitter.aarch64.o"
test -s "$WORK/selfhost_emitter.aarch64.o"

"$BUILD" "$ROOT/bootstrap/selfhost_state1.hf" -o "$WORK/selfhost_state1.ll"
clang -O2 "$WORK/selfhost_state1.ll" "$ROOT/bootstrap/holyfitra_runtime.c" -o "$WORK/selfhost_state1"
(cd "$ROOT" && "$WORK/selfhost_state1")
test -s /tmp/holyfitra_state1_tokens.snapshot
test -s /tmp/holyfitra_state1_ast.snapshot
cp /tmp/holyfitra_state1_tokens.snapshot "$WORK/state1_tokens.first"
cp /tmp/holyfitra_state1_ast.snapshot "$WORK/state1_ast.first"
(cd "$ROOT" && "$WORK/selfhost_state1")
cmp -s "$WORK/state1_tokens.first" /tmp/holyfitra_state1_tokens.snapshot
cmp -s "$WORK/state1_ast.first" /tmp/holyfitra_state1_ast.snapshot
"$BUILD" --target=aarch64-linux-android21 "$ROOT/bootstrap/selfhost_state1.hf" -o "$WORK/selfhost_state1.aarch64.ll"
clang --target=aarch64-linux-android21 -c "$WORK/selfhost_state1.aarch64.ll" -o "$WORK/selfhost_state1.aarch64.o"
test -s "$WORK/selfhost_state1.aarch64.o"

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
grep -F "error[HF3001]" "$WORK/invalid.err" >/dev/null
grep -F "declared type does not match initializer" "$WORK/invalid.err" >/dev/null
grep -F "|" "$WORK/invalid.err" >/dev/null
grep -F "^" "$WORK/invalid.err" >/dev/null

if "$BUILD" "$ROOT/bootstrap/invalid_syntax.hf" >"$WORK/invalid_syntax.out" 2>"$WORK/invalid_syntax.err"; then
  echo "invalid syntax fixture unexpectedly accepted" >&2
  exit 1
fi
grep -F "error[HF1001]" "$WORK/invalid_syntax.err" >/dev/null
grep -F "|" "$WORK/invalid_syntax.err" >/dev/null
grep -F "^" "$WORK/invalid_syntax.err" >/dev/null

if "$BUILD" "$ROOT/bootstrap/invalid_name.hf" >"$WORK/invalid_name.out" 2>"$WORK/invalid_name.err"; then
  echo "invalid name fixture unexpectedly accepted" >&2
  exit 1
fi
grep -F "error[HF2001]" "$WORK/invalid_name.err" >/dev/null
grep -F "unknown value" "$WORK/invalid_name.err" >/dev/null

# Verify the seed command itself works without Python in PATH or environment.
env -i PATH="$(dirname "$(command -v clang)"):$(dirname "$(command -v clang++)"):/usr/bin:/bin" HOME="$WORK/home" "$BUILD" --help >/dev/null

printf 'bootstrap_host=passed\nbootstrap_short_circuit=passed\nbootstrap_aggregate=passed\nbootstrap_selfhost_frontend=passed\nbootstrap_io=passed\nbootstrap_buffer=passed\nbootstrap_symtable=passed\nbootstrap_typechecker=passed\nbootstrap_emitter=passed\nbootstrap_state1=passed\nbootstrap_runtime_sanitizer=passed\nbootstrap_diagnostics=passed\nbootstrap_invalid=passed\nbootstrap_aarch64_object_bytes=%s\nbootstrap_selfhost_aarch64_object_bytes=%s\nbootstrap_buffer_aarch64_object_bytes=%s\nbootstrap_symtable_aarch64_object_bytes=%s\nbootstrap_typechecker_aarch64_object_bytes=%s\nbootstrap_emitter_aarch64_object_bytes=%s\nbootstrap_state1_aarch64_object_bytes=%s\nbootstrap_python_free_help=passed\n' "$(stat -c%s "$WORK/hello.aarch64.o")" "$(stat -c%s "$WORK/selfhost_frontend.aarch64.o")" "$(stat -c%s "$WORK/buffer.aarch64.o")" "$(stat -c%s "$WORK/selfhost_symtable.aarch64.o")" "$(stat -c%s "$WORK/selfhost_typechecker.aarch64.o")" "$(stat -c%s "$WORK/selfhost_emitter.aarch64.o")" "$(stat -c%s "$WORK/selfhost_state1.aarch64.o")"
