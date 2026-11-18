#!/bin/sh
# Mutation check: does any test in tests/test_radio_sdrpp.py fail when a fix line is removed?
# usage: mutate.sh <worktree> <scratch-dir>
WT=$1; S=$2
mut(){ rm -rf $S/mut; mkdir -p $S/mut; git -C $WT archive HEAD | tar -x -C $S/mut
  (cd $S/mut && python3 -c "
import sys;f,a,b=sys.argv[1:4];s=open(f).read();assert a in s,(f,a);open(f,'w').write(s.replace(a,b,1))" "$1" "$2" "$3" &&
   QT_QPA_PLATFORM=offscreen python3 -m pytest -q -p no:cacheprovider tests/test_radio_sdrpp.py --timeout=60 --timeout-method=thread 2>&1 | tail -1); }
echo "M1 B7 requeue removed from run()"; mut palisade_qt/iqworker.py "                    self._requeue(p)
" ""
echo "M2 B6 text-mode drain restored"; mut iqsource.py "stderr_last=subprocess.STDOUT, text=False, bufsize=0)" "stderr_last=subprocess.STDOUT)"
echo "M3 B2 back-off reset removed"; mut palisade_qt/iqworker.py "                    self._fault_n = 0
" ""
echo "M4 B3 PRISM finished-worker check removed"; mut palisade_qt/prism.py "                and not (w.isFinished() and not self.swapping()))" "                )"
