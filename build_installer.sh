#!/usr/bin/env bash
# Assemble the single-file installer: install_head.sh + base64(tar.gz of app files) + install_tail.sh.
# Payload = every *.py, the fonts/ dir, harden.sh, and the test suite.
set -euo pipefail
cd "$(dirname "$0")"

OUT="${1:-install-uconsole-suite.sh}"
TARBALL="$(mktemp --suffix=.tgz)"
trap 'rm -f "$TARBALL"' EXIT

# Deterministic, reproducible tar (sorted, no mtondata noise)
FILES=(*.py harden.sh install_radiosonde.sh run_tests.sh fonts tests)
tar czf "$TARBALL" --sort=name --owner=0 --group=0 --numeric-owner \
    --exclude='__pycache__' --exclude='*.pyc' "${FILES[@]}"

{
  cat install_head.sh
  base64 "$TARBALL"
  cat install_tail.sh
} > "$OUT"

PY=$(ls -1 *.py | wc -l)
BYTES=$(wc -c < "$OUT")
echo "built $OUT  (${PY} python modules + harden.sh + fonts, ${BYTES} bytes)"
echo "sanity: head/tail markers"
grep -c "B64EOF" "$OUT" | sed 's/^/  B64EOF count: /'
bash -n "$OUT" && echo "  bash -n: OK"
