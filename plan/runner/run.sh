#!/bin/bash
# PALISADE brief runner — runs planner briefs headless, one lane at a time.
# Usage:  ~/palisade-run.sh A      (second terminal: ~/palisade-run.sh B)
# Reads origin/docs/briefs:plan/runner/QUEUE  (lines: "<lane> <ID> <model>"), runs each new ID
# for its lane as:  claude -p "git fetch origin docs/briefs && run <ID>"
# Env: PALISADE_REPO (default ~/SentryHub)  PALISADE_PERM (default auto)  PALISADE_POLL (secs, 60)
set -u
LANE="${1:-A}"
REPO="${PALISADE_REPO:-$HOME/SentryHub}"
PERM="${PALISADE_PERM:-auto}"
POLL="${PALISADE_POLL:-60}"
STATE="$HOME/.palisade-runner"
STW="$STATE/status-wt"
mkdir -p "$STATE/logs"; touch "$STATE/done"
cd "$REPO" || { echo "no repo at $REPO"; exit 1; }

status() {   # append one line to runner-status.log on branch runner-status and push it
  local line="$(date '+%Y-%m-%d %H:%M:%S') [$LANE] $*"
  echo "$line" | tee -a "$STATE/runner.log"
  (
    if [ ! -d "$STW" ]; then
      git fetch -q origin runner-status 2>/dev/null
      if git rev-parse -q --verify origin/runner-status >/dev/null; then
        git worktree add -q "$STW" -B runner-status origin/runner-status
      else
        git worktree add -q "$STW" -B runner-status origin/docs/briefs
      fi
    fi
    cd "$STW" && git pull -q --rebase origin runner-status 2>/dev/null
    echo "$line" >> runner-status.log
    git add runner-status.log && git commit -q -m "runner: $*" >/dev/null 2>&1
    git push -q origin runner-status 2>/dev/null || { git pull -q --rebase origin runner-status; git push -q origin runner-status; }
  ) >/dev/null 2>&1
}

status "runner up (perm=$PERM, repo=$REPO)"
while true; do
  git fetch -q origin docs/briefs 2>/dev/null
  git show origin/docs/briefs:plan/runner/QUEUE 2>/dev/null | grep -v '^[[:space:]]*#' > "$STATE/queue.$LANE"
  while read -r lane id model _rest; do
    [ "$lane" = "$LANE" ] && [ -n "${id:-}" ] || continue
    grep -qx "$id" "$STATE/done" && continue
    mkdir "$STATE/lock-$id" 2>/dev/null || continue
    status "START $id (${model:-opus})"
    caffeinate -i claude -p "git fetch origin docs/briefs && run $id" \
      --model "${model:-opus}" --permission-mode "$PERM" \
      < /dev/null > "$STATE/logs/$id.log" 2>&1
    rc=$?
    echo "$id" >> "$STATE/done"
    rmdir "$STATE/lock-$id" 2>/dev/null
    status "END $id rc=$rc :: $(tail -c 300 "$STATE/logs/$id.log" | tr '\n' ' ')"
  done < "$STATE/queue.$LANE"
  sleep "$POLL"
done
