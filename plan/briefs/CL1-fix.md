# CL1-fix — close what RA-CL1 reopened

**Branch:** `fix/cl1-screen-structure` (same branch, same PR #19). Append to
`plan/briefs/CL1-report.md`; do not open a new PR.
**Source:** your own RA-CL1 verdict (DO NOT MERGE). Evidence and PoC scripts are in the
scratchpad `reaudit_result.json` + `reaudit/`. **First action: copy them into
`plan/briefs/CL1-reaudit-evidence/` and commit**, because /private/tmp is cleared on reboot.
**Read:** `CLAUDE.md`, `plan/briefs/README.md` (model tiers apply this time: sonnet for renders
and suite runs, haiku for inventory, ≤~10 agents per stage; list stage→model in the report).

## Scope rule

UI-only, as CL1. **Exception, narrow:** PANIC must be honest about what it did. Do not change
any gate's logic. If making PANIC truthful needs a gate API that does not exist (e.g. revoking
the BENCH acknowledgement), do not add one: make the TX slot read the *real* gate state and
show it, and list "PANIC cannot revoke BENCH ack" under **Hand to CL2** in the report.

## Fix, in this order. Every item needs a test that fails first, then passes.

**High**
1. PANIC kill: signal the whole process group (start children with `start_new_session`, kill
   with `killpg`), wait, verify dead, and report only verified-dead counts. Never count signals
   sent as processes killed. Test with a fake `sh -c 'a | b'` pipeline: both members dead.
2. PANIC TX display: after PANIC the TX slot shows what the gate says, read from the engine,
   not a cleared label. If BENCH's gate still passes, the slot says so. Test: bench ack held
   → PANIC → slot still shows PERMITTED and banner says "BENCH ack not revoked".
3. Mute: re-read the sink after every set; MUTED shows only if the read-back says muted;
   a failed mixer command shows a visible fault and leaves controls in the true state.
   Run mixer calls off the UI thread (worker, retained per the `_retain` rule). Test with a
   fake mixer that fails and one that hangs 2 s (UI stays responsive).
4. Alerts drawer: select/restore by alert **id**, never row index. Test: new alert arrives
   while drawer open → acknowledging acts on the alert the operator selected.

**Medium**
5. Slots never elide the varying part: widen or abbreviate so the full text is painted;
   tests assert on the painted/visible text, not the stored string. RADIO owner and ENG scope
   readable.
6. Readers fail to a visible **UNKNOWN** state (amber, word + shape), never OFF/NONE, if the
   engine read raises. Test by making the reader raise.
7. PANIC works with a combo dropdown or context menu open (application-level shortcut/event
   filter). Test.
8. ENGAGEMENT panel: scope list not clipped, evidence table ≥ 3 rows; strip/panel shows
   name, operator, target count (parity with main's RECON banner).
9. Alerts: never drop unacknowledged past 500 (cap acknowledged ones only). Test.
10. Sky-dome labels not clipped at 18 px. Visible focus ring on the active nav key and map style
    combo. Green removed from synthetic demo data (PROWL). Feed tables: no elided columns at
    18 px (give columns real widths).

**Earlier partials (RA-CL1 table)**
11. D1: tests that fail if a rail returns or value wrapping is off.
12. D2: slot captions 16 px, nav 16 px, section captions ≥16, table headers and scope labels
    pinned by a test that measures **rendered** `QFontInfo` pixel size of real widgets (the
    audit saw 10/11/13 px, so the earlier test is not checking real widgets: find out why and
    say so in the report).
13. D3: trim OPS scope dead space (≤ 24 px each side); test for the vertical sub-tab rail.
14. D9: test that fails if ARMED/ACTIVE slots turn green; BABEL protocol colours readable
    (≥7:1 in SUN, ≥4.5:1 in LIGHT).
15. D10: empty detail cards collapse (no 214–636 px blanks); test the OPS alert card.
16. RADIOS: refresh while visible (timer or arbiter signal), not only on open.
17. Tests for R, E, M, `[` `]` keys and PANIC with a panel open.
18. Detectors start when SWEEP opens: pin with a test and note it as intended in the report.

Skip the ~25 Low items; list the unverified ones under "found, not fixed".

## Not fixable here: say so in the report

Python 3.13 run, uConsole, real window manager (`show()` vs fullscreen), real tiles. Give the
owner one device command to run later; do not claim them checked.

## Done means

Suite + pyflakes pasted for real, renders at exactly 1280×720 (dark/light/sun × live/demo),
report appended, branch pushed, no PR change. Then **stop**: a second cold re-audit
(`RA-CL1b`, fresh chat, scoped to items 1–18) decides the merge.

Commits end with:
```
Co-Authored-By: Claude Mythos 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01DNwALPN1Ydsu8Kidx4CrT4
```
