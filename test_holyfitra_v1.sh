#!/usr/bin/env bash
set -euo pipefail

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
DRIVER="$ROOT/holyfitra-v1.sh"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/holyfitra-v1-test.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT

cat >"$WORK/good.hf" <<'EOF'
module v1_good

fn add(a: i32, b: i32) -> i32 {
    return a + b
}

fn main() -> i32 {
    return add(20, 22)
}
EOF

cat >"$WORK/test_zero.hf" <<'EOF'
module v1_test

fn main() -> i32 {
    return 0
}
EOF

cat >"$WORK/bad.hf" <<'EOF'
module v1_bad
this construct is not part of the v1 grammar
EOF

cat >"$WORK/deep.hf" <<'EOF'
module v1_deep
fn main() -> i32 {
    return
EOF
for _ in $(seq 1 513); do printf '(' >>"$WORK/deep.hf"; done
printf '1' >>"$WORK/deep.hf"
for _ in $(seq 1 513); do printf ')' >>"$WORK/deep.hf"; done
printf '\n}\n' >>"$WORK/deep.hf"
cat >"$WORK/huge_array.hf" <<'EOF'
module v1_huge_array
fn main(a: [999999999]i32) -> i32 {
    return 0
}
EOF
printf 'module v1_huge_string\nfn main() -> i32 { return "' >"$WORK/huge_string.hf"
head -c 1048577 /dev/zero | tr '\0' 'x' >>"$WORK/huge_string.hf"
printf '" }\n' >>"$WORK/huge_string.hf"
truncate -s 8388609 "$WORK/oversized.hf"

export HOLYFITRA_V1_BUILD_DIR="$WORK/build"
"$DRIVER" build-seed >/dev/null
"$DRIVER" check "$WORK/good.hf" >/dev/null
"$DRIVER" emit "$WORK/good.hf" -o "$WORK/one.ll" >/dev/null
"$DRIVER" emit "$WORK/good.hf" -o "$WORK/two.ll" >/dev/null
cmp "$WORK/one.ll" "$WORK/two.ll"
"$DRIVER" build "$WORK/good.hf" -o "$WORK/good" >/dev/null
set +e
"$WORK/good" >/dev/null
status=$?
set -e
test "$status" -eq 42
if "$DRIVER" check "$WORK/bad.hf" >/dev/null 2>&1; then
    echo 'malformed source unexpectedly accepted' >&2
    exit 1
fi
if "$DRIVER" check "$WORK/deep.hf" >/dev/null 2>&1; then
    echo 'deep source unexpectedly accepted' >&2
    exit 1
fi
if "$DRIVER" check "$WORK/oversized.hf" >/dev/null 2>&1; then
    echo 'oversized source unexpectedly accepted' >&2
    exit 1
fi
if "$DRIVER" check "$WORK/huge_array.hf" >/dev/null 2>&1; then
    echo 'huge array unexpectedly accepted' >&2
    exit 1
fi
if "$DRIVER" check "$WORK/huge_string.hf" >/dev/null 2>&1; then
    echo 'huge string unexpectedly accepted' >&2
    exit 1
fi
mkdir -p "$WORK/project/tests"
cp "$WORK/test_zero.hf" "$WORK/project/tests/smoke.hf"
"$DRIVER" test "$WORK/project" >/dev/null
"$DRIVER" package "$WORK/good.hf" -o "$WORK/good.json" >/dev/null
grep -q '"python_required": false' "$WORK/good.json"
grep -q '"android_execution": false' "$WORK/good.json"
printf '%s\n' 'holyfitra_v1_driver=passed'
