# CL1-fix3 — close RA-CL1c (tiny)

**Branch:** `fix/cl1-screen-structure` @ `ee4ac57`. Own worktree (`git worktree add ../wt-CL1-fix3
origin/fix/cl1-screen-structure`). Read `plan/briefs/RA-CL1c-report.md` (F1–F5). Token budget per
`README.md`. No subagents needed.

- **F1 (blocker):** focus must never paint over a glyph in any theme. Drop the 4 px left/right
  focus border on nav keys; show focus with an inset/underline or a fill + `bw` side border that
  stays outside the text rect. Strip width must not grow (SUN demo has 1 px spare). Test: for each
  key, focused vs unfocused glyph ink is identical inside the text rect, all three themes.
- **F2:** `scope_summary` caps at `999+ targets`; test the strip still fits 1280 at 1000 and
  100000 targets, every theme, live + demo.
- **F3:** test that a FeedTable refits when its viewport gains a v-scroll or narrows (mutation m16
  must be caught).
- **F4:** when the selected ATLAS contact disappears, the detail card shows it as **LOST** (or
  clears); never as current. Test.
- **F5:** skip unless it fits with zero width cost.

Done: suite + pyflakes pasted, renders of the strip (sun demo worst case with focus on each key)
and ATLAS, report appended to `CL1-report.md`, pushed, worktree removed, no PR.

Trailer: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` +
`Claude-Session: https://claude.ai/code/session_01DNwALPN1Ydsu8Kidx4CrT4`
