# RA-CL3c — scoped cold re-audit of CL3-fix2 (`fix/cl3-evidence` @ 4995c5c)

**Verdict: DO NOT MERGE.** B3 and N14 are closed as the RA-CL3b PoCs define them. But the fix
makes no row RUNNING or ISSUED at close by **writing outcomes it has not verified**. Two cases
are High:

- **N16.** A bound child that dies hard gets `kill … (kill signalled by END)` and a **KILLED** row.
  END sends no signal, and the orphaned gated process **keeps running** after END.
- **N17.** `_settle_tickets` reads the chain, then writes void records later and not atomically.
  `states()` lets a `refuse_ticket` overwrite any state. A device write that lands inside that
  window ends as **REFUSED "ended"** even though the bytes went out.

Auditor: fresh session, Claude Opus 5.5. All verdicts are from the session model, with no
subagents. The environment was Linux, Python 3.12.3 (venv with PySide6, pyqtgraph, flask, numpy,
tkinter), Qt offscreen, under xvfb.
Evidence:
- `plan/briefs/RA-CL3b-poc/poc_ra_cl3b.py`. Its B3 and N14 tests are flipped in place to `FIXED_*`.
  Run it with `SUITE=<checkout> pytest -q` → **16 passed**.
- `plan/briefs/RA-CL3c-poc/poc_ra_cl3c.py` → **13 passed**. This takes about 3 min because the
  5000-record chain is built with O(n²) appends.

`OK_*`/`FIXED_*` means the claim holds. `DEFECT_*` means the defect reproduces.

## 1. RA-CL3b PoC re-run

| ID | Verdict | Evidence / test |
|---|---|---|
| **B3** END leaves a bound child's row RUNNING | **CLOSED** (for a child that reports, see N16 for one that cannot) | `poc_ra_cl3b.py::test_FIXED_end_while_a_bound_childs_process_runs_kill_exit_in_the_engagement_chain`: the child's own `kill` and `exit` (wpid = child, exit −15, `stopped` set) land in the engagement chain before `engagement.close`. No `by=end` records. Row KILLED, no session chain. Suite: `tests/test_cl3_fix2.py::test_b3_*` (7). Fix: `executor.py:58` (`for_id(chain_id)`), `:193` (`entry["chain"]`), `engagement.py:513-573` (`_settle_tickets`), `:833-838` (re-check bound to `issued_under`) |
| **N14** pre-START ticket exits into the engagement | **CLOSED** | `poc_ra_cl3b.py::test_FIXED_ticket_from_before_START_keeps_its_exit_in_the_session_chain`: the engagement chain never sees the ticket. The session chain has `exit 0` and the row is EXECUTED. Suite: `test_n14_a_ticket_from_before_start_keeps_its_exit_in_the_session_chain` |
| every other RA-CL3b test | holds | All `OK_*`/`FIXED_*` pass. `DEFECT_*` for R1, N13 (two tests) and N12 still reproduce. These are known open items and this fix does not change them |

## 2. Attacks on END (`engagement.end` → `_settle_tickets`)

| Attack | Result | PoC (`poc_ra_cl3c.py`) |
|---|---|---|
| 4 bound children, each running one process, one of which ignores SIGTERM | **OK**. END takes 1.23 s. 4 kills and 4 exits, all written by the children, all before close. Close is the last record. 0 RUNNING/ISSUED rows at close. No session chain, no live pids | `test_OK_end_with_four_children_one_ignoring_sigterm` |
| 1 child running 3 SIGTERM-ignoring processes. Its sweep stops them one after another, about 1 s each | **OK, bounded** (→ N19 Low). END takes 2.04 s. END writes a `kill by=end` for the third process before close, so the row is KILLED at close. The child's own `kill`/`exit` records land **after** close, which leaves 2 kills for one ticket. All pids are dead and the final rows are KILLED | `test_OK_end_one_child_three_sigterm_ignoring_processes_overruns_the_drain` |
| child SIGKILLed after spawn | **DEFECT → N16**. END writes `kill` by=end ("…kill signalled by END") before close, and writes nothing for the child that reported. Both rows show KILLED. **The dead child's `sleep` (own session) is still alive after END** | `test_DEFECT_sigkilled_child_end_records_kill_but_the_process_keeps_running` |
| redeem at the moment END voids. The re-check has passed and the spawner is still starting | **DEFECT → N18**. Trail: `issue, refuse_ticket(by=end, "before the ticket was used — void"), engagement.close, spawn, kill, exit`. The final row KILLED is correct. The void record is false, and the spawn is recorded after close | `test_DEFECT_redeem_racing_end_void_is_recorded_as_never_used` |
| device write landing between END's read and END's void | **DEFECT → N17**. Trail: `issue, write, refuse_ticket(by=end)`. The final row is `REFUSED "ended"`, but the port received the bytes | `test_DEFECT_void_after_write_hides_an_executed_device_write` |
| txguard bench ticket in a bound child across END | **OK**. END writes nothing about it. Its own `issue/spawn/exit` stays in the chain it was issued under | `test_OK_child_txguard_bench_ticket_across_end_not_claimed` (+ suite `test_b3_end_does_not_claim_…`) |
| END while the chain is tampered / not private (0644) / unwritable | **OK**. END returns the name in 0.00 s, 0.01 s and 2.03 s. The hub's process is killed and the engagement is no longer active. When the chain does not verify, nothing is settled. This is fail-safe: there is nothing it could write | `test_OK_end_completes_when_the_chain_is_broken[tamper,perms,unwritable]` |
| END wall time on a large chain: 5000 records and 20 issued, never-used tickets | 1.46 s. Each void record re-verifies the whole chain under the lock. The time from END's read to the last void is **1.34 s**, and that is N17's natural window | `test_OK_end_time_on_a_large_chain_with_many_void_tickets` |

## 3. Ticket→chain binding

| Attack | Result | PoC |
|---|---|---|
| END alpha / START bravo with the same scope inside the TTL. The alpha ticket is redeemed under bravo | **OK**. Refused. Alpha holds `issue, refuse_ticket(void), refuse_ticket(redeem)` and bravo has nothing | suite `test_b3_a_ticket_from_alpha_is_void_under_bravo` |
| alpha process still running under bravo. The child is SIGSTOPped across END and START, so it never sees the gap | **OK**. END writes `kill by=end` in alpha before close. On SIGCONT the child's re-check fails ("engagement changed"), and its kill and exit land in **alpha** after close. Bravo has no ticket records and there is no session chain | `test_OK_stopped_child_misses_rollover_kill_exit_go_to_alpha_not_bravo` |
| bound chain deleted before kill/exit | **OK**. The records are dropped. None go to bravo and no session chain is created | `test_OK_bound_chain_deleted_before_exit_nothing_misfiled`, suite `test_executor_never_falls_back_…` |
| two hubs on one DATA dir | **OK** (unchanged). Each END reads and settles only its own chain id | `poc_ra_cl3b.py::test_OK_two_hubs_children_on_one_data_dir` |
| ticket issued in a child before START | **OK**. Only a txguard ticket is possible with no engagement. It is bound to the child's session chain, the same as N14 | (by construction, + N14 test) |

## 4. `states()` fold

| Check | Result |
|---|---|
| a later spawn or exit after a folded `refuse_ticket` | **OK**. A later record overrides it (REFUSED → RUNNING → EXECUTED) — `test_OK_fold_does_not_hide_a_later_running_or_executed` |
| redeem refusal of a known ticket | **OK**. It stays visible as that row's `REFUSED` + reason (`scope`). A refusal for an unknown ticket keeps its own row |
| a `refuse_ticket` recorded **after** spawn, write or exit | **DEFECT → N17**. The fold overwrites any state unconditionally (`chain.py:305-309`). A void that lands after a `write` permanently hides EXECUTED. One that lands after a `spawn` hides RUNNING until a kill or exit arrives, and if the reporter is dead that never happens |

## New findings

| # | Sev | Finding | Fix direction |
|---|---|---|---|
| **N16** | **HIGH (blocks)** | For a spawned ticket with no kill (a SIGKILLed, OOM-killed or crashed bound child), END records `kill` by=end, reason "**kill signalled by END**", and the row reads **KILLED**. END signals nothing. The gated process runs in its own session (`start_new_session=True`), so it survives its parent and keeps running after END with no gate re-checking it. The trail tells the operator it was killed. Before the fix the row stayed RUNNING, which was true | In `_settle_tickets`, actually kill it. The spawn record has `pid`, which is the pgid for the default spawner. Also record the process start time at spawn (`gatestate.proc_start`) so END can `killpg` only that exact process, never a recycled pid. Then record `kill` with the real result. If the identity cannot be confirmed, record an honest state such as `LOST: pid N not confirmed stopped` and do not show KILLED. Regression: SIGKILL a bound child, END, then assert the grandchild pid is dead and the record is truthful |
| **N17** | **HIGH (blocks)** | `_settle_tickets` reads the open tickets and then writes `refuse_ticket`/`kill` later, outside the chain lock and with no re-check. `states()` lets a known ticket's `refuse_ticket` overwrite any state. If a `write` or `spawn` from a bound child (or a hub thread) lands in between, the final trail shows the action **REFUSED "ended"** although it executed. The window is the full span of END's void loop: 1.34 s measured at 5000 records with 20 tickets. A writer's `LOCK_EX` append queues behind END's `LOCK_SH` read, so it lands right after it | (a) Make END's outcome records conditional and atomic. Add a `Chain.record_if(pred, …)` that evaluates `pred(records)` under the same `LOCK_EX` after the re-sync, and skips the record if the ticket has gained a spawn, write or exit. (b) In `states()`, let a `refuse_ticket` change only an `AUTHORIZED`/`ISSUED` row and never a RUNNING, EXECUTED, FAILED or KILLED one |
| N18 | MED | A redeem whose re-check passed just before END publishes, still inside the spawner, is recorded by END as "engagement ended **before the ticket was used** — void". The ticket was used, and its spawn, kill and exit follow after `engagement.close`. The final row is correct (KILLED) and the process is killed by the post-spawn sweep. The void record is false | Use the same conditional record as N17. Also word the void as "not used by close" and drop "before the ticket was used". In-process, END can skip tickets whose executor entry is `used` |
| N19 | LOW | END's drain (2 s) overruns when one child stops several SIGTERM-ignoring processes one after another (~1 s each). END papers over the unreported one with `kill by=end`, then the child's real `kill` and `exit` land **after** `engagement.close`, giving 2 kills for one ticket. The result is honest and bounded, but the chain does not end at close | Have the child's sweep stop processes in parallel (signal all, then wait), or document that post-close records are expected |

Known follow-ups re-rated: none. N12, N13, N15, R1 and N11 are unchanged by this fix, and their PoCs
behave as they did in RA-CL3b. Note on N13: `Chain.record` re-verifies the whole chain on every append,
so building 5000 records takes about 3 min. That is pre-existing and not rated here. It is the
reason END's void loop is slow on long engagements (N17 window).

## 5. Regression

- Full suite (Python 3.12.3, xvfb, Qt offscreen), one run that overlapped with the PoC run:
  **1293 passed, 5 failed, 5 skipped** (562 s).
  - 3 failures are the known baseline: `test_audit_tiles::test_undecodable_tile_is_marked_failed`,
    `test_hwlab::test_doctor_hwbench_check` and `test_sstvdec::…iss_passes…`.
  - `test_cl1_screen::test_up_down_drive_the_list_and_the_detail_follows` is the known flaky test.
  - `test_cl1_fix2::test_ack_all_never_acks_an_alert_that_arrived_after_the_drawer_was_viewed`:
    see the isolated re-run below. The fix touches no UI or alert code (`git diff ab209b7..4995c5c`
    = `chain.py engagement.py executor.py` + tests + report).
- Isolated re-run with no PoCs in parallel:
  - `test_cl1_fix2 test_cl1_screen test_cl3_fix2 test_cl3_fix test_cl3_evidence`: run 1 gave
    112 passed, run 2 gave 1 failed + 111 passed (consistent with the known flaky up/down
    test). A third run did not finish within my wait window.
  - `test_cl1_fix2 … ack_all`: **5/5 passed**, so its failure in the full run is load-induced
    flakiness and not a regression.
  - CL3 tests: green in both completed runs.
- pyflakes (`chain.py engagement.py executor.py tests/test_cl3_fix2.py` + both PoC files): clean.
- **Denial diff** `ab209b7..4995c5c -- tests/`: one file is added (`tests/test_cl3_fix2.py`, +297)
  and there are **0 deleted or changed lines** in existing tests. No denial is weakened.
- No renders, per the brief (no UI change).

## Stage → model
All stages ran on the session model (Opus 5.5). No subagents.

## Open questions (owner)
1. N16: should END kill an orphaned gated process by pid + start time (an active kill from the hub
   into a process it did not spawn), or only record it honestly as unconfirmed and alert? The
   first is safer for emissions. The second never signals a pid END cannot prove is the one it
   spawned.
