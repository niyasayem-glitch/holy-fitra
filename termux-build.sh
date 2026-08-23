#!/usr/bin/env bash
set -euo pipefail

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
PYTHON="${HOLYFITRA_PYTHON:-}"

usage() {
  cat <<'EOF'
usage:
  bash termux-build.sh setup [--dry-run]
  bash termux-build.sh test [--host-tests|--native-tests]
  bash termux-build.sh install-v1
  bash termux-build.sh v1 COMMAND [ARGUMENTS...]
  bash termux-build.sh doctor

The unified Termux entry point replaces the former termux-setup.sh,
install-holyfitra-v1.sh, and test_holyfitra_v1.sh scripts.

Commands:
  setup       Install the no-sudo Termux packages and Python CLI.
  test        Run the Python, native, bootstrap, CLI, and v1 gates.
  install-v1  Install the Python-free v1 compiler into a user prefix.
  v1          Forward arguments to the Python-free holyfitra-v1 engine.
  doctor      Print the normal CLI environment report.

Environment:
  HOLYFITRA_PREFIX       User prefix for install-v1; defaults to $HOME/.local.
  HOLYFITRA_TARGET       Override the native target triple.
  HOLYFITRA_CC/CXX       Select native C/C++ compilers.
EOF
}

python_command() {
  if [[ -n "$PYTHON" ]]; then
    command -v "$PYTHON" >/dev/null 2>&1 || { echo "termux-build: Python command not found: $PYTHON" >&2; exit 127; }
    printf '%s\n' "$PYTHON"
  elif command -v python3 >/dev/null 2>&1; then
    command -v python3
  elif command -v python >/dev/null 2>&1; then
    command -v python
  else
    echo 'termux-build: Python 3 is required; in Termux run: pkg install python' >&2
    exit 127
  fi
}

termux_environment() {
  [[ "${PREFIX:-}" == *com.termux/files/usr ]]
}

setup_termux() {
  local dry_run=0
  case "${1:-}" in
    --dry-run) dry_run=1 ;;
    -h|--help) usage; return 0 ;;
    "") ;;
    *) echo "termux-build setup: unknown option: $1" >&2; exit 2 ;;
  esac
  if ! command -v pkg >/dev/null 2>&1; then
    echo 'termux-build setup: this command must run inside Termux.' >&2
    echo 'termux-build setup: install Termux from https://termux.dev and retry.' >&2
    exit 1
  fi
  local machine
  machine="$(uname -m)"
  if [[ "$machine" != "aarch64" && "$machine" != "arm64" ]]; then
    echo "termux-build setup: warning: detected $machine; ARM64 is expected for native Android execution." >&2
  fi
  local packages=(python clang llvm coreutils findutils diffutils cmake make git pkg-config tar gzip)
  if pkg list-all 2>/dev/null | grep -q '^python-numpy/'; then
    packages+=(python-numpy)
  fi
  if (( dry_run )); then
    printf '+ pkg update -y\n+ pkg install -y'
    printf ' %q' "${packages[@]}"
    printf '\nTermux setup dry run complete. No files were changed.\n'
    return 0
  fi
  pkg update -y
  pkg install -y "${packages[@]}"
  local python
  python="$(python_command)"
  "$python" -m pip install -e "$ROOT" --no-deps --no-build-isolation --no-warn-script-location
  mkdir -p "$HOME/.local/bin"
  cat > "$HOME/.local/bin/holyfitra-env" <<EOF
# Holy Fitra Termux environment. Source this file from any directory.
export PATH="\$HOME/.local/bin:\$PATH"
export HOLYFITRA_ROOT="$ROOT"
EOF
  chmod 644 "$HOME/.local/bin/holyfitra-env"
  if [[ ! -x "$HOME/.local/bin/holyfitra" ]]; then
    cat > "$HOME/.local/bin/holyfitra" <<EOF
#!/usr/bin/env bash
exec "$ROOT/holyfitra" "\$@"
EOF
    chmod 755 "$HOME/.local/bin/holyfitra"
  fi
  export PATH="$HOME/.local/bin:$PATH"
  "$HOME/.local/bin/holyfitra" --help >/dev/null
  "$ROOT/holyfitra-v1.sh" doctor >/dev/null
  echo 'Holy Fitra Termux setup complete.'
  echo 'Source the environment with: source "$HOME/.local/bin/holyfitra-env"'
  echo 'Then run: holyfitra doctor'
}

install_v1() {
  local termux=0
  termux_environment && termux=1 || true
  local install_prefix
  if (( termux )); then
    install_prefix="${HOLYFITRA_PREFIX:-${HOME:+$HOME/.local}}"
  else
    install_prefix="${HOLYFITRA_PREFIX:-${PREFIX:-${HOME:+$HOME/.local}}}"
  fi
  local cxx="${HOLYFITRA_CXX:-${CXX:-clang++}}"
  if [[ -z "$install_prefix" ]]; then
    echo 'termux-build install-v1: set HOME or HOLYFITRA_PREFIX to a writable user prefix' >&2
    exit 2
  fi
  if ! command -v "$cxx" >/dev/null 2>&1; then
    echo "termux-build install-v1: compiler not found: $cxx" >&2
    if (( termux )); then echo 'termux-build install-v1: run: pkg install clang' >&2; fi
    exit 127
  fi
  local dest="$install_prefix/libexec/holyfitra-v1"
  local bin="$install_prefix/bin"
  mkdir -p "$dest" "$bin"
  cp "$ROOT/holyfitra-v1.sh" "$dest/holyfitra-v1.sh"
  cp "$ROOT/holyfitra_bootstrap.cpp" "$dest/holyfitra_bootstrap.cpp"
  chmod 755 "$dest/holyfitra-v1.sh"
  HOLYFITRA_V1_BUILD_DIR="$dest/.holyfitra/v1" HOLYFITRA_CXX="$cxx" "$dest/holyfitra-v1.sh" build-seed >/dev/null
  cat > "$bin/holyfitra-v1" <<EOF
#!/usr/bin/env bash
exec "$dest/holyfitra-v1.sh" "\$@"
EOF
  chmod 755 "$bin/holyfitra-v1"
  printf '%s\n' "installed $bin/holyfitra-v1"
  if [[ ":${PATH:-}:" != *":$bin:"* ]]; then
    printf '%s\n' "add it to PATH with: export PATH=\"$bin:\$PATH\""
  fi
}

v1_test() {
  local driver="$ROOT/holyfitra-v1.sh"
  local work
  work="$(mktemp -d "${TMPDIR:-/tmp}/holyfitra-v1-test.XXXXXX")"
  cat > "$work/good.hf" <<'EOF'
module v1_good
fn add(a: i32, b: i32) -> i32 {
    return a + b
}
fn main() -> i32 {
    return add(20, 22)
}
EOF
  cat > "$work/test_zero.hf" <<'EOF'
module v1_test
fn main() -> i32 {
    return 0
}
EOF
  cat > "$work/bad.hf" <<'EOF'
module v1_bad
this construct is not part of the v1 grammar
EOF
  cat > "$work/deep.hf" <<'EOF'
module v1_deep
fn main() -> i32 {
    return
EOF
  for _ in $(seq 1 513); do printf '(' >> "$work/deep.hf"; done
  printf '1' >> "$work/deep.hf"
  for _ in $(seq 1 513); do printf ')' >> "$work/deep.hf"; done
  printf '\n}\n' >> "$work/deep.hf"
  cat > "$work/huge_array.hf" <<'EOF'
module v1_huge_array
fn main(a: [999999999]i32) -> i32 {
    return 0
}
EOF
  printf 'module v1_huge_string\nfn main() -> i32 { return "' > "$work/huge_string.hf"
  head -c 1048577 /dev/zero | tr '\0' 'x' >> "$work/huge_string.hf"
  printf '" }\n' >> "$work/huge_string.hf"
  truncate -s 8388609 "$work/oversized.hf"
  export HOLYFITRA_V1_BUILD_DIR="$work/build"
  "$driver" build-seed >/dev/null
  "$driver" check "$work/good.hf" >/dev/null
  "$driver" emit "$work/good.hf" -o "$work/one.ll" >/dev/null
  "$driver" emit "$work/good.hf" -o "$work/two.ll" >/dev/null
  cmp "$work/one.ll" "$work/two.ll"
  "$driver" build "$work/good.hf" -o "$work/good" >/dev/null
  set +e
  "$work/good" >/dev/null
  local status=$?
  set -e
  test "$status" -eq 42
  for invalid in bad.hf deep.hf oversized.hf huge_array.hf huge_string.hf; do
    if "$driver" check "$work/$invalid" >/dev/null 2>&1; then
      echo "termux-build v1-test: invalid source unexpectedly accepted: $invalid" >&2
      return 1
    fi
  done
  mkdir -p "$work/project/tests"
  cp "$work/test_zero.hf" "$work/project/tests/smoke.hf"
  "$driver" test "$work/project" >/dev/null
  "$driver" package "$work/good.hf" -o "$work/good.json" >/dev/null
  grep -q '"python_required": false' "$work/good.json"
  grep -q '"android_execution": false' "$work/good.json"
  printf '%s\n' 'holyfitra_v1_driver=passed'
  rm -rf "$work"
}

run_tests() {
  local native_tests=0
  for argument in "$@"; do
    case "$argument" in
      --host-tests|--native-tests) native_tests=1 ;;
      -h|--help) usage; return 0 ;;
      *) echo "termux-build test: unknown option: $argument" >&2; exit 2 ;;
    esac
  done
  if termux_environment; then native_tests=1; fi
  local python
  python="$(python_command)"
  cd "$ROOT"
  # Discover every tracked test module so new tests cannot silently bypass
  # the canonical Termux-compatible regression gate.
  "$python" -m unittest -q
  "$python" validate_nibbleflow.py
  "$python" validate_holy_fitra_ragged.py
  if (( native_tests )); then
    command -v clang >/dev/null 2>&1 || { echo 'termux-build test: clang is required; run: pkg install clang' >&2; exit 127; }
    command -v clang++ >/dev/null 2>&1 || { echo 'termux-build test: clang++ is required; run: pkg install clang' >&2; exit 127; }
    clang -O2 -c holy_fitra_ragged_kernel.c -o "${TMPDIR:-/tmp}/holy_fitra_ragged_termux.o"
    clang++ -O2 -std=c++17 -pthread -I. "${TMPDIR:-/tmp}/holy_fitra_ragged_termux.o" holy_fitra_dispatch.cpp holy_fitra_ragged_scheduler.cpp test_holy_fitra_ragged_scheduler.cpp -o "${TMPDIR:-/tmp}/holy_fitra_ragged_scheduler_termux_test"
    "${TMPDIR:-/tmp}/holy_fitra_ragged_scheduler_termux_test"
  fi
  ./holyfitra --help >/dev/null
  ./holyfitra doctor >/dev/null
  ./holyfitra ai providers >/dev/null
  ./holyfitra contracts >/dev/null
  ./holyfitra tui . --snapshot >/dev/null
  local bench_root
  bench_root="$(mktemp -d)"
  ./holyfitra init "$bench_root/project" --name termux_validation >/dev/null
  ./holyfitra bench "$bench_root/project" --repeats 1 >/dev/null
  bash bootstrap/test_bootstrap.sh >/dev/null
  bash -n holyfitra holyfitra-v1.sh termux-build.sh make-holyfitra-v1-release.sh
  v1_test
  rm -rf "$bench_root"
  printf '%s\n' 'Holy Fitra Termux-compatible validation passed.'
}

command_name="${1:-test}"
if [[ "$command_name" == "--host-tests" || "$command_name" == "--native-tests" ]]; then
  set -- test "$@"
  command_name="test"
else
  shift || true
fi
case "$command_name" in
  setup) setup_termux "$@" ;;
  test) run_tests "$@" ;;
  install-v1) (($# == 0)) || { echo 'termux-build install-v1: no arguments expected' >&2; exit 2; }; install_v1 ;;
  v1) exec "$ROOT/holyfitra-v1.sh" "$@" ;;
  doctor) (($# == 0)) || { echo 'termux-build doctor: no arguments expected' >&2; exit 2; }; "$ROOT/holyfitra" doctor ;;
  -h|--help|help) usage ;;
  *) echo "termux-build: unknown command: $command_name" >&2; usage >&2; exit 2 ;;
esac
