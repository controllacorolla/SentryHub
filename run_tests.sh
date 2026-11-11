#!/usr/bin/env bash
# Run the suite's regression tests. Prefers a Python that has tkinter+PIL so the
# Tk/PIL-dependent paths (e.g. the dark-tile transform) run for real instead of skipping.
# On the uConsole, python3 has both, so: ./run_tests.sh
set -e
cd "$(dirname "$0")"

PY=python3
if ! $PY -c "import tkinter, PIL" 2>/dev/null; then
  if command -v python3.12 >/dev/null && python3.12 -c "import tkinter, PIL" 2>/dev/null; then
    PY=python3.12
  fi
fi
if ! $PY -c "import pytest" 2>/dev/null; then
  echo "pytest not found - installing for $PY…"
  $PY -m pip install --user --break-system-packages -q pytest || {
    echo "couldn't install pytest; install it and re-run"; exit 1; }
fi
echo "Running tests with: $($PY --version 2>&1)"
exec $PY -m pytest tests/ "$@"
