# RA-CL3d — scoped cold re-audit of CL3-fix3 (`fix/cl3-evidence` @ e5a0e54)

**Verdict: MERGE.** N16, N17, N18 and N19 are closed. Each RA-CL3c PoC now asserts the fixed
behaviour and passes. END sends no signal unless the pid and start time match exactly, and it
writes `kill` "orphan at END" only after the launched pid is gone. Every END record is now
conditional and taken under `LOCK_EX`.

There are no new Critical or High findings. One new Medium finding, **N20**, applies to
multi-process groups: `verified_gone` checks only the group leader. The executor's own
`_kill_group` behaves the same way, so this is not a regression from this fix. Fix it as a
follow-up on both kill paths. N21–N25 are Low.

Auditor: fresh session, Claude Opus 5.5. Every verdict comes from the session model. No subagents
were used.

Environment: Linux, Python 3.12.3 venv (PySide6, pyqtgraph, flask, numpy, tkinter), Qt offscreen,
xvfb. I read `RA-CL3c-report.md`, the "CL3-fix3" section of `CL3-report.md` and the diff
`4954cdf..e5a0e54`, and nothing else from the planner.

PoCs: `SUITE=<checkout> pytest -q <file>`
- `plan/briefs/RA-CL3b-poc/poc_ra_cl3b.py`: unchanged. **16 passed**.
- `plan/briefs/RA-CL3c-poc/poc_ra_cl3c.py`: updated in place. **13 passed**.
- `plan/briefs/RA-CL3d-poc/poc_ra_cl3d.py`: new. **26 passed**.

A combined run of all three gave 54 passed and 1 failed, in 611 s. The failure was the N22 zombie test:
the N21 race also turns up in its post-SIGCONT final row. I relaxed that assertion to accept
EXECUTED or KILLED and re-ran the test 4 times, all green. On the large chain, END took 1.42 s, and
the span from read to the last void was 1.29 s.

`OK_*`/`FIXED_*` means the claim holds. `DEFECT_*` means the defect reproduces.

## 1. RA-CL3c / RA-CL3b PoC re-run (in-place updates)

| ID | Verdict | Evidence / test |
|---|---|---|
| **N16** false KILLED for an orphan | **CLOSED** (single-process orphan; see N20 for groups) | `poc_ra_cl3c.py::test_FIXED_sigkilled_child_end_kills_the_orphan_and_records_it_truthfully`: END `killpg`s the orphan, which is dead afterwards. The record is `kill` "orphan at END" with `verified_gone: true` and `pid`/`pstart`. The row is KILLED. It takes 2.10 s. Fix: `engagement.py:549-602` (`_same_process`, `_zombie`, `_kill_orphan`) and `:637-651`. `executor.py:333-341` (`pstart`). Suite: `test_n16_*` (4), `test_b3_end_leaves_no_ticket_running_or_issued_even_without_confirmation` |
| **N17** END void hides an executed write | **CLOSED** | `poc_ra_cl3c.py::test_FIXED_void_after_write_no_longer_hides_an_executed_device_write`: the trail is `issue, write` with no void, and the row is EXECUTED. Fix: `chain.py:236-253` (`_only_if` under `LOCK_EX`), `chain.py:311-318` (a refusal only replaces AUTHORIZED/ISSUED) and `engagement.py:629-656`. Suite: `test_n17_*` (2) |
| **N18** void reason "before the ticket was used" | **CLOSED** (wording, as scoped) | `poc_ra_cl3c.py::test_FIXED_redeem_racing_end_void_no_longer_claims_never_used`. The reason is now "no use of this ticket recorded by then". The trail is still `refuse_ticket(end), close, spawn, kill, exit`, so the spawn comes after close. The final row is KILLED. The report says this outcome is expected |
| **N19** two kills for one ticket | **CLOSED** | `poc_ra_cl3c.py::test_FIXED_end_one_child_three_sigterm_ignoring_processes_overruns_the_drain`: every ticket has ≤1 kill and no kill lands after close. Any END kill is `orphan at END`/verified. END now takes 3.11 s, up from 2.04 s, because it kills the third process itself (→ N24). Suite: `test_n19_*` |
| rollover (`test_OK_stopped_child_misses_rollover_…`) | **updated per owner decision; trail at close honest** | Alpha: `spawn, kill(by=end, "orphan at END", verified_gone, pid=proc), engagement.close, exit(-15)`. Bravo has no ticket records and there is no session chain. In about half of the runs the tail is `exit, kill`: the child's sweep records a kill of the already-dead process after its exit. The test now accepts both orders. The tail is untrue → **N21** |
| all other RA-CL3c / RA-CL3b tests | hold | All pass. Large chain: 5000 records and 20 void tickets. The `DEFECT_*` tests for R1, N12 and N13 still reproduce (known open items, unchanged) |

## 2. Attacks on the orphan kill (`poc_ra_cl3d.py`)

| Attack | Result | Test |
|---|---|---|
| Recycled pid (start differs by 1 tick), pid 0, pid 1, own pid, `True`, `"pid"` str, float pid, negative pid, missing/empty/forged (`linux:0`)/int `pstart` | **OK, no signal** for every case. A spy on `os.kill`/`os.killpg` records nothing to the victim, 0, 1, the hub's pid or the hub's pgrp. The victim stays alive. END records `unconfirmed` "…END sent no signal" and the row is UNCONFIRMED | `test_OK_end_sends_no_signal_without_an_exact_identity_match[12 cases]` |
| The hub's **own process-group leader** named in a forged record with its real start time | **DEFECT → N23 (Low)**. `_same_process` excludes `getpid()` but not `getpgrp()`. `_kill_orphan` avoids `killpg` on its own group but then calls `os.kill(pgrp_leader, TERM/KILL)`, which signals the hub's launcher (a shell or session leader). The spy blocked the signal. This needs the chain key | `test_DEFECT_own_process_group_leader_is_signalled_by_a_forged_record` |
| A record forged **with the key**, naming another of the user's processes with its real start time | **DEFECT, informational (part of N23)**. END TERM/KILLs that process's whole group and logs it as an orphan kill. The HMAC key (0600, same uid) is the boundary. Anyone who holds it can already signal the user's processes directly, so END adds no capability. Without the key a record does not verify. A key-less rollback (N12/R1) can only remove records, and removing a kill/exit makes END kill the genuine matching process, which is the safe direction | `test_DEFECT_forged_record_with_the_key_kills_any_same_uid_process_group` |
| Orphan group: leader exits on SIGTERM, a group member ignores SIGTERM | **DEFECT → N20 (Medium)**. `_kill_orphan` re-checks only the leader. Once the leader is gone it returns "verified gone" without sending SIGKILL. END records `kill` "orphan at END" `verified_gone: true`, the row is KILLED, and the helper in the same gated process group **keeps running**. The executor's own `_kill_group` waits only for the leader as well, so a hub-owned kill leaves the same survivor | `test_DEFECT_group_member_ignoring_sigterm_survives_a_verified_gone_orphan_kill`, `test_PREEXISTING_hub_executor_kill_has_the_same_group_semantics` |
| Which groups END signals | **OK**. Only `killpg(orphan)`. END never signals the hub's pid or group, the dead child's pid, or a sibling child's group | `test_OK_end_never_signals_the_hubs_own_group_or_a_childs_group` |
| Orphan ignores SIGTERM | **OK**. TERM, then KILL after 1 s. Recorded as `kill` verified. END takes 3.10 s | `test_OK_orphan_ignoring_sigterm_is_sigkilled_and_recorded_verified` |
| Orphan survives SIGKILL (simulated D-state: signals swallowed) | **OK**. TERM then KILL are sent and END records `unconfirmed` "orphan at END: signalled, still alive". The row is UNCONFIRMED, never KILLED. END takes 4.06 s | `test_OK_orphan_that_survives_sigkill_is_unconfirmed_never_killed` |
| Zombie orphan: the process exited, and its stopped parent cannot reap it | **State honest, reason wrong → N22 (Low)**. END sends no signal and records `unconfirmed` "pid N **does not match** the process logged at launch". The pid does match; the process has already exited. After SIGCONT the child's exit wins and the row is EXECUTED. Sometimes the row is KILLED instead, because the N21 race also adds a kill | `test_DEFECT_zombie_orphan_reason_says_pid_does_not_match` |
| Child reports its exit or kill during END's kill | **OK**. The `unreported` predicate runs under `LOCK_EX` and drops END's record when the child's kill or exit landed first. The three-process run shows `by_end == []` with all rows KILLED | RA-CL3c N19 test |
| Rollover: the stopped child resumes after END killed its process | **Untrue tail → N21 (Low)**. (a) The tail is `exit -15, stopped=None` and the fold shows the final row as **FAILED "exit -15"** above END's verified kill. (b) Otherwise the child's sweep records a `kill` "gate closed…" **after** the exit, which is a kill of a dead process and a second kill for the ticket. Both come from the executor's pump/sweep race (`executor.py:288-314`): `stop()` runs on a handle whose exit is recorded but whose `_done` is not yet set. END now exposes it. The row at close (KILLED) is correct | `test_DEFECT_rollover_resumed_child_writes_an_untrue_tail_after_ends_verified_kill` |
| END wall time, 4 SIGTERM-ignoring orphans | 6.31 s. The orphans are killed one at a time at about 1.05 s each after the 2 s drain. One that survives SIGKILL costs about 2 s → **N24 (Low)** | `test_OK_end_wall_time_with_four_sigterm_ignoring_orphans` |
| A step raises (`_kill_orphan` raises for one orphan) | **OK**. END completes and closes, and the other orphan is killed and recorded. The ticket whose step raised gets no record and stays RUNNING at close. The only realistic raise there is `ChainError`, and then nothing can be written anyway (`proc_start`/`_zombie`/`getpgid` errors are all caught) | `test_OK_end_completes_when_a_step_raises` |
| macOS (`_darwin_start`, zombie check) | **Reviewed by reading only. Not run, because no Mac was available.** `_darwin_start` reads `kp_proc.p_un.p_starttime` at offset 0 of `kinfo_proc` (`qi`), which is correct. **There is no `ps`-based zombie check on the tip**: the brief's description is stale, and the CL3 report says it was removed. On darwin `_zombie()` returns False. A zombie orphan that matches (stopped parent) is therefore TERM/KILLed (a no-op), waited on for about 2 s, and recorded `unconfirmed` "signalled, still alive". That is fail-safe and never a false KILLED, but it costs 2 s and the reason is wrong → **N25 (Low)**. On a Mac the RA-CL3c rollover PoC would see UNCONFIRMED instead of KILLED |

## 3. `Chain.record(_only_if=…)`

| Check | Result | Test |
|---|---|---|
| Skipped record | **OK**. Returns None. The `.jsonl` and `.head` bytes are unchanged, the chain verifies, and the next append gets the next seq | `test_OK_only_if_skip_and_raise_leave_the_chain_intact` |
| Predicate raises | **OK**. The exception propagates as its own type, not `ChainError`. The lock is released in `finally`, nothing is written, and the chain verifies. END's per-ticket `try` catches it. The rollback (N3) path is untouched because the predicate runs before any write | same |
| Concurrent writers: 3 processes with 180 appends, one writes `stop`; main appends `cond` only if there is no `stop` yet | **OK**. 36 conditional appends. Zero `cond` after the first `stop`. The chain verifies and all 180 notes are present | `test_OK_only_if_is_atomic_against_concurrent_writer_processes` |

## 4. `states()`

| Check | Result | Test |
|---|---|---|
| `unconfirmed` | **OK**. It replaces only RUNNING. A later kill or exit overrides it, and it never downgrades KILLED/EXECUTED | `test_OK_states_unconfirmed_and_refusal_rules_hide_no_outcome` |
| refusal only on unused rows | **OK**. A refusal after a spawn, exit or write is ignored, so RUNNING/EXECUTED stay visible. The only `refuse_ticket` writers are the redeem re-check (`executor.py:222`) and END. The redeem re-check fires on the first, consuming redeem, so the row is ISSUED and its refusal is never the one that gets suppressed. Replays raise before any record. No real outcome is hidden | same, plus RA-CL3c `test_OK_fold_does_not_hide_…` |
| any exit overrides a verified END kill | → N21 (a) | above |

## 5. Regression

- Full suite (3.12.3, xvfb, offscreen): **1301 passed, 4 failed, 5 skipped** (550 s). All 4 failures
  are the known baseline/flaky set: `test_audit_tiles::test_undecodable_tile_is_marked_failed`,
  `test_hwlab::test_doctor_hwbench_check`, `test_sstvdec::…iss_passes…` and
  `test_cl1_screen::test_up_down_drive_the_list_and_the_detail_follows`.
- **Denial diff** `4954cdf..e5a0e54 -- tests/`: only `tests/test_cl3_fix2.py` changed (+135/−2). The
  2 changed lines are in `test_b3_end_leaves_no_ticket_running_or_issued_even_without_confirmation`.
  The expectation moved from `kill`/KILLED to `unconfirmed`/UNCONFIRMED for an orphan with no logged
  start time, and a new `assert not any(kill by END)` was added. This is stricter and correct under
  N16. No denial is weakened.
- pyflakes (`chain.py engagement.py executor.py tests/test_cl3_fix2.py` and the three PoC files): clean.
- No renders, per the brief.

## New findings

| # | Sev | Finding | Fix direction |
|---|---|---|---|
| **N20** | **MED** | `verified_gone` is a leader-only check. A gated tool whose leader exits on SIGTERM while a group member ignores it leaves that member running. END records `kill` "orphan at END" `verified_gone: true` and the row reads KILLED. This is the N16 class at lower likelihood. It is not introduced here: `executor._kill_group` has the same semantics for hub-owned kills | In both `_kill_orphan` and `_kill_group`, once the leader is gone, probe `killpg(pgid, 0)`. A live pgid cannot be recycled as a new pid, so the probe is safe. SIGKILL the group if anything is left. Claim gone only when the probe fails with ESRCH. Otherwise record `unconfirmed` |
| N21 | LOW | After a rollover or slow child, the resumed child's post-close tail is untrue. Either FAILED "exit -15" overrides END's verified KILLED, or a `kill` of an already-exited process lands after its exit (a second kill for the ticket). The cause is the pre-existing pump/sweep race in `executor.py:288-314`, which END now exposes. The row at close is correct | Have `Handle.stop()` skip the record once the exit is recorded: set `_done` before or with the exit record, under one lock. In `states()`, have an exit with a signal code after a `kill` keep KILLED |
| N22 | LOW | For a zombie orphan (exited, unreaped) END's `unconfirmed` reason says "pid does not match the process logged at launch". It does match; the process already exited. The state is honest | Separate the cases in `_settle_tickets`: say "exited (zombie), not yet reaped" and record it as a kill/exit-unknown rather than a mismatch |
| N23 | LOW | `_same_process` does not exclude the hub's own process-group leader. With a forged keyed record END `os.kill`s the hub's launcher. A keyed forgery can also kill any same-uid process group. The key boundary covers both, so END adds no new capability | Refuse `pid == os.getpgrp()` and `pid == os.getppid()` in `_same_process`. Optionally require the spawn record's `wpid` to be a known bound child |
| N24 | LOW | END kills orphans one at a time: 2 s drain plus about 1.05 s per SIGTERM-ignoring orphan (6.31 s for 4), plus about 2 s per one that survives SIGKILL. This is beyond the owner-accepted 2 s wait, but bounded | TERM all matching orphans, wait once, then KILL the ones left |
| N25 | LOW | macOS: `_zombie()` is always False, so a matching zombie orphan costs about 2 s and is recorded "signalled, still alive" (UNCONFIRMED). Fail-safe. The brief's `ps`-based check is not on the tip. Not run (no Mac) | Read `kp_proc.p_stat == SZOMB` from the same `sysctl` buffer `_darwin_start` already fetches |

Known follow-ups N11, N12, N13, N15 and R1: unchanged by this fix and not re-rated.

## Stage → model
All stages ran on the session model (Opus 5.5). No subagents were used.
