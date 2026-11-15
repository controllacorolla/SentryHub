#!/bin/sh
# usage: watch.sh <target-count> <runner-pattern>
F=/private/tmp/claude-501/-Users-daltonhayes-SentryHub/f893c360-320b-4c7c-9dc4-e3ab8ef11055/scratchpad/reaudit/test-teeth/results/summary.jsonl
last=0
while true; do
  n=0
  [ -f "$F" ] && n=$(wc -l < "$F" | tr -d ' ')
  if [ $((n/20)) -gt $((last/20)) ] || [ "$n" -ge "$1" ]; then echo "mutations done: $n"; last=$n; fi
  [ "$n" -ge "$1" ] && break
  pgrep -f "$2" >/dev/null || { echo "runner exited at $n"; break; }
  sleep 15
done
