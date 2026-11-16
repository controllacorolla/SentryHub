#!/bin/bash
# RA-CL5d: re-run every RA-CL5 and RA-CL5b PoC against the branch tip. Python 3.12 venv.
# Usage (repo root): bash plan/briefs/RA-CL5d-evidence/rerun_all.sh /path/to/venv/bin/python
PY=${1:-python3}
B=plan/briefs
O=$B/RA-CL5d-evidence/rerun
export QT_QPA_PLATFORM=minimal
run() { # out-name dir script args...
  local out=$1 dir=$2 s=$3; shift 3
  echo "=== $*" >> $O/$out.out
  (cd $B/$dir && timeout 300 $PY $s "$@") >> $O/$out.out 2>&1
  echo "--- rc=$?" >> $O/$out.out
}
rm -f $O/*.out
for w in babel sstv scan fm nwr prism atlas; do run poc_revoke RA-CL5-evidence poc_revoke.py $w; done
for i in 1 2 3; do run poc_release_order RA-CL5-evidence poc_release_order.py; done
for w in babel nwr; do run poc_panic RA-CL5-evidence poc_panic.py $w; done
run poc_acquiring RA-CL5-evidence poc_acquiring.py
run poc_gui_block RA-CL5-evidence poc_gui_block.py
run poc_arbiter RA-CL5-evidence poc_arbiter.py
run poc_alert_drop RA-CL5-evidence poc_alert_drop.py
run poc_eventbus RA-CL5-evidence poc_eventbus.py
run poc_pipeline RA-CL5-evidence poc_pipeline.py
run poc_workers RA-CL5-evidence poc_workers.py
run poc_hub_close RA-CL5-evidence poc_hub_close.py
for w in r1 r2; do run poc_babel RA-CL5-evidence poc_babel.py $w; done
run poc_e3_bleak RA-CL5-evidence poc_e3_bleak.py
run poc_b2_retune RA-CL5b-evidence poc_b2_retune.py
run poc_atlas_hidden_revoke RA-CL5b-evidence poc_atlas_hidden_revoke.py
run poc_gui_block_modeswitch RA-CL5b-evidence poc_gui_block_modeswitch.py
for w in revoke forced panic hide submode hung stall decoder_dies stall_revoke; do run poc_nwr_safety RA-CL5b-evidence poc_nwr_safety.py $w; done
for w in babel_ais babel_pocsag sstv nwr fm scan prism atlas_ais atlas_aprs; do run poc_panic_race RA-CL5b-evidence poc_panic_race.py $w 12; done
run poc_panic_race RA-CL5b-evidence poc_panic_race.py atlas_ais_hidden 8
run poc_sstv_stale_decode RA-CL5b-evidence poc_sstv_stale_decode.py
run poc_submode_drop RA-CL5b-evidence poc_submode_drop.py 3.5
run poc_submode_drop RA-CL5b-evidence poc_submode_drop.py 2.2 trap
run poc_submode_drop RA-CL5b-evidence poc_submode_drop.py 1.0 trap
run poc_tk_sstv_rotation RA-CL5b-evidence poc_tk_sstv_rotation.py

# RA-CL5c PoCs
for w in hidden_revoke hidden_forced hidden_panic hidden_acquiring hidden_cost; do run poc_c_atlas RA-CL5c-evidence poc_c_atlas.py $w; done
run poc_c_atlas_toggle_panic RA-CL5c-evidence poc_c_atlas.py toggle_panic
for w in "wedged 25" "wedge_mid 25" "chatter 25" "stuck_mm 20" "sigstop 20" "dies1 40" "dies3 40" "dies5 40" "io_unreadable 25" "revoke 8" "forced 8" "panic 8" "hide 8" "retune 8" "to_fm 8" "from_fm 12" "from_scan 12"; do run poc_c_nwr RA-CL5c-evidence poc_c_nwr.py $w; done
run poc_c_sstv_drop RA-CL5c-evidence poc_c_sstv_drop.py
for w in revoke babel_revoke panic babel_panic same_name babel_same; do run poc_c_swap RA-CL5c-evidence poc_c_swap.py $w; done
for w in gui_block close never; do run poc_c_swap2 RA-CL5c-evidence poc_c_swap.py $w; done
echo ALLDONE >> $O/_done
