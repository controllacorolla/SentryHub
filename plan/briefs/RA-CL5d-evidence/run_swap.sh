#!/bin/bash
# RA-CL5d: every N-k attack phase. Usage (this dir): bash run_swap.sh /path/to/python
PY=${1:-python3}; export QT_QPA_PLATFORM=minimal; O=poc_d_swap.out; rm -f $O
r() { echo "=== $*" >> $O; timeout 200 $PY poc_d_swap.py "$@" 2>&1 | grep -v propagateSize >> $O; echo "--- rc=${PIPESTATUS[0]}" >> $O; }
for a in 0 0.05 0.2 0.6 1.0 2.0; do r revoke_at $a; done
for a in 0 0.2 1.0; do r forced_at $a; done
for a in 0 0.05 0.2 0.6 1.0 2.0 4.0; do r panic_at $a; done
r revoke_free; r revoke_new; r panic_new
for a in 0 0.2 1.0; do r chain_revoke $a; r chain_panic $a; done
for a in 0 0.2 1.0; do r babel_chain_revoke $a; r babel_chain_panic $a; done
for a in 0 0.2 1.0 2.0; do r babel_revoke_at $a; done
for a in 0 0.2; do r babel_forced_at $a; done
r babel_rerun; r other_page
for a in 0 0.2 1.0; do r panic_atlas $a; done
echo ALLDONE >> $O
