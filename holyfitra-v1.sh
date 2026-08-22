#!/usr/bin/env bash
set -euo pipefail

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
BUILD_DIR="${HOLYFITRA_V1_BUILD_DIR:-$ROOT/.holyfitra/v1}"
SEED="$BUILD_DIR/holyfitra-bootstrap"
RUN_TIMEOUT="${HOLYFITRA_V1_TIMEOUT:-30}"
SEED_OPT="${HOLYFITRA_SEED_OPT:-O0}"

native_target() {
  if [[ -n "${HOLYFITRA_TARGET:-}" ]]; then
    printf '%s\n' "$HOLYFITRA_TARGET"
    return
  fi
  local machine
  machine="$(uname -m)"
  case "$machine" in
    aarch64|arm64)
      if [[ "${PREFIX:-}" == *com.termux/files/usr ]]; then
        printf '%s\n' 'aarch64-linux-android'
      else
        printf '%s\n' 'aarch64-unknown-linux-gnu'
      fi
      ;;
    armv7l|armv8l|arm)
      if [[ "${PREFIX:-}" == *com.termux/files/usr ]]; then
        printf '%s\n' 'armv7a-linux-androideabi'
      else
        printf '%s\n' 'armv7-unknown-linux-gnueabihf'
      fi
      ;;
    x86_64|amd64) printf '%s\n' 'x86_64-pc-linux-gnu' ;;
    i686|x86) printf '%s\n' 'i686-pc-linux-gnu' ;;
    *) printf '%s-unknown-linux-gnu\n' "$machine" ;;
  esac
}

TARGET="$(native_target)"
CC="${HOLYFITRA_CC:-${CC:-clang}}"
CXX="${HOLYFITRA_CXX:-${CXX:-clang++}}"

usage() {
  cat <<'EOF'
usage:
  holyfitra-v1.sh doctor
  holyfitra-v1.sh build-seed
  holyfitra-v1.sh check INPUT.hf [--target TRIPLE]
  holyfitra-v1.sh emit INPUT.hf -o OUTPUT.ll [--target TRIPLE]
  holyfitra-v1.sh build INPUT.hf -o OUTPUT [--target TRIPLE]
  holyfitra-v1.sh run INPUT.hf [--target TRIPLE]
  holyfitra-v1.sh test PROJECT_OR_TESTS_DIR
  holyfitra-v1.sh package INPUT.hf -o OUTPUT.json [--version VERSION] [--target TRIPLE]

Environment:
  HOLYFITRA_TARGET   Override the native LLVM target triple.
  HOLYFITRA_CC       C compiler/driver used for native linking.
  HOLYFITRA_CXX      C++ compiler used to build the seed compiler.
  HOLYFITRA_V1_TIMEOUT  Execution timeout in seconds; default: 30.
  HOLYFITRA_SEED_OPT    Seed compiler optimization level; default: O0.

On Termux, install the native toolchain with:
  pkg install python clang llvm coreutils findutils
EOF
}

need_command() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "holyfitra-v1: required command not found: $1" >&2
    if [[ "${PREFIX:-}" == *com.termux/files/usr ]]; then
      echo "holyfitra-v1: in Termux, install it with: pkg install clang llvm coreutils findutils" >&2
    fi
    exit 127
  }
}

validate_timeout() {
  if [[ ! "$RUN_TIMEOUT" =~ ^([1-9][0-9]*([.][0-9]+)?|0[.]([0-9]*[1-9][0-9]*))$ ]]; then
    echo 'holyfitra-v1: HOLYFITRA_V1_TIMEOUT must be a positive number' >&2
    exit 2
  fi
}

is_native_target() {
  [[ "$1" == "host" || "$1" == "$(native_target)" ]]
}

build_seed() {
  need_command "$CXX"
  case "$SEED_OPT" in
    O0|O1|O2|O3) ;;
    *) echo 'holyfitra-v1: HOLYFITRA_SEED_OPT must be O0, O1, O2, or O3' >&2; exit 2 ;;
  esac
  mkdir -p "$BUILD_DIR"
  "$CXX" -std=c++17 "-$SEED_OPT" -Wall -Wextra -Werror -pedantic \
    "$ROOT/holyfitra_bootstrap.cpp" -o "$SEED"
  chmod 755 "$SEED"
}

ensure_seed() {
  if [[ ! -x "$SEED" || "$ROOT/holyfitra_bootstrap.cpp" -nt "$SEED" ]]; then
    build_seed
  fi
}

parse_common_options() {
  INPUT=""
  OUTPUT=""
  TARGET="$(native_target)"
  VERSION="1.0.0"
  while (($#)); do
    case "$1" in
      --target=*) TARGET="${1#--target=}"; shift ;;
      --target) (($# >= 2)) || { echo 'holyfitra-v1: --target requires a value' >&2; exit 2; }; TARGET="$2"; shift 2 ;;
      -o|--output) (($# >= 2)) || { echo 'holyfitra-v1: -o requires a value' >&2; exit 2; }; OUTPUT="$2"; shift 2 ;;
      --version) (($# >= 2)) || { echo 'holyfitra-v1: --version requires a value' >&2; exit 2; }; VERSION="$2"; shift 2 ;;
      --version=*) VERSION="${1#--version=}"; shift ;;
      -*) echo "holyfitra-v1: unknown option: $1" >&2; exit 2 ;;
      *) [[ -z "$INPUT" ]] || { echo 'holyfitra-v1: multiple inputs are unsupported' >&2; exit 2; }; INPUT="$1"; shift ;;
    esac
  done
  [[ -n "$INPUT" ]] || { echo 'holyfitra-v1: input is required' >&2; exit 2; }
  if [[ "$TARGET" == "host" ]]; then
    TARGET="$(native_target)"
  fi
}

verify_llvm() {
  local llvm_path="$1"
  need_command "$CC"
  local object_path
  object_path="$(mktemp "${TMPDIR:-/tmp}/holyfitra-v1-verify.XXXXXX.o")"
  trap 'rm -f "$object_path"' RETURN
  if is_native_target "$TARGET"; then
    "$CC" -x ir -c "$llvm_path" -o "$object_path"
  else
    "$CC" -x ir -target "$TARGET" -c "$llvm_path" -o "$object_path"
  fi
  rm -f "$object_path"
  trap - RETURN
}

emit_file() {
  parse_common_options "$@"
  [[ -f "$INPUT" ]] || { echo "holyfitra-v1: input does not exist: $INPUT" >&2; exit 1; }
  [[ -n "$OUTPUT" ]] || { echo 'holyfitra-v1: emit requires -o OUTPUT.ll' >&2; exit 2; }
  ensure_seed
  mkdir -p "$(dirname -- "$OUTPUT")"
  local temporary
  temporary="$(mktemp "${TMPDIR:-/tmp}/holyfitra-v1-emit.XXXXXX.ll")"
  trap 'rm -f "$temporary"' RETURN
  "$SEED" --target="$TARGET" "$INPUT" -o "$temporary"
  verify_llvm "$temporary"
  cp "$temporary" "$OUTPUT"
  rm -f "$temporary"
  trap - RETURN
  printf '{"ok":true,"command":"emit","output":"%s","target":"%s"}\n' "$OUTPUT" "$TARGET"
}

build_file() {
  parse_common_options "$@"
  [[ -f "$INPUT" ]] || { echo "holyfitra-v1: input does not exist: $INPUT" >&2; exit 1; }
  [[ -n "$OUTPUT" ]] || { echo 'holyfitra-v1: build requires -o OUTPUT' >&2; exit 2; }
  ensure_seed
  need_command "$CC"
  mkdir -p "$(dirname -- "$OUTPUT")"
  local temporary
  temporary="$(mktemp "${TMPDIR:-/tmp}/holyfitra-v1-build.XXXXXX.ll")"
  trap 'rm -f "$temporary"' RETURN
  "$SEED" --target="$TARGET" "$INPUT" -o "$temporary"
  verify_llvm "$temporary"
  if is_native_target "$TARGET"; then
    "$CC" -O2 "$temporary" -o "$OUTPUT"
  else
    "$CC" -target "$TARGET" -O2 "$temporary" -o "$OUTPUT"
  fi
  chmod 755 "$OUTPUT"
  rm -f "$temporary"
  trap - RETURN
  printf '{"ok":true,"command":"build","output":"%s","target":"%s"}\n' "$OUTPUT" "$TARGET"
}

check_file() {
  parse_common_options "$@"
  [[ -f "$INPUT" ]] || { echo "holyfitra-v1: input does not exist: $INPUT" >&2; exit 1; }
  ensure_seed
  local temporary
  temporary="$(mktemp "${TMPDIR:-/tmp}/holyfitra-v1-check.XXXXXX.ll")"
  trap 'rm -f "$temporary"' RETURN
  "$SEED" --target="$TARGET" "$INPUT" -o "$temporary" >/dev/null
  verify_llvm "$temporary"
  rm -f "$temporary"
  trap - RETURN
  printf '{"ok":true,"command":"check","input":"%s","target":"%s"}\n' "$INPUT" "$TARGET"
}

run_file() {
  parse_common_options "$@"
  [[ -f "$INPUT" ]] || { echo "holyfitra-v1: input does not exist: $INPUT" >&2; exit 1; }
  need_command timeout
  validate_timeout
  local executable
  executable="$(mktemp "${TMPDIR:-/tmp}/holyfitra-v1-run.XXXXXX")"
  trap 'rm -f "$executable"' RETURN
  build_file "$INPUT" -o "$executable" --target "$TARGET" >/dev/null
  set +e
  timeout --preserve-status "$RUN_TIMEOUT" "$executable"
  local status=$?
  set -e
  rm -f "$executable"
  trap - RETURN
  return "$status"
}

test_project() {
  local root="$1"
  [[ -n "$root" ]] || { echo 'holyfitra-v1: test path is required' >&2; exit 2; }
  need_command timeout
  validate_timeout
  local tests_dir="$root"
  if [[ -d "$root/tests" ]]; then tests_dir="$root/tests"; fi
  [[ -d "$tests_dir" ]] || { echo "holyfitra-v1: test directory does not exist: $tests_dir" >&2; exit 1; }
  local found=0 passed=0 failed=0
  while IFS= read -r -d '' source; do
    found=$((found + 1))
    local executable status
    executable="$(mktemp "${TMPDIR:-/tmp}/holyfitra-v1-test.XXXXXX")"
    if build_file "$source" -o "$executable" >/dev/null 2>&1 && timeout --preserve-status "$RUN_TIMEOUT" "$executable" >/dev/null 2>&1; then
      passed=$((passed + 1))
      printf 'PASS %s\n' "$source"
    else
      failed=$((failed + 1))
      printf 'FAIL %s\n' "$source" >&2
    fi
    rm -f "$executable"
  done < <(find "$tests_dir" -type f -name '*.hf' -print0 | sort -z)
  [[ "$found" -gt 0 ]] || { echo 'holyfitra-v1: no .hf tests found' >&2; return 1; }
  printf '{"ok":%s,"command":"test","found":%d,"passed":%d,"failed":%d}\n' "$([[ "$failed" -eq 0 ]] && echo true || echo false)" "$found" "$passed" "$failed"
  [[ "$failed" -eq 0 ]]
}

package_file() {
  parse_common_options "$@"
  [[ -f "$INPUT" ]] || { echo "holyfitra-v1: input does not exist: $INPUT" >&2; exit 1; }
  [[ -n "$OUTPUT" ]] || { echo 'holyfitra-v1: package requires -o OUTPUT.json' >&2; exit 2; }
  ensure_seed
  need_command sha256sum
  mkdir -p "$(dirname -- "$OUTPUT")"
  local source_hash seed_hash name source_file
  source_hash="$(sha256sum "$INPUT" | awk '{print $1}')"
  seed_hash="$(sha256sum "$SEED" | awk '{print $1}')"
  source_file="$(basename "$INPUT")"
  name="$(basename "$INPUT" .hf)"
  [[ "$source_file" =~ ^[A-Za-z0-9_.-]+\.hf$ ]] || { echo 'holyfitra-v1: source filename contains unsupported JSON characters' >&2; exit 1; }
  [[ "$name" =~ ^[A-Za-z0-9_.-]+$ ]] || { echo 'holyfitra-v1: source name contains unsupported JSON characters' >&2; exit 1; }
  [[ "$VERSION" =~ ^[A-Za-z0-9][A-Za-z0-9.+-]*$ ]] || { echo 'holyfitra-v1: version contains unsupported JSON characters' >&2; exit 1; }
  [[ "$TARGET" =~ ^[A-Za-z0-9_.+:-]+$ ]] || { echo 'holyfitra-v1: target contains unsupported JSON characters' >&2; exit 1; }
  printf '{\n  "schema": "holyfitra.v1.package",\n  "name": "%s",\n  "version": "%s",\n  "source": {"path": "%s", "sha256": "%s"},\n  "compiler": {"seed": "holyfitra-bootstrap", "sha256": "%s", "target": "%s"},\n  "python_required": false,\n  "android_execution": false\n}\n' "$name" "$VERSION" "$source_file" "$source_hash" "$seed_hash" "$TARGET" >"$OUTPUT"
  printf '{"ok":true,"command":"package","manifest":"%s","source_sha256":"%s"}\n' "$OUTPUT" "$source_hash"
}

doctor() {
  local clang_status=missing clangpp_status=missing timeout_status=missing sha_status=missing
  command -v "$CC" >/dev/null 2>&1 && clang_status=available || true
  command -v "$CXX" >/dev/null 2>&1 && clangpp_status=available || true
  command -v timeout >/dev/null 2>&1 && timeout_status=available || true
  command -v sha256sum >/dev/null 2>&1 && sha_status=available || true
  printf '{"v1":true,"termux":%s,"architecture":"%s","native_target":"%s","seed_optimization":"%s","python_required":false,"clang":"%s","clang++":"%s","timeout":"%s","sha256sum":"%s","android_execution":"not_available_without_sdk_ndk_device"}\n' \
    "$([[ "${PREFIX:-}" == *com.termux/files/usr ]] && echo true || echo false)" "$(uname -m)" "$TARGET" "$SEED_OPT" "$clang_status" "$clangpp_status" "$timeout_status" "$sha_status"
}

command_name="${1:-}"
shift || true
case "$command_name" in
  doctor) doctor ;;
  version|--version) ensure_seed; "$SEED" --version ;;
  build-seed) (($# == 0)) || { usage >&2; exit 2; }; build_seed; printf '{"ok":true,"command":"build-seed","seed":"%s"}\n' "$SEED" ;;
  check) check_file "$@" ;;
  emit) emit_file "$@" ;;
  build) build_file "$@" ;;
  run) run_file "$@" ;;
  test) (($# == 1)) || { echo 'usage: holyfitra-v1.sh test PROJECT_OR_TESTS_DIR' >&2; exit 2; }; test_project "$1" ;;
  package) package_file "$@" ;;
  -h|--help|help) usage ;;
  *) usage >&2; exit 2 ;;
esac
