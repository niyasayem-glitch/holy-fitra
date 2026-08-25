#!/usr/bin/env bash
# Execute only on real ARM64 Linux/Android hardware. This script is deliberately
# not an emulator or cross-compile substitute.
set -euo pipefail

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
MACHINE=$(uname -m)
case "$MACHINE" in
  aarch64|arm64) ;;
  *)
    printf '{"schema":"holyfitra.arm64-i64-validation/v1","status":"not-run","reason":"requires-real-arm64","machine":"%s"}\n' "$MACHINE"
    exit 77
    ;;
esac

command -v python3 >/dev/null
command -v clang >/dev/null

WORK=$(mktemp -d "${TMPDIR:-/tmp}/holyfitra-arm64-i64.XXXXXX")
trap 'rm -rf "$WORK"' EXIT
OUTPUT="$WORK/hf_arm64_i64_input"
SOURCE="$ROOT/language_benchmarks/hf_arm64_i64_input.hf"

python3 "$ROOT/holyfitra_compiler.py" build "$SOURCE" -o "$OUTPUT" >/dev/null

run_case() {
  local expected=$1
  shift
  set +e
  "$OUTPUT" "$@" >/dev/null 2>&1
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

DEVICE=${HOSTNAME:-unknown}
if command -v getprop >/dev/null; then
  DEVICE=$(getprop ro.product.model 2>/dev/null || printf unknown)
fi
printf '{"schema":"holyfitra.arm64-i64-validation/v1","status":"passed","machine":"%s","device":"%s","cases":7,"compiler":"native-termux-or-linux-clang"}\n' "$MACHINE" "$DEVICE"
