#!/usr/bin/env bash
set -euo pipefail

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
HOST_TESTS=0
PYTHON="${HOLYFITRA_PYTHON:-}"

usage() {
  cat <<'EOF'
usage: bash termux-build.sh [--host-tests|--native-tests]

Runs the Python/compiler validation suite. On a real Termux session, native
ARM64 tests are enabled automatically. --host-tests and --native-tests are
kept as aliases for compatibility with existing CI commands.
EOF
}

for argument in "$@"; do
  case "$argument" in
    --host-tests|--native-tests) HOST_TESTS=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "termux-build: unknown option: $argument" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ -z "$PYTHON" ]]; then
  if command -v python3 >/dev/null 2>&1; then
    PYTHON="$(command -v python3)"
  elif command -v python >/dev/null 2>&1; then
    PYTHON="$(command -v python)"
  else
    echo 'termux-build: Python 3 is required; in Termux run: pkg install python' >&2
    exit 127
  fi
fi

if [[ "${PREFIX:-}" == *com.termux/files/usr ]]; then
  HOST_TESTS=1
fi

cd "$ROOT"

"$PYTHON" -m unittest -q \
  test_holyfitra_compiler.py \
  test_holyfitra_contracts.py \
  test_holyfitra_quant_tuning.py \
  test_holyfitra_dashboard.py \
  test_holyfitra_ui.py \
  test_holyfitra_data.py \
  test_holyfitra_qat_deploy.py \
  test_holyfitra_hybrid.py \
  test_language_core.py \
  test_hyperir.py \
  test_package.py \
  test_holy_fitra_runtime.py \
  test_holy_fitra_execution_plan.py \
  test_holy_fitra_ragged.py \
  test_holy_fitra_dynamic_prefill.py \
  test_smooth_runtime.py

"$PYTHON" validate_nibbleflow.py
"$PYTHON" validate_holy_fitra_ragged.py

if (( HOST_TESTS )); then
  command -v clang >/dev/null 2>&1 || { echo 'termux-build: clang is required; run: pkg install clang' >&2; exit 127; }
  command -v clang++ >/dev/null 2>&1 || { echo 'termux-build: clang++ is required; run: pkg install clang' >&2; exit 127; }
  clang -O2 -c holy_fitra_ragged_kernel.c -o "${TMPDIR:-/tmp}/holy_fitra_ragged_termux.o"
  clang++ -O2 -std=c++17 -pthread -I. \
    "${TMPDIR:-/tmp}/holy_fitra_ragged_termux.o" \
    holy_fitra_dispatch.cpp \
    holy_fitra_ragged_scheduler.cpp \
    test_holy_fitra_ragged_scheduler.cpp \
    -o "${TMPDIR:-/tmp}/holy_fitra_ragged_scheduler_termux_test"
  "${TMPDIR:-/tmp}/holy_fitra_ragged_scheduler_termux_test"
fi

./holyfitra --help >/dev/null
./holyfitra doctor >/dev/null
./holyfitra contracts >/dev/null
./holyfitra tui . --snapshot >/dev/null
TERMUX_BENCH_ROOT="$(mktemp -d)"
trap 'rm -rf "$TERMUX_BENCH_ROOT"' EXIT
./holyfitra init "$TERMUX_BENCH_ROOT/project" --name termux_validation >/dev/null
./holyfitra bench "$TERMUX_BENCH_ROOT/project" --repeats 1 >/dev/null
bootstrap/test_bootstrap.sh >/dev/null
bash -n holyfitra holyfitra-v1.sh install-holyfitra-v1.sh termux-setup.sh termux-build.sh test_holyfitra_v1.sh
./test_holyfitra_v1.sh >/dev/null
printf '%s\n' 'Holy Fitra Termux-compatible validation passed.'
