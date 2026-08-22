#!/usr/bin/env bash
set -euo pipefail

HOST_TESTS=0
for argument in "$@"; do
  case "$argument" in
    --host-tests) HOST_TESTS=1 ;;
    *) echo "usage: $0 [--host-tests]" >&2; exit 2 ;;
  esac
done

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
cd "$ROOT"

python3 -m unittest -q \
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

python3 validate_nibbleflow.py
python3 validate_holy_fitra_ragged.py

if (( HOST_TESTS )); then
  clang -O2 -c holy_fitra_ragged_kernel.c -o /tmp/holy_fitra_ragged_termux.o
  clang++ -O2 -std=c++17 -pthread -I. \
    /tmp/holy_fitra_ragged_termux.o \
    holy_fitra_dispatch.cpp \
    holy_fitra_ragged_scheduler.cpp \
    test_holy_fitra_ragged_scheduler.cpp \
    -o /tmp/holy_fitra_ragged_scheduler_termux_test
  /tmp/holy_fitra_ragged_scheduler_termux_test
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
bash -n holyfitra-v1.sh test_holyfitra_v1.sh
./test_holyfitra_v1.sh >/dev/null
printf '%s\n' 'Holy Fitra Termux-compatible validation passed.'
