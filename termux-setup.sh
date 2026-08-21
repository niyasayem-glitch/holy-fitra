#!/usr/bin/env bash
set -euo pipefail

DRY_RUN=0
if [[ "${1:-}" == "--dry-run" ]]; then
  DRY_RUN=1
fi

if ! command -v pkg >/dev/null 2>&1; then
  echo "This script is intended for Termux. Install it from https://termux.dev before continuing." >&2
  exit 1
fi

packages=(python clang llvm cmake make git pkg-config)
if pkg list-all 2>/dev/null | grep -q '^python-numpy/'; then
  packages+=(python-numpy)
fi

run() {
  if (( DRY_RUN )); then
    printf '+ %q' "$@"
    printf '\n'
  else
    "$@"
  fi
}

run pkg update -y
run pkg install -y "${packages[@]}"

if (( ! DRY_RUN )); then
  python -m pip install --upgrade pip setuptools wheel --no-warn-script-location
  python -m pip install -e . --no-build-isolation --no-warn-script-location
  mkdir -p "$HOME/.local/bin"
  cat > "$HOME/.local/bin/holyfitra-env" <<'EOF'
export PATH="$HOME/.local/bin:$PATH"
export HOLYFITRA_ROOT="${HOLYFITRA_ROOT:-$PWD}"
EOF
  chmod 700 "$HOME/.local/bin/holyfitra-env"
fi

echo "Holy Fitra Termux setup complete. Run: holyfitra --help"
