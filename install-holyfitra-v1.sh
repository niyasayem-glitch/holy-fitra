#!/usr/bin/env bash
set -euo pipefail

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
PREFIX="${PREFIX:-${HOME:-}/.local}"
DEST="$PREFIX/libexec/holyfitra-v1"
BIN="$PREFIX/bin"

if [[ -z "${HOME:-}" && -z "${PREFIX:-}" ]]; then
  echo 'install-holyfitra-v1: HOME or PREFIX must be set' >&2
  exit 2
fi
command -v clang++ >/dev/null 2>&1 || { echo 'install-holyfitra-v1: clang++ is required' >&2; exit 127; }
mkdir -p "$DEST" "$BIN"
cp "$ROOT/holyfitra-v1.sh" "$DEST/holyfitra-v1.sh"
cp "$ROOT/holyfitra_bootstrap.cpp" "$DEST/holyfitra_bootstrap.cpp"
chmod 755 "$DEST/holyfitra-v1.sh"
HOLYFITRA_V1_BUILD_DIR="$DEST/.holyfitra/v1" "$DEST/holyfitra-v1.sh" build-seed >/dev/null
printf '#!/usr/bin/env bash\nexec %q "$@"\n' "$DEST/holyfitra-v1.sh" >"$BIN/holyfitra-v1"
chmod 755 "$BIN/holyfitra-v1"
printf '%s\n' "installed $BIN/holyfitra-v1"
