#!/usr/bin/env bash
set -euo pipefail

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
OUTPUT="${1:-$ROOT/dist/holyfitra-v1.0.0-host.tar.gz}"
EXTRACT="$(mktemp -d "${TMPDIR:-/tmp}/holyfitra-release-verify.XXXXXX")"
trap 'rm -rf "$EXTRACT"' EXIT

mkdir -p "$(dirname -- "$OUTPUT")"
rm -f "$OUTPUT"

bash "$ROOT/make-holyfitra-v1-release.sh" "$OUTPUT"
test -s "$OUTPUT"

ARCHIVE_SHA256="$(sha256sum "$OUTPUT" | awk '{print $1}')"
LISTING="$EXTRACT/listing.txt"
tar -tzf "$OUTPUT" >"$LISTING"

grep -Fxq 'holyfitra-v1/' "$LISTING"
ROOT_ENTRY_COUNT="$(grep -c '^holyfitra-v1/' "$LISTING")"
test "$ROOT_ENTRY_COUNT" -gt 0

# Reject absolute paths, parent traversal, and unexpected top-level entries.
if grep -Eq '(^/|(^|/)\.\./|^[^h]|^holyfitra-v1/\.\./)' "$LISTING"; then
    echo 'release verifier: unsafe archive path detected' >&2
    exit 1
fi

rm -rf "$EXTRACT/tree"
mkdir -p "$EXTRACT/tree"
tar -xzf "$OUTPUT" -C "$EXTRACT/tree"
PACKAGE="$EXTRACT/tree/holyfitra-v1"

test -d "$PACKAGE"
for required in \
    RELEASE_METADATA.txt \
    holyfitra-v1.sh \
    termux-build.sh \
    holyfitra_bootstrap.cpp \
    bootstrap/hello.hf \
    bootstrap/holyfitra_runtime.c \
    docs/README.md \
    docs/HOLY_FITRA_V1_RELEASE_SPEC.md \
    tools/measure_million_line.py \
    tools/stress_million_line.py; do
    test -f "$PACKAGE/$required" || {
        echo "release verifier: missing required file: $required" >&2
        exit 1
    }
done

test -x "$PACKAGE/holyfitra-v1.sh"
test -x "$PACKAGE/termux-build.sh"
grep -Fxq 'version=1.0.0-host' "$PACKAGE/RELEASE_METADATA.txt"
grep -Fxq 'python_required=false' "$PACKAGE/RELEASE_METADATA.txt"
grep -Fxq 'android_execution=false' "$PACKAGE/RELEASE_METADATA.txt"
grep -Fxq 'aarch64_status=artifact-only' "$PACKAGE/RELEASE_METADATA.txt"

if find "$PACKAGE" -type f \( \
    -name '*.pyc' -o -name '*.pyo' -o -name '*.o' -o -name '*.a' -o -name '*.so' \
    -o -name '*.apk' -o -name '*.aar' -o -name '.git*' \
\) -print -quit | grep -q .; then
    echo 'release verifier: generated or repository metadata artifact found' >&2
    exit 1
fi

printf '%s  %s\n' "$ARCHIVE_SHA256" "$(basename -- "$OUTPUT")" >"$OUTPUT.sha256"
(
    cd "$(dirname -- "$OUTPUT")"
    sha256sum -c "$(basename -- "$OUTPUT").sha256"
)
{
    echo "### Release package verification"
    echo "Archive: $(basename -- "$OUTPUT")"
    echo "SHA-256: $ARCHIVE_SHA256"
    echo "Entries: $ROOT_ENTRY_COUNT"
    echo 'Metadata: host/Termux package; Android execution false; AArch64 artifact-only.'
} >>"${GITHUB_STEP_SUMMARY:-/dev/null}"

echo "release_package_verified=true"
echo "release_archive=$OUTPUT"
echo "release_sha256=$ARCHIVE_SHA256"
echo "release_entries=$ROOT_ENTRY_COUNT"
