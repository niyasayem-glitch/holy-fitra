#!/usr/bin/env bash
set -euo pipefail

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
DRY_RUN=0

usage() {
  cat <<'EOF'
usage: bash termux-setup.sh [--dry-run]

Installs the no-sudo Termux toolchain and the Holy Fitra CLI for the current
user. The script is intended for a Termux session on Android; it does not
install the Android SDK/NDK and does not build APKs.
EOF
}

for argument in "$@"; do
  case "$argument" in
    --dry-run) DRY_RUN=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "termux-setup: unknown option: $argument" >&2; usage >&2; exit 2 ;;
  esac
done

if ! command -v pkg >/dev/null 2>&1; then
  echo 'termux-setup: this script must run inside Termux.' >&2
  echo 'termux-setup: install Termux from https://termux.dev and retry.' >&2
  exit 1
fi

machine="$(uname -m)"
if [[ "$machine" != "aarch64" && "$machine" != "arm64" ]]; then
  echo "termux-setup: warning: detected architecture $machine; Android ARM64 is expected for device-native execution." >&2
fi

packages=(python clang llvm coreutils findutils diffutils cmake make git pkg-config tar gzip)
if pkg list-all 2>/dev/null | grep -q '^python-numpy/'; then
  packages+=(python-numpy)
fi

run() {
  if (( DRY_RUN )); then
    printf '+'
    printf ' %q' "$@"
    printf '\n'
  else
    "$@"
  fi
}

run pkg update -y
run pkg install -y "${packages[@]}"

if (( ! DRY_RUN )); then
  PYTHON="$(command -v python3 || command -v python)"
  "$PYTHON" -m pip install -e "$ROOT" --no-deps --no-build-isolation --no-warn-script-location

  mkdir -p "$HOME/.local/bin"
  cat > "$HOME/.local/bin/holyfitra-env" <<EOF
# Holy Fitra Termux environment. Source this file from any directory.
export PATH="\$HOME/.local/bin:\$PATH"
export HOLYFITRA_ROOT="$ROOT"
EOF
  chmod 644 "$HOME/.local/bin/holyfitra-env"

  # Prefer the installed console script when packaging succeeds, but retain a
  # repository-independent launcher for environments where pip entry points
  # are not placed on PATH.
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
fi

if (( DRY_RUN )); then
  echo 'Holy Fitra Termux setup dry run complete. No packages or files were changed.'
else
  echo 'Holy Fitra Termux setup complete.'
  echo 'Source the environment with: source "$HOME/.local/bin/holyfitra-env"'
  echo 'Then run: holyfitra doctor'
fi
