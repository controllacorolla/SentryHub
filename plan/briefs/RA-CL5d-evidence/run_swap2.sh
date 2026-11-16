#!/bin/bash
# RA-CL5d second pass (hooks on the GUI thread; revoke->None runs marked N/A). Usage: bash run_swap2.sh PY
PY=${1:-python3}; export QT_QPA_PLATFORM=minimal; O=poc_d_swap2.out; rm -f $O
r() { echo "=== $*" >> $O; timeout 200 $PY poc_d_swap.py "$@" 2>&1 | grep -v propagateSize >> $O; echo "--- rc=${PIPESTATUS[0]}" >> $O; }
r revoke_at 1.0; r revoke_at 2.0; r revoke_free; r revoke_new; r panic_new
for a in -1 0 0.2 1.0; do r chain_revoke $a; done; r chain_panic -1
r babel_chain_revoke -1; r babel_chain_panic -1; r babel_chain_revoke 1.0
for a in 0 0.2 1.0; do r panic_atlas $a; done
echo ALLDONE >> $O
