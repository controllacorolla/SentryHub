#!/usr/bin/env bash
# Assemble the single-file installer: install_head.sh + base64(tar.gz of app files) + install_tail.sh.
# Payload = every *.py, the fonts/ dir, harden.sh, and the test suite.
set -euo pipefail
cd "$(dirname "$0")"

OUT="${1:-install-uconsole-suite.sh}"
TARBALL="$(mktemp)"          # no --suffix: BSD mktemp (macOS) lacks it, and the name is internal
trap 'rm -f "$TARBALL"' EXIT

FILES=(*.py harden.sh install_radiosonde.sh run_tests.sh fonts tests)
# Prefer GNU tar for a deterministic, sorted archive; fall back to the platform tar (bsdtar on
# macOS) so the documented macOS dev build still works - just not byte-reproducible there.
if tar --version 2>/dev/null | grep -qi 'gnu tar'; then
    GNUTAR=tar
elif command -v gtar >/dev/null 2>&1; then
    GNUTAR=gtar
else
    GNUTAR=
fi
if [ -n "$GNUTAR" ]; then
    "$GNUTAR" czf "$TARBALL" --sort=name --owner=0 --group=0 --numeric-owner \
        --exclude='__pycache__' --exclude='*.pyc' "${FILES[@]}"
else
    # bsdtar: no --sort/--owner; COPYFILE_DISABLE stops macOS adding ._ AppleDouble entries
    COPYFILE_DISABLE=1 tar czf "$TARBALL" \
        --exclude='__pycache__' --exclude='*.pyc' "${FILES[@]}"
fi

{
  cat install_head.sh
  base64 < "$TARBALL"        # stdin, not a positional arg: BSD base64 (macOS) rejects the latter
  cat install_tail.sh
} > "$OUT"

PY=$(ls -1 *.py | wc -l)
BYTES=$(wc -c < "$OUT")
echo "built $OUT  (${PY} python modules + harden.sh + fonts, ${BYTES} bytes)"
echo "sanity: head/tail markers"
grep -c "B64EOF" "$OUT" | sed 's/^/  B64EOF count: /'
bash -n "$OUT" && echo "  bash -n: OK"
