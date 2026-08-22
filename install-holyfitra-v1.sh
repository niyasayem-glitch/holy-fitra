#!/usr/bin/env bash
set -euo pipefail

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
TERMUX=0
if [[ "${PREFIX:-}" == *com.termux/files/usr ]]; then
  TERMUX=1
fi

# Termux reserves PREFIX for its package prefix. Use HOLYFITRA_PREFIX there so
# installation always remains user-owned and never requires sudo.
if (( TERMUX )); then
  INSTALL_PREFIX="${HOLYFITRA_PREFIX:-${HOME:+$HOME/.local}}"
else
  INSTALL_PREFIX="${HOLYFITRA_PREFIX:-${PREFIX:-${HOME:+$HOME/.local}}}"
fi
CXX="${HOLYFITRA_CXX:-${CXX:-clang++}}"

usage() {
  cat <<'EOF'
usage:
  ./install-holyfitra-v1.sh
  HOLYFITRA_PREFIX="$HOME/.local" ./install-holyfitra-v1.sh

Installs the native v1 compiler into a user-owned prefix. No sudo is used.
Termux users should use HOLYFITRA_PREFIX; PREFIX is reserved by Termux.
Set HOLYFITRA_CXX to select a C++ compiler explicitly.
EOF
}

case "${1:-}" in
  -h|--help) usage; exit 0 ;;
  "") ;;
  *) echo "install-holyfitra-v1: unexpected argument: $1" >&2; usage >&2; exit 2 ;;
esac

if [[ -z "$INSTALL_PREFIX" ]]; then
  echo 'install-holyfitra-v1: set HOME or HOLYFITRA_PREFIX to a writable user prefix' >&2
  exit 2
fi

if ! command -v "$CXX" >/dev/null 2>&1; then
  echo "install-holyfitra-v1: compiler not found: $CXX" >&2
  if (( TERMUX )); then
    echo 'install-holyfitra-v1: in Termux, run: pkg install clang' >&2
  fi
  exit 127
fi

DEST="$INSTALL_PREFIX/libexec/holyfitra-v1"
BIN="$INSTALL_PREFIX/bin"
mkdir -p "$DEST" "$BIN"
cp "$ROOT/holyfitra-v1.sh" "$DEST/holyfitra-v1.sh"
cp "$ROOT/holyfitra_bootstrap.cpp" "$DEST/holyfitra_bootstrap.cpp"
chmod 755 "$DEST/holyfitra-v1.sh"
HOLYFITRA_V1_BUILD_DIR="$DEST/.holyfitra/v1" HOLYFITRA_CXX="$CXX" "$DEST/holyfitra-v1.sh" build-seed >/dev/null

cat > "$BIN/holyfitra-v1" <<EOF
#!/usr/bin/env bash
exec "$DEST/holyfitra-v1.sh" "\$@"
EOF
chmod 755 "$BIN/holyfitra-v1"

printf '%s\n' "installed $BIN/holyfitra-v1"
if [[ ":${PATH:-}:" != *":$BIN:"* ]]; then
  printf '%s\n' "add it to PATH with: export PATH=\"$BIN:\$PATH\""
fi
