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
      if [[ "${PREFIX:-}" == *com.termux/files/usr ]]; then printf '%s\n' 'aarch64-linux-android'; else printf '%s\n' 'aarch64-unknown-linux-gnu'; fi
      ;;
    armv7l|armv8l|arm)
      if [[ "${PREFIX:-}" == *com.termux/files/usr ]]; then printf '%s\n' 'armv7a-linux-androideabi'; else printf '%s\n' 'armv7-unknown-linux-gnueabihf'; fi
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
  holyfitra-v1.sh presets
  holyfitra-v1.sh init DIRECTORY [--template basic|selfhost-core] [--name NAME]
  holyfitra-v1.sh build-seed
  holyfitra-v1.sh check PROJECT_OR_INPUT [--target TRIPLE]
  holyfitra-v1.sh emit PROJECT_OR_INPUT -o OUTPUT.ll [--target TRIPLE]
  holyfitra-v1.sh build PROJECT_OR_INPUT -o OUTPUT [--target TRIPLE]
  holyfitra-v1.sh run PROJECT_OR_INPUT [--target TRIPLE]
  holyfitra-v1.sh test PROJECT_OR_TESTS_DIR
  holyfitra-v1.sh package PROJECT_OR_INPUT -o OUTPUT.json [--version VERSION] [--target TRIPLE]
  holyfitra-v1.sh bundle PROJECT_OR_INPUT -o OUTPUT.tar.gz [--version VERSION] [--target TRIPLE]

Environment:
  HOLYFITRA_TARGET      Override the native LLVM target triple.
  HOLYFITRA_CC          C compiler/driver used for native linking.
  HOLYFITRA_CXX         C++ compiler used to build the seed compiler.
  HOLYFITRA_V1_TIMEOUT  Execution timeout in seconds; default: 30.
  HOLYFITRA_SEED_OPT    Seed compiler optimization level; default: O0.

On Termux, install the native toolchain with:
  pkg install clang llvm coreutils findutils tar gzip
EOF
}

need_command() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "holyfitra-v1: required command not found: $1" >&2
    if [[ "${PREFIX:-}" == *com.termux/files/usr ]]; then
      echo "holyfitra-v1: in Termux, install it with: pkg install clang llvm coreutils findutils tar gzip" >&2
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

is_native_target() { [[ "$1" == "host" || "$1" == "$(native_target)" ]]; }

build_seed() {
  need_command "$CXX"
  case "$SEED_OPT" in O0|O1|O2|O3) ;; *) echo 'holyfitra-v1: HOLYFITRA_SEED_OPT must be O0, O1, O2, or O3' >&2; exit 2 ;; esac
  mkdir -p "$BUILD_DIR"
  "$CXX" -std=c++17 "-$SEED_OPT" -Wall -Wextra -Werror -pedantic "$ROOT/holyfitra_bootstrap.cpp" -o "$SEED"
  chmod 755 "$SEED"
}

ensure_seed() { [[ -x "$SEED" && "$ROOT/holyfitra_bootstrap.cpp" -ot "$SEED" ]] || build_seed; }

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
  [[ "$TARGET" != "host" ]] || TARGET="$(native_target)"
}

resolve_input_source() {
  local candidate="$1"
  PROJECT_ROOT=""
  SOURCE_PATH=""
  SOURCE_REL=""
  PACKAGE_ROOT_MODE=false
  if [[ -d "$candidate" ]]; then
    PROJECT_ROOT="$(cd -- "$candidate" && pwd -P)"
    PACKAGE_ROOT_MODE=true
    for SOURCE_REL in src/main.hf main.hf; do
      if [[ -f "$PROJECT_ROOT/$SOURCE_REL" ]]; then SOURCE_PATH="$PROJECT_ROOT/$SOURCE_REL"; break; fi
    done
    [[ -n "$SOURCE_PATH" ]] || { echo "holyfitra-v1: project entry is missing; expected src/main.hf or main.hf in $PROJECT_ROOT" >&2; exit 1; }
  elif [[ -f "$candidate" ]]; then
    PROJECT_ROOT="$(cd -- "$(dirname -- "$candidate")" && pwd -P)"
    SOURCE_PATH="$PROJECT_ROOT/$(basename -- "$candidate")"
    SOURCE_REL="$(basename -- "$candidate")"
  else
    echo "holyfitra-v1: input does not exist: $candidate" >&2
    exit 1
  fi
  [[ "$SOURCE_REL" =~ ^[A-Za-z0-9_./-]+\.hf$ ]] || { echo 'holyfitra-v1: source path contains unsupported package characters' >&2; exit 1; }
}

source_paths() {
  local source_root="$1"
  if [[ "$PACKAGE_ROOT_MODE" != true ]]; then
    printf '%s\n' "$SOURCE_REL"
    return
  fi
  (
    cd -- "$source_root"
    find . -type f \( -name '*.hf' -o -name '*.hfmd' -o -name '*.md' -o -name '*.toml' \) -printf '%P\n' | LC_ALL=C sort
  )
}

source_inventory() {
  local source_root="$1"
  (
    cd -- "$source_root"
    source_paths "$source_root" | while IFS= read -r source; do
      [[ -n "$source" ]] || continue
      printf '%s\t%s\n' "$source" "$(sha256sum -- "$source" | awk '{print $1}')"
    done
  )
}

write_package_manifest() {
  local manifest="$1" version="$2" target="$3" source_root="$4" source_path="$5" source_rel="$6"
  local source_hash seed_hash source_tree_hash source_count package_name
  source_hash="$(sha256sum -- "$source_path" | awk '{print $1}')"
  seed_hash="$(sha256sum -- "$SEED" | awk '{print $1}')"
  source_tree_hash="$(source_inventory "$source_root" | sha256sum | awk '{print $1}')"
  source_count="$(source_inventory "$source_root" | awk 'END { print NR + 0 }')"
  package_name="$(basename -- "$source_path" .hf)"
  [[ "$package_name" =~ ^[A-Za-z0-9_.-]+$ ]] || { echo 'holyfitra-v1: source name contains unsupported JSON characters' >&2; exit 1; }
  [[ "$version" =~ ^[A-Za-z0-9][A-Za-z0-9.+-]*$ ]] || { echo 'holyfitra-v1: version contains unsupported JSON characters' >&2; exit 1; }
  [[ "$target" =~ ^[A-Za-z0-9_.+:-]+$ ]] || { echo 'holyfitra-v1: target contains unsupported JSON characters' >&2; exit 1; }
  printf '{\n  "schema": "holyfitra.v1.package",\n  "package_format": "manifest-v2",\n  "name": "%s",\n  "version": "%s",\n  "source": {"path": "%s", "sha256": "%s"},\n  "source_tree": {"files": %s, "sha256": "%s"},\n  "compiler": {"seed": "holyfitra-bootstrap", "sha256": "%s", "target": "%s", "self_hosting": "stage0_with_states_1_to_9_validation"},\n  "python_required": false,\n  "fixed_point_self_hosting": false,\n  "android_execution": false\n}\n' "$package_name" "$version" "$source_rel" "$source_hash" "$source_count" "$source_tree_hash" "$seed_hash" "$target" >"$manifest"
}

presets() {
  printf '%s\n' '{"schema":"holyfitra.v1.presets","presets":[{"name":"basic","entry":"src/main.hf","purpose":"minimal native Stage-0 project"},{"name":"selfhost-core","entry":"src/main.hf","purpose":"bounded compiler-core workspace with documented Stage-0 module boundaries"}],"python_required":false,"fixed_point_self_hosting":false}'
}

init_project() {
  local destination="${1:-}"
  shift || true
  local template="basic" project_name=""
  [[ -n "$destination" ]] || { echo 'holyfitra-v1: init requires DIRECTORY' >&2; exit 2; }
  while (($#)); do
    case "$1" in
      --template) (($# >= 2)) || { echo 'holyfitra-v1: --template requires a value' >&2; exit 2; }; template="$2"; shift 2 ;;
      --template=*) template="${1#--template=}"; shift ;;
      --name) (($# >= 2)) || { echo 'holyfitra-v1: --name requires a value' >&2; exit 2; }; project_name="$2"; shift 2 ;;
      --name=*) project_name="${1#--name=}"; shift ;;
      *) echo "holyfitra-v1: unknown init option: $1" >&2; exit 2 ;;
    esac
  done
  [[ "$template" == "basic" || "$template" == "selfhost-core" ]] || { echo "holyfitra-v1: unknown preset: $template" >&2; exit 2; }
  [[ ! -e "$destination" ]] || { echo "holyfitra-v1: destination already exists: $destination" >&2; exit 1; }
  project_name="${project_name:-$(basename -- "$destination")}"
  [[ "$project_name" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || { echo 'holyfitra-v1: project name must be a Holy Fitra identifier' >&2; exit 2; }
  mkdir -p "$destination"
  cp -R "$ROOT/bootstrap/presets/$template/." "$destination/"
  while IFS= read -r -d '' file; do
    sed "s/@PROJECT_NAME@/$project_name/g" "$file" >"$file.tmp"
    mv "$file.tmp" "$file"
  done < <(find "$destination" -type f -print0)
  printf '{"ok":true,"command":"init","project":"%s","preset":"%s","entry":"%s/src/main.hf","python_required":false}\n' "$destination" "$template" "$destination"
}

verify_llvm() {
  local llvm_path="$1" object_path
  need_command "$CC"
  object_path="$(mktemp "${TMPDIR:-/tmp}/holyfitra-v1-verify.XXXXXX.o")"
  trap 'rm -f "$object_path"' RETURN
  if is_native_target "$TARGET"; then "$CC" -x ir -c "$llvm_path" -o "$object_path"; else "$CC" -x ir -target "$TARGET" -c "$llvm_path" -o "$object_path"; fi
  rm -f "$object_path"
  trap - RETURN
}

emit_file() {
  parse_common_options "$@"
  resolve_input_source "$INPUT"
  [[ -n "$OUTPUT" ]] || { echo 'holyfitra-v1: emit requires -o OUTPUT.ll' >&2; exit 2; }
  ensure_seed
  mkdir -p "$(dirname -- "$OUTPUT")"
  local temporary
  temporary="$(mktemp "${TMPDIR:-/tmp}/holyfitra-v1-emit.XXXXXX.ll")"
  trap 'rm -f "$temporary"' RETURN
  "$SEED" --target="$TARGET" "$SOURCE_PATH" -o "$temporary"
  verify_llvm "$temporary"
  cp "$temporary" "$OUTPUT"
  rm -f "$temporary"
  trap - RETURN
  printf '{"ok":true,"command":"emit","output":"%s","target":"%s"}\n' "$OUTPUT" "$TARGET"
}

build_file() {
  parse_common_options "$@"
  resolve_input_source "$INPUT"
  [[ -n "$OUTPUT" ]] || { echo 'holyfitra-v1: build requires -o OUTPUT' >&2; exit 2; }
  ensure_seed
  need_command "$CC"
  mkdir -p "$(dirname -- "$OUTPUT")"
  local temporary
  temporary="$(mktemp "${TMPDIR:-/tmp}/holyfitra-v1-build.XXXXXX.ll")"
  trap 'rm -f "$temporary"' RETURN
  "$SEED" --target="$TARGET" "$SOURCE_PATH" -o "$temporary"
  verify_llvm "$temporary"
  local link_flags=(-O2 -Wl,--build-id=sha1 -Wl,--strip-all)
  if is_native_target "$TARGET"; then "$CC" "${link_flags[@]}" "$temporary" -o "$OUTPUT"; else "$CC" -target "$TARGET" "${link_flags[@]}" "$temporary" -o "$OUTPUT"; fi
  chmod 755 "$OUTPUT"
  rm -f "$temporary"
  trap - RETURN
  printf '{"ok":true,"command":"build","output":"%s","target":"%s"}\n' "$OUTPUT" "$TARGET"
}

check_file() {
  parse_common_options "$@"
  resolve_input_source "$INPUT"
  ensure_seed
  local temporary
  temporary="$(mktemp "${TMPDIR:-/tmp}/holyfitra-v1-check.XXXXXX.ll")"
  trap 'rm -f "$temporary"' RETURN
  "$SEED" --target="$TARGET" "$SOURCE_PATH" -o "$temporary" >/dev/null
  verify_llvm "$temporary"
  rm -f "$temporary"
  trap - RETURN
  printf '{"ok":true,"command":"check","input":"%s","target":"%s"}\n' "$SOURCE_PATH" "$TARGET"
}

run_file() {
  parse_common_options "$@"
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
  [[ -d "$root/tests" ]] && tests_dir="$root/tests"
  [[ -d "$tests_dir" ]] || { echo "holyfitra-v1: test directory does not exist: $tests_dir" >&2; exit 1; }
  local found=0 passed=0 failed=0
  while IFS= read -r -d '' source; do
    found=$((found + 1))
    local executable
    executable="$(mktemp "${TMPDIR:-/tmp}/holyfitra-v1-test.XXXXXX")"
    if build_file "$source" -o "$executable" >/dev/null 2>&1 && timeout --preserve-status "$RUN_TIMEOUT" "$executable" >/dev/null 2>&1; then
      passed=$((passed + 1)); printf 'PASS %s\n' "$source"
    else
      failed=$((failed + 1)); printf 'FAIL %s\n' "$source" >&2
    fi
    rm -f "$executable"
  done < <(find "$tests_dir" -type f -name '*.hf' -print0 | sort -z)
  [[ "$found" -gt 0 ]] || { echo 'holyfitra-v1: no .hf tests found' >&2; return 1; }
  printf '{"ok":%s,"command":"test","found":%d,"passed":%d,"failed":%d}\n' "$([[ "$failed" -eq 0 ]] && echo true || echo false)" "$found" "$passed" "$failed"
  [[ "$failed" -eq 0 ]]
}

package_file() {
  parse_common_options "$@"
  resolve_input_source "$INPUT"
  [[ -n "$OUTPUT" ]] || { echo 'holyfitra-v1: package requires -o OUTPUT.json' >&2; exit 2; }
  ensure_seed
  need_command sha256sum
  mkdir -p "$(dirname -- "$OUTPUT")"
  write_package_manifest "$OUTPUT" "$VERSION" "$TARGET" "$PROJECT_ROOT" "$SOURCE_PATH" "$SOURCE_REL"
  printf '{"ok":true,"command":"package","manifest":"%s","manifest_sha256":"%s"}\n' "$OUTPUT" "$(sha256sum -- "$OUTPUT" | awk '{print $1}')"
}

bundle_file() {
  parse_common_options "$@"
  resolve_input_source "$INPUT"
  [[ -n "$OUTPUT" ]] || { echo 'holyfitra-v1: bundle requires -o OUTPUT.tar.gz' >&2; exit 2; }
  [[ "$OUTPUT" == *.tar.gz ]] || { echo 'holyfitra-v1: bundle output must end in .tar.gz' >&2; exit 2; }
  ensure_seed
  need_command sha256sum
  need_command tar
  local temporary stage stage_name bundle_hash
  temporary="$(mktemp -d "${TMPDIR:-/tmp}/holyfitra-v1-bundle.XXXXXX")"
  trap 'rm -rf "$temporary"' RETURN
  stage_name="holyfitra-v1-$(basename -- "$SOURCE_PATH" .hf)-$VERSION"
  stage="$temporary/$stage_name"
  mkdir -p "$stage/toolchain/bootstrap" "$stage/project"
  cp "$ROOT/holyfitra-v1.sh" "$ROOT/holyfitra_bootstrap.cpp" "$stage/toolchain/"
  cp "$ROOT/bootstrap/holyfitra_runtime.c" "$ROOT/bootstrap/README.md" "$stage/toolchain/bootstrap/"
  cp -R "$ROOT/bootstrap/presets" "$stage/toolchain/bootstrap/"
  while IFS= read -r source; do
    [[ -n "$source" ]] || continue
    mkdir -p "$stage/project/$(dirname -- "$source")"
    cp "$PROJECT_ROOT/$source" "$stage/project/$source"
  done < <(source_paths "$PROJECT_ROOT")
  write_package_manifest "$stage/PACKAGE.json" "$VERSION" "$TARGET" "$PROJECT_ROOT" "$SOURCE_PATH" "$SOURCE_REL"
  cat >"$stage/BUILD.md" <<'EOF'
# Holy Fitra v1 portable source bundle

This bundle contains a bounded Holy Fitra source tree plus the dependency-free Stage-0 seed toolchain. Start inside `toolchain/` and run `./holyfitra-v1.sh check ../project` or `./holyfitra-v1.sh build ../project -o ../project/build/app`.

The package is source-portable and Python-free for its Stage-0 compiler path. It does **not** contain a fixed-point Stage-1 compiler, an Android NDK, an APK, or proof of execution on a physical Android device.
EOF
  mkdir -p "$(dirname -- "$OUTPUT")"
  tar --sort=name --mtime='@0' --owner=0 --group=0 --numeric-owner -C "$temporary" -czf "$OUTPUT" "$stage_name"
  bundle_hash="$(sha256sum -- "$OUTPUT" | awk '{print $1}')"
  rm -rf "$temporary"
  trap - RETURN
  printf '{"ok":true,"command":"bundle","bundle":"%s","sha256":"%s","python_required":false,"fixed_point_self_hosting":false}\n' "$OUTPUT" "$bundle_hash"
}

doctor() {
  local clang_status=missing clangpp_status=missing timeout_status=missing sha_status=missing tar_status=missing
  command -v "$CC" >/dev/null 2>&1 && clang_status=available || true
  command -v "$CXX" >/dev/null 2>&1 && clangpp_status=available || true
  command -v timeout >/dev/null 2>&1 && timeout_status=available || true
  command -v sha256sum >/dev/null 2>&1 && sha_status=available || true
  command -v tar >/dev/null 2>&1 && tar_status=available || true
  printf '{"v1":true,"termux":%s,"architecture":"%s","native_target":"%s","seed_optimization":"%s","python_required":false,"fixed_point_self_hosting":false,"project_presets":["basic","selfhost-core"],"clang":"%s","clang++":"%s","timeout":"%s","sha256sum":"%s","tar":"%s","android_execution":"not_available_without_sdk_ndk_device"}\n' "$([[ "${PREFIX:-}" == *com.termux/files/usr ]] && echo true || echo false)" "$(uname -m)" "$TARGET" "$SEED_OPT" "$clang_status" "$clangpp_status" "$timeout_status" "$sha_status" "$tar_status"
}

command_name="${1:-}"
shift || true
case "$command_name" in
  doctor) doctor ;;
  presets) (($# == 0)) || { usage >&2; exit 2; }; presets ;;
  init) init_project "$@" ;;
  version|--version) ensure_seed; "$SEED" --version ;;
  build-seed) (($# == 0)) || { usage >&2; exit 2; }; build_seed; printf '{"ok":true,"command":"build-seed","seed":"%s"}\n' "$SEED" ;;
  check) check_file "$@" ;;
  emit) emit_file "$@" ;;
  build) build_file "$@" ;;
  run) run_file "$@" ;;
  test) (($# == 1)) || { echo 'usage: holyfitra-v1.sh test PROJECT_OR_TESTS_DIR' >&2; exit 2; }; test_project "$1" ;;
  package) package_file "$@" ;;
  bundle) bundle_file "$@" ;;
  -h|--help|help) usage ;;
  *) usage >&2; exit 2 ;;
esac
