# RA-CL3b — scoped cold re-audit of CL3-fix (`fix/cl3-evidence` @ 13c04a4)

**Verdict: DO NOT MERGE.** One blocker (B3): if the hub ENDs while a bound child's gated process
is running, the child's `kill` and `exit` records go to a fresh per-child session chain. The
engagement chain ends `… spawn, engagement.close`, and the row stays **RUNNING** forever. This is
the B1 defect class on the normal device END path, which the brief names explicitly (item 2). Every
RA-CL3 item is otherwise closed.

Auditor: fresh headless session, Claude Opus 5.5. All stages ran on the session model, with no
subagents (token budget). Python **3.12.16** (Mac venv: PySide6 6.12.0, pyqtgraph, flask,
numpy, tkinter), Qt offscreen.
Evidence: `plan/briefs/RA-CL3-poc/poc_ra_cl3.py` (updated) and
`plan/briefs/RA-CL3b-poc/poc_ra_cl3b.py`. To run: `SUITE=<checkout> pytest -q <file>` → **55 passed**
for both files together. `OK_*`/`FIXED_*` means the claim holds; `DEFECT_*` means the defect reproduces.

## 1. RA-CL3 PoC re-run (DEFECT → FIXED, expectations updated in place)

| RA-CL3 ID | Verdict | PoC (now passes as) |
|---|---|---|
| B1 child executions off-chain | **CLOSED** | `test_FIXED_bound_child_executions_land_in_the_engagement_chain`: authorize, issue, spawn, and exit 0 are all in the engagement chain, the row is EXECUTED, and no session chain exists |
| B2 stale chain on rollover | **CLOSED** | `test_FIXED_bound_child_follows_engagement_rollover` (+ END/START/START below) |
| N1 unkeyed head | **CLOSED** (residual → R1) | `test_FIXED_truncate_plus_head_rewrite_without_key_fails`: both the old 1-field head and a 3-field head with a junk MAC are refused |
| N2 id not bound | **CLOSED** | `test_FIXED_swap_two_chains_files_with_their_keys_and_heads_fails`, `test_OK_id_binding_rename_under_another_valid_id_fails` |
| N3 orphan bricks chain | **PARTIAL** → N13 | `test_FIXED_failed_head_write_is_rolled_back`, `test_OK_fsync_of_the_jsonl_fails_rolled_back`. Still bricks on a directory-fsync failure and on SIGKILL (N13) |
| N4 unlocked readers | **CLOSED** | `test_FIXED_locked_reader_sees_no_spurious_tamper` (0 failures), `test_OK_readers_and_three_writer_processes` (478 reads against 3 writer processes, 0 spurious, 300/300 authorizes) |
| N5 pid overwritten | **CLOSED** | `test_FIXED_spawn_and_kill_records_carry_the_child_pid` (spawn/kill `pid` = child, `wpid` = writer, row `pid <child>`) |
| N6 short key / perms | **CLOSED** | `test_FIXED_short_key_refused_and_jsonl_perms_checked` (16 B key → "damaged"; 0666 jsonl or head → "not private") |
| N7 start raises | **CLOSED** | `test_FIXED_start_never_raises_on_unencodable_name`, `test_FIXED_unencodable_field_records_…` (mixed int/str keys still `TypeError`; callers catch it) |
| N8 path traversal | **CLOSED** | `test_FIXED_chain_id_path_traversal_refused` (`open`/`for_id`/`exists`) |
| N9 refusals w/o engagement | **CLOSED** | `test_FIXED_refusals_without_engagement_are_recorded` (prune policy still owner Q2) |
| N10 two rows / redeem refusal | **CLOSED** (note N15) | `test_n10_*` in the suite; `test_OK_refusal_execution_kill_recorded` shows one row per action |
| H9 memory on tamper | **CLOSED** | `test_FIXED_chain_states_not_served_from_memory_when_tampered` (`rows == []`); render: 0 rows under NOT VERIFIED |
| G7 field rewrite | CLOSED | `test_OK_rewrite_field_fails[*]` (incl. `wpid`) |
| symlink at create | CLOSED (stricter) | a dangling symlink is now refused too (`lexists`) |

## 2. Routing attacks

| Attack | Result | PoC |
|---|---|---|
| bound child across END / START / START | **OK**. Alpha's authorize goes to alpha. After END the child is refused, and the refusal goes to the child's session chain. START bravo, then START charlie (refused because bravo is open). The child authorizes into bravo only, and both chains verify | `test_OK_bound_child_across_END_START_START` |
| child started before the engagement | **OK**. Once the hub STARTs, the child's issue, spawn, and exit 0 go to the engagement chain | `test_OK_child_started_before_the_engagement` |
| shared state names a chain the child cannot open (missing id, key 0644, tampered record, `../../x`) | **OK**. In all 4 cases authorize → `(False …)`, issue → `(False …)`, and `chain.record` → `ChainError`. **No session-chain fallback** (`_SESSION` None, no `-session-` file) | `test_OK_shared_state_names_an_unopenable_chain_…` |
| **END while a bound child's process runs** | **DEFECT → B3**. Hub `end()` publishes "expired" and then "none" back to back. The child's 250 ms sweep sees no engagement, stops the process (`gate closed: no active engagement`), and its `kill` + `exit -15` route to a **new child session chain**. Engagement chain: `[open, authorize, issue, spawn, close]`. Row = RUNNING | `test_DEFECT_end_while_a_bound_childs_process_runs_…` |
| END while a hub process runs | OK: `kill < exit < engagement.close`, no session chain | `test_OK_end_while_a_hub_process_runs_…` |
| ticket issued before START, still running at START | **DEFECT → N14**. The bench TX ticket's `issue`/`spawn` are in the session chain. Its `exit` lands in the **engagement** chain. `states()` shows a `tx:bench EXECUTED` row the engagement never authorized, and the session chain never records the exit | `test_DEFECT_ticket_from_before_START_exits_into_the_engagement_chain` |
| two hubs' children on one DATA dir | **OK**. Hub 1 (alpha, this process) and hub 2 (bravo, subprocess) run 3 bound children each with 20 authorizes per child. 60/60 records land in the correct chain, both chains verify, and no session chains exist | `test_OK_two_hubs_children_on_one_data_dir` |

## 3. Head MAC / id binding / rollback / races

| Attack | Result | PoC |
|---|---|---|
| head MAC: truncate + forged head without the key | OK (refused) | above |
| id binding: copy files under another valid id | OK (refused) | `test_OK_id_binding_rename_…` |
| **snapshot rollback**: save jsonl+head at N, restore later | **DEFECT → R1**. Verifies without the key. Everything after N is gone, and the running hub keeps appending to the rolled-back chain with VERIFIED | `test_DEFECT_snapshot_rollback_without_the_key_verifies` |
| fail the head write | OK (rolled back, next authorize OK) | `test_FIXED_failed_head_write_is_rolled_back` |
| fail the jsonl fsync | OK (rolled back) | `test_OK_fsync_of_the_jsonl_fails_rolled_back` |
| **fail the directory fsync after the head `os.replace`** | **DEFECT → N13**. `_write_private` has already replaced the head (n+1) when it raises. `record()` then truncates the jsonl back to n, and every later open or append fails with "head says 2 records … file has 1" | `test_DEFECT_directory_fsync_failure_after_head_replace_bricks_the_chain` |
| **SIGKILL the writer between line fsync and head write** | **DEFECT → N13**. Orphan line, no rollback (the process is dead), and no recovery on open. Every later authorize in every process refuses | `test_DEFECT_sigkill_between_line_fsync_and_head_write_bricks_the_chain` |
| SIGKILL at random points under load | 12 kills, 0 bricked (the window is narrow; the deterministic PoC above proves it is reachable) | `test_sigkill_random_points_under_load` |
| reader/writer races, real processes | OK (0 spurious in 478 reads) | `test_OK_readers_and_three_writer_processes` |
| malformed head `² h m` / a jsonl line `1` | **DEFECT → N12**. Raises `ValueError` / `AttributeError`, not `ChainError`. `_active_chain` catches only `ChainError`, so for an uncached chain (a bound child) `authorize_action` **raises** instead of returning `(False, why)`, and `chain_info` raises (the panel shows its UNKNOWN row, not NOT VERIFIED). Fails closed, but by crash | `test_DEFECT_malformed_head_or_line_raises_non_chainerror_…` |

## 4. H9 panel (1280×720, live)

| Render | Result |
|---|---|
| `RA-CL3b-poc/engagement-{dark,sun}-live.png` | VERIFIED, 4 rows, one row per action. Panel 1220×640 @ (30,60). Sun shows a 1-step h-scroll even at normal size |
| `engagement-{dark,sun}-tampered-live.png` | **NOT VERIFIED, rows cleared (0)**. In sun the caption runs past the panel edge, so the reason ("record 2 fails its HMAC") is not visible. The words NOT VERIFIED are |
| `engagement-dark-stress-live.png` (34 rows, 50-char hostnames) | h-scroll (max 4). TARGET column 508 px wide; RESULT starts at x=898 in a 691 px viewport → **off-screen**. Right-aligned short IP targets render **blank**. STATE (x 108–238) stays visible |
| `engagement-sun-tampered-stress-live.png` | NOT VERIFIED, 0 rows; the caption is truncated to the chain id |

**N11 verdict: acceptable as a CL4 follow-up.** It does **not** hide a state word: STATE and NOT
VERIFIED stay on-screen in every render. It does hide RESULT (exit code / refusal reason) and
clips IP targets to blank under stress, and the tamper reason can overflow the caption. Wire the trail
to `FeedTable.fit_viewport` (CL1-fix2) and elide the caption reason in CL4.

## New findings

| # | Sev | Finding | Fix direction |
|---|---|---|---|
| **B3** | **HIGH (blocks)** | END while a bound child's process runs → its kill/exit go to a child session chain. The engagement row stays RUNNING and the engagement trail never shows the kill or exit code (`executor.record` → `chain.current()` keys on the engagement in force *at record time*) | Bind a ticket to the chain id in force **at issue** (store it in the executor entry) and route that ticket's `spawn`/`kill`/`exit`/`write`/`refuse_ticket` to `chain.for_id(that id)`, never `current()`. This also fixes N14. Regression: a real bound child with a running process, hub `end()`, then assert kill + exit (with code) are in the engagement chain before or after `close` and the row is KILLED |
| N13 | MED | N3 is not fully closed. (a) A directory fsync failure after `os.replace(head)` → jsonl rolled back under an advanced head → bricked. (b) SIGKILL/power loss between line fsync and head replace → orphan line → bricked, with no recovery on open | (a) Once `os.replace` succeeds, don't roll back the jsonl (treat the dir fsync failure as non-fatal, or re-write the old head before truncating). (b) On open under `LOCK_EX`: if the file has exactly head.n+1 records, the extra one chains to head.h, and it passes its HMAC, roll the head forward (or truncate it) and append a `recovered` record |
| N14 | MED | A ticket issued before START (session chain) that exits after START writes its exit into the engagement chain → a phantom EXECUTED row there, and the session chain lacks the exit | same fix as B3 |
| R1 | LOW (residual) | Snapshot rollback of jsonl+head verifies without the key. The head MAC proves (id,n,h), not freshness. The `chain.py` docstring ("dropping records fails against the keyed head") overclaims | Owner Q1 (off-device anchor). At minimum, state this limit in the docstring. An on-device monotonic counter (e.g. the hub's in-memory last-n, refusing if n decreases) would catch it while the hub is running |
| N12 | LOW | A malformed head or a non-object JSON line raises a non-`ChainError` out of `Chain.open`. Uncached (child) `authorize_action` and `chain_info` raise | Wrap `_parse`/`_check_head` failures in `ChainError` (`isinstance(rec, dict)`, `int()` in try); `_active_chain` should catch `Exception` |
| N15 | LOW | N10 folding keys on `(label, target)`. A custom `label=` would never fold (latent: no production caller passes `label=` today), and two interleaved authorizes of the same action+target from different processes fold to the wrong row | Carry the authorize record's `seq` into the `issue` record and fold by that |
| N11 | LOW | see §4 | CL4 |

## 5. Regression

- Full suite (Python 3.12.16, Qt offscreen, Mac): **1278 passed, 3 failed, 14 skipped** (274 s). The 3 failures (`test_audit_tiles::test_undecodable_tile_is_marked_failed`, `test_hwlab::test_doctor_hwbench_check`, `test_sstvdec::test_iss_passes_use_their_own_tle_and_leave_weather_cache_alone`) are the same 3 RA-CL3 recorded as pre-existing on base `93aaf27`. They are outside CL3. `tests/test_cl3_fix.py` 19/19 and `test_cl3_evidence.py` green
- pyflakes (`chain.py engagement.py executor.py palisade_qt/panels.py tests/test_cl3_fix.py tests/test_cl3_evidence.py`): clean (also clean on `RA-CL3b-poc/poc_ra_cl3b.py`)
- **Denial diff** (`d4d79f6..13c04a4 -- tests/`, the pre-fix tip). The brief says `13c04a4^`, but that is the fix commit itself, so I took the strictest reading and diffed against the pre-fix tip. Result: **no denial weakened**. The changes are `pid`→`wpid` (a field rename, same strength); `[AUTHORIZED, ISSUED]` → exactly `[ISSUED]` (stricter); one assert added (`detail == "scope"`); and `test_cl1_fix2` now also patches `chain_info`/`chain_states` to raise (it widens the UNKNOWN case).

## Stage → model
All stages ran on the session model (Opus 5.5). No subagents.

## Open questions (owner)
1. (= Q1) Off-device signed head. It is now the only defence against R1 snapshot rollback.
2. (= Q2) Prune policy for session chains. B3 adds one per child per END-with-running-process.
