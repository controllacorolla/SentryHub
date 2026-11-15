cd "$(dirname "$0")"
run() { # name, -k expr
  cp -R base2/palisade_qt base2/.pq_orig
  sed 's/base2/base2/' /dev/null
  ../../venv312/bin/python - "$1" <<'PY'
import sys, os
src = open("mutate2.py").read().split("only = sys.argv")[0]
ns = {"__file__": os.path.abspath("mutate2.py")}; exec(src, ns)
path, old, new = ns["M"][sys.argv[1]]; fp = os.path.join(ns["BASE"], path); s = open(fp).read()
assert s.count(old) == 1; open(fp, "w").write(s.replace(old, new))
PY
  (cd base2 && QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 ../../../venv312/bin/python -m pytest -q -p no:cacheprovider tests/test_cl1_screen.py -k "$2" 2>&1 | grep -E "^FAILED|passed|failed" | cut -c1-200 | sed "s/^/[$1] /")
  rm -rf base2/palisade_qt && mv base2/.pq_orig base2/palisade_qt
}
run CTRL_no_slash "key_map_and_command_palette"
run CTRL_no_panic_key "panic"
run CTRL_no_a_key "alerts_persist"
