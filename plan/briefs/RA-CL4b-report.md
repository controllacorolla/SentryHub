# RA-CL4b — cold re-audit of CL4-fix (`fix/cl4-honest-state` @ 1c884d5, code @ f8172a2)

**Verdict: MERGE.** N26, the High finding that blocked RA-CL4, is closed in steady state. With HOME unset (live),
OPS and ATLAS draw no rings, positions, basemap or centre marker, and no tile is ever requested. Setting HOME in
SETTINGS brings the picture back live, centred on HOME. N27–N32, N34 and the E1 residual are closed, each with a
test. Every RA-CL4 DEFECT PoC for a fixed ID now fails because the defect is gone. Three new findings are not
blockers: N35 (Med, a transient ≤12 s on OPS after HOME is set), N36 (Med, pre-existing, END leaves a live group
member) and N37 (Low).

Auditor: fresh session, Claude Opus 5.5. I read `RA-CL4-report.md`, the brief, the diff `692513f..f8172a2`, and only
the lines each finding cites. `CL4-report.md` was not read. Env: Linux, **Python 3.12.3** venv (PySide6 6.12,
pyqtgraph, flask, numpy, tkinter), xvfb, Qt offscreen.
New PoCs: `plan/briefs/RA-CL4b-poc/poc_ra_cl4b.py` (22 tests; real chains, real processes, a real HTTP server on
127.0.0.1). Renders and their script: `plan/briefs/RA-CL4b-renders/`.

## Step 1 — RA-CL4 PoCs rerun on the branch

`poc_ra_cl4_gates.py` + `poc_ra_cl4_honest.py`: **28 passed, 6 failed**. The 6 failures are the DEFECT tests for
N23/N32 (session leader), N31, N27, N28, N26-ATLAS and N29. Each now fails because its defect is gone.
Two DEFECT/RESIDUAL tests still pass:
- `test_DEFECT_ops_ppi_without_home_plots_contacts_around_a_provisional_origin` still passes, but it asserts OPS's
  *internal* x/y, not what is drawn. The PPI is now handed `[]` and is covered (see
  `test_FIXED_n26_ops_home_unset_ppi_draws_nothing`). This is not a reproduction.
- `test_RESIDUAL_torn_partial_line_still_bricks_but_fails_closed` (N33) still reproduces, which is expected: N33 is
  declared not fixed.

## Per ID

| ID | Verdict | Evidence | Test |
|---|---|---|---|
| **N26** (High) | **CLOSED** (Med residual → N35) | `Cover` (`kit/components.py:289-314`) lies over the PPI (`ops.py:222-224, 313-315`) and the map (`atlas.py:742-745, 887-892`), and both are given `[]` when live with no HOME. `MapPanel._can_fetch` (`mappanel.py:97-130`) is False for a `None` origin, so there is no tile at construction or on a style flip. Recorded fetches: `[]`. Cover geometry equals the target's rect. The HOME marker is hidden. The detail card and table show RANGE "—". A HOME saved through `MoreApp._save_settings` (no restart) lifts both covers, makes ATLAS fetch `('dark', 47.6, -122.3)`, and re-projects contacts from HOME (0.3° N gives 18 nm on bearing 000). ATLAS drops provisional-frame contacts. **OPS does not** (N35) | `test_cl4_honest::test_n26_*` (2). PoC `test_FIXED_n26_*` (3). Renders `ops_home_unset_*`, `atlas_home_unset_*`, `ops_home_set_*`, `atlas_home_set_*` |
| N27 | CLOSED | Real chain, one byte altered. Caption "NOT VERIFIED: … record 1 fails its HMAC", trail STALE "TRAIL UNREADABLE — the chain failed verification" (`panels.py:458-461`). An R1 snapshot rollback in-session gives the same result. "nothing authorized" never appears | `test_n27_tampered_trail_is_not_watching`. PoC `test_FIXED_n27_*`, `test_FIXED_n28_rollback_*` |
| N28 | CLOSED | Real chain, garbage `.head`, engagement active. `chain_unreadable()` (`engagement.py:974-985`) gives the reason. Caption "Evidence chain UNREADABLE — … head file malformed", trail STALE with that reason. The gate refuses. With no engagement it still says "NO ENGAGEMENT" / "none open". `chain_unreadable` opens via the same `chain.for_id` that `_active_chain` already calls, so there is no new side effect | `test_n28_*` (2). PoC `test_FIXED_n28_malformed_head_*`, `test_OK_no_engagement_*` |
| N29 | CLOSED (Low residual → N37) | `eventbus.py:194-197`: only `contact`/`decode` that is not telemetry marks a feed. The OVERWATCH pass alert, ATLAS RADIO BUSY and OPS telemetry give `feeds() == {}`, and SITREP says "No feed is running". "Watching X" now needs a contact or decode publisher. CONTACT_TTL 300 s and the decode window 600 s are both longer than FEED_LIVE 120 s, so the line cannot appear without contacts or decodes. A FORGE "serial device connected" decode still counts as a feed (N37) | `test_n29_*`. PoC `test_FIXED_n29_*` |
| N30 | CLOSED | `recon.py:540-541` pauses the Wi-Fi worker before `start()`. 15 starts hidden on the WIFI subtab and 15 hidden on BLE ran **0** scans (RA-CL4: 14/30) | `test_n30_*`. PoC `test_FIXED_n30_*[WIFI,BLE]` |
| N31 | CLOSED (Med pre-existing → N36) | `_kill_orphans` returns `(False, "exited")` when nothing was signalled (`engagement.py:692-693`). END records `unconfirmed` "exited on its own before END signalled it; exit status not observed" and sends no signal. Never `kill`. `_kill_orphan` has no callers | `test_n31_*`. PoC `test_FIXED_n31_*`. RA-CL4 `test_DEFECT_kill_recorded_by_end…` now fails |
| N32 | CLOSED | `_protected_pids()` (`engagement.py:549-568`) covers pid, ppid, pgrp, `getsid(0)` and the `/proc` ancestor chain. Keyed forged spawns naming the real session leader **and** the grandparent got 0 signals from END. On macOS the walk stops at ppid (no `/proc`), so sid and ppid are still covered; the key remains the boundary (info) | `test_n32_*`. PoC `test_FIXED_n32_*`. RA-CL4 `test_DEFECT_n23_…session_leader…` now fails |
| N34 | CLOSED | `eng_chain.setWordWrap(True)` (`panels.py:346`). In sun mode at 1280 the "NOT VERIFIED: chain …" caption wraps onto two lines without clipping | render `engagement_tampered_sun_live.png` (no test; render-only Low, as RA-CL4 classed it) |
| E1 residual | CLOSED | `sky_app.py:697-712`: with no numeric `now`, a file source uses its mtime and HTTP uses age ∞. A future `now` (outside ±10 s) is stale. On a real HTTP server, `now` absent / +1 h / string / NaN / `true` all give **stale**, and a current `now` gives live. A file with no `now` is live with a fresh mtime and stale at 120 s | `test_e1_residual_*`. PoC `test_FIXED_e1_http_*` (5), `test_OK_e1_*` (2) |
| N33 | not fixed (declared) | Torn final line still refuses the chain (fail closed) | RA-CL4 `test_RESIDUAL_torn_partial_line…` still passes |

**Regression of RA-CL4 CLOSED items:** none. All RA-CL4 `FIXED_*`/`OK_*` PoCs still pass (N20 ×4, N24, N23, N13,
N12 ×11, R1, H17, E1/L5, H3 ×2, H2 ×2, H4). `test_cl4_gates.py` + `test_cl4_honest.py`: **100 passed**.

## Step 2 — attacks, other results
- **N26, other surfaces:** OVERWATCH predicts nothing without HOME (unchanged). The assistant's map answer gives
  counts only, never a range. The cover is raised over the map's style combo and blocks hover, so there are no
  tooltips. Demo mode is unchanged (DEMO_HOME).
- **N27/N28:** I found no state in which the trail says "nothing authorized" or "NO ENGAGEMENT" while it cannot know.
  Tampered, malformed head and in-session rollback all read STALE / UNREADABLE. An exception in `chain_info` still
  gives the UNKNOWN row.
- **UI-only rule:** every non-UI change traces to a finding: `engagement.py` (N28/N31/N32), `eventbus.feeds` (N29),
  `recon` pause (N30), `sky_app` age (E1). No radio, decoder or gate behaviour changed otherwise.

## New findings

| # | Sev | Finding | PoC | Fix direction |
|---|---|---|---|---|
| **N35** | MED | OPS has no `home_changed` handler. Contacts heard before HOME was set keep the x/y/rng computed from the provisional origin (the first contact). When HOME is set live, the cover lifts at once and, until each contact is heard again (≤ `STALE_S` = 12 s), the PPI draws them around HOME with the first one dead centre, and the sub-line reads **"nearest 0 NM"** for an aircraft ~880 nm away (Seattle contact, HOME = Denver). ATLAS clears its contacts on `home_changed`; OPS does not. Transient and bounded, but it is a range readout from the guessed origin | `test_DEFECT_ops_after_home_set_shows_nearest_range_from_the_guessed_origin` | Connect `eventbus.bus.home_changed` in OPS and clear `_contacts` (as `AtlasApp._on_home_changed`), or recompute x/y from stored lat/lon on refresh |
| N36 | MED (pre-existing) | When the orphan's **leader** exits before `_kill_orphans` acts (in the race, or already gone or zombie at `_settle_tickets`) but a member of its process group is still running, END sends nothing to the group. The record is honestly `unconfirmed` ("exited on its own…", which does not mention the survivor), but a process of the gated tool keeps running after END, although its pgid is safe to signal (a pgid with live members cannot be reused). Before CL4-fix the race path wrote a false `kill verified_gone`, so the fix improved the record. The live survivor is not new | `test_DEFECT_n31_leader_exits_before_kill_live_group_member_survives_end` (group alive after END: True) | When the logged pid is gone but `pgid == pid` still has live members, `killpg` it (TERM→KILL) and record `kill` for the group, or say "a process in its group is still running" |
| N37 | LOW | FORGE publishes a `decode` "serial device connected" (`forge.py:186`) when a port opens. `feeds()` then lists FORGE for 2 min, so SITREP drops "No feed is running … not an all-clear" and the assistant drops "nothing is being watched". It never says "Watching" | `test_DEFECT_n29_forge_serial_connect_counts_as_a_running_feed` | Publish the connection as an alert/status, or exclude `proto == "SERIAL"` connection notices from `feeds()` |

## Step 3 — renders (1280×720, live, dark + sun)
`plan/briefs/RA-CL4b-renders/`: `ops_home_unset`, `ops_home_set`, `atlas_home_unset`, `atlas_home_set`,
`engagement_none`, `engagement_tampered`, `engagement_malformed_head` × `{dark,sun}` (14 files). They were produced by
`render_ra_cl4b.py` with tile fetches recorded, not sent. There is no blank table: each empty view has an
EmptyState with a reason. Strip `minimumSizeHint` is at most **1123 px** (sun, ENG active), within 1270. In the
`engagement_malformed_head` frames the chain was already tampered, so the reason shown is the HMAC failure. The
malformed-head-only text is covered by PoC `test_FIXED_n28_malformed_head_*`.

## Step 4 — regression
- `tests/test_cl4_*.py`: **100 passed**.
- Full suite, Python 3.12.3 (`QT_QPA_PLATFORM=offscreen xvfb-run -a python -m pytest -q tests`): **1486 passed, 3 failed, 6 skipped** in 674 s. The 3 failures are the known baseline set, the same as RA-CL4 and main (`test_audit_tiles::test_undecodable_tile_is_marked_failed`, `test_hwlab::test_doctor_hwbench_check`, `test_sstvdec::test_iss_passes_use_their_own_tle…`). There are 10 more passes than RA-CL4's 1476, which are the CL4-fix tests.
- Assertion diff `692513f..1c884d5 -- tests/`: only `tests/test_cl4_honest.py` changed, with +132 lines and **0
  removed**. No assertion was weakened.
- pyflakes: changed files, new PoC and render script are clean.

## Stage → model
Every stage ran on the session model (Opus 5.5). No subagent tool was available in this run, so the PoC reruns,
suite and renders, which the README assigns to `sonnet`, were run directly. All verdicts are the session model's.

**MERGE**
