#!/bin/bash
# RA-CL5d NWR attacks. Usage (this dir): bash run_nwr.sh /path/to/python
PY=${1:-python3}; export QT_QPA_PLATFORM=minimal; O=poc_d_nwr.out; rm -f $O
for w in "chatter 25" "stderr_trickle 25" "trickle 25" "stuck_mm 25" "sigstop 25" "stopcont 25" "dies1 40" "dies3 40" "dies5 40" "bursty15 25" "bursty08 25" "io_unreadable 20" "wedged 20" "wedge_mid 20" "realistic60 60" "realistic_load 60" "revoke 8" "forced 8" "panic 8" "hide 8" "retune 10" "to_fm 8" "from_fm 12" "from_scan 12"; do
  echo "=== $w" >> $O; timeout 200 $PY poc_d_nwr.py $w 2>&1 | grep -v propagateSize >> $O; echo "--- rc=${PIPESTATUS[0]}" >> $O
done
echo ALLDONE >> $O
