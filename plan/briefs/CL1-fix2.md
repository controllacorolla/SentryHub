# CL1-fix2 — close RA-CL1b (small, same branch)

**Branch:** `fix/cl1-screen-structure`, on top of `5cbc1de`. Same PR #19. Read
`plan/briefs/RA-CL1b-report.md` first. Token budget per `README.md`. Ignore the untracked
`p_*.py` / `run.sh` / `suite_tail.txt` from a duplicate audit session; delete them, don't commit.

## Owner decisions (2026-11-15)

1. **PANIC unchecks the BENCH conducted-ack checkbox** (pure UI; the ack is page state). The TX
   slot and banner then show what the gate says. Remove the "BENCH ack not revoked" banner path.
2. **D7 stands as recorded: the function label is visible beside every key.** Planner commit
   `1e0993c` moving it to tooltip only was wrong. Two-line key: callsign over function label,
   both ≥16 px, strip ≤40 px tall, all of it fits 1280 wide. Use short labels: home · map ·
   spectrum · listen · sweep · survey · hardware · settings. If it can't fit at 16 px, stop and
   report the measured widths; don't shrink type.
3. **ATLAS table fits without horizontal scroll at 1280×720.** Drop or merge the least useful
   column(s) to fit. No numeric value may ever be clipped: numbers that can't fit elide with "…"
   and show the full value in the detail card/tooltip.

## Fix (test fails first, then passes)

- **N1** per decision 3. Test: every visible cell's full text fits its column at 1280×720 on
  ATLAS, or ends in "…"; no horizontal scrollbar.
- **N2** `kit/feed.py`: restore selection by item id after refresh/re-sort; the detail card
  follows the selected item. Test: re-sort with a different order → same aircraft selected,
  detail matches.
- **N10** tests that fail if the SIGKILL fallback is removed and if the process-group kill is
  removed (use a real `sh -c` pipeline that traps SIGTERM).
- **N3** per decision 1, with a test.
- **D7** per decision 2, with a test that every nav key shows its function label as visible text.
- **Item 6 (from the second RA-CL1b report):** the RADIOS and ENGAGEMENT *panels* must show
  UNKNOWN when a read raises, like the slots do. Today RADIOS keeps "FREE" and ENGAGEMENT throws
  on open. Test both with a raising reader.
- **Ack all** must not clear alerts that arrived after the drawer was opened/last viewed. Test.
- Other RA-CL1b Mediums/Lows: fix if trivial, else list under "found, not fixed".

## Done means

Suite + pyflakes pasted, renders only for ATLAS and the top strip (dark + sun, live) plus one
stress pass, report appended to `CL1-report.md`, pushed, no PR. Stop: RA-CL1c (fresh chat,
scoped to these items) decides the merge.

Trailer: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` +
`Claude-Session: https://claude.ai/code/session_01DNwALPN1Ydsu8Kidx4CrT4`
