#!/usr/bin/env bash
# Reproducible AArch64 user-mode emulation check. It is not hardware evidence.
set -euo pipefail

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
QEMU=${QEMU_AARCH64:-qemu-aarch64}
CLANG=${CLANG:-clang}
SYSROOT=${AARCH64_SYSROOT:-/usr/aarch64-linux-gnu}
SOURCE="$ROOT/language_benchmarks/hf_arm64_i64_input.hf"

command -v "$QEMU" >/dev/null
command -v "$CLANG" >/dev/null
test -d "$SYSROOT"

WORK=$(mktemp -d "${TMPDIR:-/tmp}/holyfitra-qemu-aarch64.XXXXXX")
trap 'rm -rf "$WORK"' EXIT
LLVM="$WORK/hf_arm64_i64_input.ll"
BINARY="$WORK/hf_arm64_i64_input"

python3 "$ROOT/holyfitra_compiler.py" emit-llvm "$SOURCE" --target aarch64-unknown-linux-gnu -o "$LLVM" >/dev/null
"$CLANG" --target=aarch64-linux-gnu --gcc-toolchain=/usr -O2 "$LLVM" -o "$BINARY"
file "$BINARY" | grep -F 'ARM aarch64' >/dev/null

run_case() {
  local expected=$1
  shift
  set +e
  "$QEMU" -L "$SYSROOT" "$BINARY" "$@" >/dev/null 2>&1
  local actual=$?
  set -e
  if [ "$actual" -ne "$expected" ]; then
    printf 'case failure: expected exit %s, got %s\n' "$expected" "$actual" >&2
    exit 1
  fi
}

run_case 7
run_case 11 9223372036854775807
run_case 12 -9223372036854775808
run_case 13 -9
run_case 7 9223372036854775808
run_case 7 -9223372036854775809
run_case 7 12x

QEMU_VERSION=$("$QEMU" --version | head -1 | sed 's/"/\\"/g')
printf '{"schema":"holyfitra.qemu-aarch64-i64-validation/v1","status":"passed","emulator":"%s","sysroot":"%s","cases":7,"evidence":"emulator-only"}\n' "$QEMU_VERSION" "$SYSROOT"
