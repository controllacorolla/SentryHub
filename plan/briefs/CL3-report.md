# CL3 — evidence chain · implementer report (planner, cloud session, 2026-11-15)

**Branch:** `fix/cl3-evidence`, off `fix/cl2-gates` @ `93aaf27` (RA-CL2e MERGE). Must land after
PR #20. Written directly by the planner per the owner's 13:27 decision; the cold re-audit RA-CL3
decides the merge.
**Findings:** G6 G7 H9 E5 C2 (AUDIT_INDEX cluster CL3).

## What changed

| ID | Status | Fix (file) | Regression tests (`tests/test_cl3_evidence.py`) |
|---|---|---|---|
| **G7** chain not tamper-evident / durable / shared | CLOSED | New **`chain.py`**: one chain per engagement at `DATA/engagements/<id>.jsonl` + `<id>.key` (32 random bytes, 0600) + `<id>.head`. Every record hashed **whole**: `h = HMAC-SHA256(key, prev ‖ canonical_json(record−h))`. Open = load + verify + continue (no second genesis). Append = `flock` + re-sync + write + `fsync` + head update; **raises** `ChainError` on any failure. Records `engagement.open` (scope in force, operator, expiry), `engagement.close`, `authorize`, `refuse`, and from the executor `issue` / `spawn` / `exit` (real exit code) / `write` / `kill`. Wall `t`, `mono_ns`, `pid`, optional `gps_t` via `chain.set_time_source`. `sign_head_argv()` for gpg (tool-gated, not run). RECON/FORGE per-page `EvidenceChain()` instances removed. | `test_g7_rewriting_any_field_breaks_verification_poc` (operator, engagement, target, seq, t, action, authorization), `test_g7_dropping_the_last_record_is_detected_poc`, `test_g7_dropping_a_middle_record_is_detected`, `test_g7_unkeyed_reforge_fails_poc`, `test_g7_reopen_continues_the_chain_no_second_genesis_poc`, `test_g7_write_errors_raise_not_silent_poc`, `test_g7_records_executions_with_exit_code_and_kills`, `test_g7_open_records_scope_in_force_and_files_are_private`, `test_g7_one_chain_shared_by_recon_and_forge_pages`, `test_chain_is_shared_with_a_bound_child_process` (real child via `gatestate.child_env`, appends to the same chain, verifies) |
| **G6** authorized without a durable record | CLOSED | `engagement.start` creates the chain first; **no chain → no engagement**. `authorize_action` writes the `authorize` record **before** the action is added to the trail; a `ChainError` → `(False, "… no durable record, no authorization")`. `executor.issue` records `issue` **before** storing the ticket; failure → `TicketRefused`, nothing minted. Refusals are recorded (`refuse`) best-effort. Legacy `evidence_chain=` parameter accepted, ignored. | `test_g6_no_durable_record_no_authorization_poc`, `test_g6_engagement_cannot_start_without_a_chain`, `test_g6_ticket_issue_fails_closed_when_the_record_fails` |
| **H9** UI showed authorizations as if executed | CLOSED | `Chain.states()` → one row per authorization / ticket with its current state: **AUTHORIZED · ISSUED · RUNNING · EXECUTED (exit 0) · FAILED (exit n) · KILLED · REFUSED**. `engagement.chain_states()` / `chain_info()`. ENGAGEMENT panel trail now has TIME · STATE · ACTION · TARGET · RESULT, read from the durable chain, caption shows chain id + record count + VERIFIED / NOT VERIFIED. Panel widened to 1220×620 (fits 1280×720, no h-scroll). | `test_h9_authorized_and_executed_are_different_states_poc`, `test_h9_engagement_panel_shows_state_column_from_the_chain` |
| **C2** vault built `sh -c` strings | CLOSED | `Vault.lock_argv` / `unlock_argv` return argv **lists** joined by `Vault.run_pipeline()` (no shell). `tests/test_evidence.py::test_vault_commands_and_availability` updated to assert the new shape (the old assertion encoded the defect). | `test_c2_vault_uses_argv_lists_and_a_pipe_not_sh_c` |
| **E5** report generator had no callers | CLOSED (report) · OPEN (FDE) | `evidence.export_engagement_report()` writes `DATA/reports/<chain id>.html` from the **verified** chain (refuses if it does not verify). Wired to the ENGAGEMENT panel **EXPORT REPORT** button. Full-disk encryption on the device is a system/installer matter → **CL8 / owner**. | `test_e5_report_is_written_from_the_verified_chain` |
| TX without an engagement | — | Conducted bench / replay tickets (txguard only) are recorded to a per-process **session chain** `DATA/engagements/<ts>-<id>-session-<pid>.jsonl`, so TX is never unevidenced. | `test_tx_without_engagement_goes_to_a_session_chain` |

Also: `tests/conftest.py` gains an autouse fixture redirecting `suite.DATA` to a temp dir for every
test (every `engagement.start` now writes files; tests must not touch the developer's real data
dir), and `tests/test_engagement.py::test_action_logged_to_evidence_chain` now asserts against
the durable chain instead of the legacy in-memory one.

## Limits (say so, don't hide)

- The HMAC key is a 0600 file of the same user: the chain is tamper-evident against anything
  that cannot read that file, and against truncation/reordering/rewrite by anyone without it.
  The same user with the key can still re-forge; the head signature (`sign_head_argv`, gpg) is
  the stronger step and is **not automated** here (owner/tool-gated).
- Bound children append to the hub's chain by id with the same key file. Concurrency is
  `flock` + re-sync before each append; tested with one real child process.
- `gps_t` is recorded only when a time source has been registered; none is wired yet (CL5/CL6
  GPS work).

## Evidence

Fail-first: on the base commit (no `chain.py` wiring) **18 of 18** tests in `test_cl3_evidence.py`
fail; after: 18 pass. `tests/test_evidence.py`, `test_engagement.py`, all `test_cl2_*.py` pass
(295).

Suite here (Linux, **Python 3.13.18**, PySide6 6.12, xvfb, no `tkinter`):
```
$ QT_QPA_PLATFORM=offscreen xvfb-run -a python3 -m pytest -q tests \
    --deselect tests/test_palisade_qt.py::test_all_callsigns_build_in_both_themes \
    --deselect tests/test_audit_tiles.py::test_undecodable_tile_is_marked_failed --ignore=tests/test_shell.py
1188 passed, 4 skipped, 3 deselected in 441s
```
(the three exclusions are the same known non-cluster items as in CL2's report). pyflakes clean on
`chain.py engagement.py executor.py evidence.py palisade_qt/panels.py palisade_qt/recon.py
palisade_qt/forge.py tests/test_cl3_evidence.py`.

Renders: `plan/briefs/CL3-renders/render_engagement.py <out>` → ENGAGEMENT panel with
AUTHORIZED / EXECUTED / FAILED / REFUSED rows, dark + sun, exactly 1280×720, no h-scroll.
Stage → model: planner session (Claude Mythos 5.1), no subagents. **Not run:** Python 3.12 on the
Mac, the uConsole.

## Open questions (owner)

1. Automate head signing (gpg, timer) in v0.1, or leave manual?
2. Session-chain files for TX-only runs accumulate one per process; prune policy?

---

## CL3-fix — close RA-CL3 (planner, 2026-11-15)

| ID | Status | Fix | Test (`tests/test_cl3_fix.py`) |
|---|---|---|---|
| **B1** child executions off-chain | CLOSED | `chain.current()` now asks `engagement.current_chain_id()` — the id of the engagement in force in THIS process (own or hub-published) — and opens/caches by id (`chain.for_id`). No process-global set only by the hub. | `test_b1_bound_child_executions_land_in_the_engagement_chain` (real bound child: issue/spawn/exit with exit code in the engagement chain; no session chain created) |
| **B2** stale chain on rollover | CLOSED | `_active_chain()` re-derives the id every call; `end()` keeps the engagement routable (expired) while the executor kills + records, then closes. | `test_b2_child_follows_an_engagement_rollover` (child authorizes against alpha, then bravo, each in its own chain), `test_b2_hub_rollover_routes_executor_records_to_the_new_chain` |
| N1 unkeyed head | CLOSED | `.head` = `"<n> <h> <mac>"`, `mac = HMAC(key, id|n|h)`. | `test_n1_truncate_plus_head_rewrite_without_key_fails` |
| N2 id not bound | CLOSED | chain id is part of every record HMAC and the head MAC. | `test_n2_whole_chain_swap_fails_under_the_other_id` |
| N3 orphan line bricks chain | CLOSED | append rolls back to the previous length on any failure after the write (`ftruncate` + fsync). | `test_n3_failed_append_is_rolled_back_and_the_chain_still_verifies` |
| N4 unlocked readers | CLOSED | `_load_and_verify` takes `LOCK_SH`; writers `LOCK_EX`. | `test_n4_concurrent_readers_never_see_spurious_tamper` (3 readers × 150 appends, 0 spurious) |
| N5 pid overwritten | CLOSED | writer pid is `wpid`; a caller's `pid` (spawn/kill) is kept. | `test_n5_spawn_and_kill_records_carry_the_child_pid` |
| N6 key length / perms | CLOSED | key must be ≥ 32 bytes; jsonl + head + key must be 0600, owned, not symlinks. | `test_n6_short_key_and_loose_permissions_are_refused` |
| N7 start raises | CLOSED | `start()` catches any exception from chain creation → `(False, why)`; `canonical()` uses `surrogatepass`. | `test_n7_start_never_raises_on_an_unencodable_name` |
| N8 path traversal | CLOSED | `valid_id()` (`^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$`, no `..`) enforced in `Chain.__init__`, `for_id`, `exists`. | `test_n8_*` (2) |
| N9 refusals w/o engagement | CLOSED | `_record_soft` routes to the session chain when none is open. | covered by `_record_soft` path; prune policy still owner Q2 |
| N10 two rows / silent redeem refusal | CLOSED | `states()` folds a ticket into its AUTHORIZED row; `executor._redeem` records `refuse_ticket`. | `test_n10_one_row_per_action_and_redeem_refusals_are_visible` |
| H9 memory on tamper | CLOSED | `verify()` drops `records` on failure. | RA PoC `test_DEFECT_chain_states_served_from_memory_when_tampered` now passes as OK (not re-run here) |
| N11 h-scroll under stress | OPEN → follow-up | FeedTable `fit_viewport` exists on main (CL1-fix2); wiring the ENGAGEMENT trail to it is a UI change for RA-CL3b to confirm or CL4. | — |

Also merged `main` (CL1 + CL2) into the branch; the ENGAGEMENT panel keeps CL1's wrapped scope card
+ ≥3 evidence rows and gains CL3's STATE/RESULT columns (1220×640).

Fail-first: `tests/test_cl3_fix.py` on the previous tip → **16 failed, 3 passed**; after → 19 passed.
Suite here (Linux 3.13, xvfb, known exclusions as before): green except the two Linux-font strip
tests (`test_every_page_and_subtab_fits_1280x720`, `test_strip_fits_1280_with_a_huge_scope`: 1284 px —
pre-existing on `main`, see RA-MAIN-1). pyflakes clean.

---

## CL3-fix2 — close RA-CL3b B3 + N14 (planner thread, 2026-11-15)

Root cause, verified in code: `executor.record()` routed every record through `chain.current()`,
i.e. the engagement in force **at record time**. A bound child killed after the hub's END saw no
engagement and wrote kill/exit to a fresh session chain (B3); a bench ticket issued before START
wrote its exit into the new engagement's chain (N14). The prior reading (tie each ticket to the
chain it was issued under) was correct but not sufficient alone: the hub also closed the chain
before a child could report, and an issued-but-unused ticket stayed ISSUED forever.

| ID | Status | Fix | Test (`tests/test_cl3_fix2.py`) |
|---|---|---|---|
| **B3** END leaves a bound child's row RUNNING | CLOSED | (1) `executor.issue` stores the id of the chain its `issue` record went to (`entry["chain"]`); `refuse_ticket`/`spawn`/`write`/`kill`/`exit` go to `chain.for_id(that id)`; no fallback to another chain if it cannot be opened. (2) `engagement.end()` → `_settle_tickets()`: after publishing *expired*, waits ≤ `END_DRAIN_S` (2 s) for every spawned engagement ticket's `exit`, then records `kill` (by=`end`, "exit not confirmed") for spawned tickets with no kill, and `refuse_ticket` ("void") for never-used ones — all **before** `engagement.close`. Only issuer=`engagement` tickets (txguard bench tickets are not ended by END, so END writes nothing false about them). (3) the engagement ticket's re-check also requires `current_chain_id()` == the id at issue: a ticket/process from alpha is void under bravo, even with the same scope, even if a child misses the END→START gap. (4) `states()` folds a `refuse_ticket` for a known ticket into that action's row (REFUSED), instead of a second row beside a stale ISSUED. | `test_b3_end_while_a_bound_childs_process_runs_records_kill_and_exit_before_close` (the RA PoC inverted: real bound child, child-written kill + exit −15 before close, row KILLED, no session chain), `test_b3_end_leaves_no_ticket_running_or_issued_even_without_confirmation`, `test_b3_end_while_a_hub_process_runs_still_closes_last`, `test_b3_a_ticket_from_alpha_is_void_under_bravo`, `test_b3_a_rollover_the_child_never_saw_still_kills_the_process`, `test_b3_end_does_not_claim_to_kill_a_txguard_ticket_it_does_not_end`, `test_executor_never_falls_back_to_another_chain_when_the_bound_one_is_gone` |
| **N14** pre-START ticket exits into the engagement | CLOSED | same binding (1) | `test_n14_a_ticket_from_before_start_keeps_its_exit_in_the_session_chain` (RA PoC inverted) |
| N12, N13, N15, R1, N11 | OPEN (not in this fix) | out of scope of this brief; tracked from RA-CL3b | — |

Behaviour change to note: END now blocks up to 2 s **only** while a bound child's engagement
process has not yet reported its exit (typical: one 250 ms sweep + SIGTERM). A txguard bench
ticket issued during an engagement keeps running past END (unchanged gate semantics) and its exit
lands after `engagement.close` in the chain it was issued under.

Fail-first: `tests/test_cl3_fix2.py` on `ab209b7` → **7 failed, 1 passed** (the hub-process case was
already OK); after → 8 passed (5 repeat runs, no flake). RA-CL3b PoCs: both `test_DEFECT_end_while_a_bound_child…`
and `test_DEFECT_ticket_from_before_START…` now FAIL (= defect gone); every `OK_*`/`FIXED_*` still passes.

Full suite (Linux, Python 3.12.3, PySide6, tkinter, xvfb offscreen): **1293 passed, 4 failed, 5 skipped**.
The 4 are the known baseline (`test_audit_tiles::test_undecodable_tile_is_marked_failed`,
`test_hwlab::test_doctor_hwbench_check`, `test_sstvdec::…iss_passes…`, flaky
`test_cl1_screen::test_up_down_drive_the_list_and_the_detail_follows`). CL1/CL2/CL3 test files
re-run after the final edit: 119 passed (+ the flaky up/down). pyflakes clean on touched files.
