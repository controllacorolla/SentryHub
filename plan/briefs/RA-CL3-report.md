# RA-CL3 — cold re-audit of CL3 (`fix/cl3-evidence` @ 3208b70)

**Verdict: DO NOT MERGE.** Bound child processes (the Hub's normal mode: every app is a child)
write their executions to a private per-child session chain, so the engagement chain shows only
AUTHORIZED for them (B1). A long-lived child writes the next engagement's authorizations into the
previous engagement's chain (B2). Both make the engagement trail lossy, and B2 is an
authorization with no record in its own engagement's chain.

Auditor: fresh headless session, Claude Opus 5.5 (session model, all verdicts). No subagents.
Python **3.12.13** (Mac, venv: PySide6 6.12, pyqtgraph, flask, numpy, tkinter), Qt offscreen.
PoCs: `plan/briefs/RA-CL3-poc/poc_ra_cl3.py` (`SUITE=<checkout> pytest -q poc_ra_cl3.py` → 39
passed. `test_OK_*` = the audit claim holds, `test_DEFECT_*` = the defect reproduces.)

## Blockers

| # | Sev | Finding | Evidence | PoC |
|---|---|---|---|---|
| **B1** | HIGH (blocks) | **A bound child's executions never reach the engagement chain.** `engagement.authorize_action` finds the hub's chain by id (`engagement.py` `_active_chain`). `executor.record` → `chain.record` → `chain.current()` doesn't: `_OPEN` is only set by `engagement.start` in the hub, so the child creates its own `…-session-<pid>.jsonl` (`chain.py:286-295`). `issue`/`spawn`/`exit`/`kill` from every Hub-launched app go there. The engagement chain shows `AUTHORIZED` forever and never shows EXECUTED/FAILED/KILLED, so H9 doesn't work on the device. The CL3 test only covers `authorize_action` in the child. | child: `ISSUE True … EXIT 0 … CHILDCHAIN 2026…-session-12985`; engagement chain child events: `['authorize']` | `test_DEFECT_bound_child_executions_go_to_a_private_session_chain` |
| **B2** | HIGH (blocks) | **Stale chain after engagement rollover.** `_active_chain` returns the cached `_CHAIN["obj"]` without checking it against `_eng()["chain"]`. If the hub ENDs alpha and STARTs bravo, a running child authorizes against bravo's scope and records `authorize … engagement='bravo'` in **alpha's** chain. Bravo's chain has no record of that authorization (G6 regressed for children). | child: `B (True, "…(engagement 'bravo')")`; record in alpha jsonl, none in bravo | `test_DEFECT_bound_child_stale_chain_after_engagement_rollover` |

Fix direction (planner's call): route `chain.current()` through the same lookup as `_active_chain`, keyed on the *current* `_eng()["chain"]` id, and drop the cache when the id changes. Add regression tests that use a real bound child for `E.issue` + `executor.run` (exit code in the engagement chain) and for a rollover between two authorizes.

## Per-ID verdicts

| ID | Verdict | Evidence (file:line / PoC) |
|---|---|---|
| **G7** rewrite any field | CLOSED | operator, engagement, seq, target, action, binding, authorization, t, pid, exit_code, argv each → `ChainError` (`test_OK_rewrite_field_fails[*]`, `test_OK_exit_code_and_argv_rewrite_fails`) |
| G7 drop middle / delete or edit `.head` | CLOSED | `test_OK_drop_last_and_middle_and_head_delete` |
| G7 drop last | **PARTIAL** | Truncating the jsonl alone is detected. But `.head` is an unkeyed copy of the last `h`, and that value is printed in the jsonl. Truncating N records and writing the new last `h` into `.head` **verifies with no key** (`chain.py:155-162`). Anyone who can write the 0600 jsonl can also do this, so the head only stops a writer who can't touch `.head`. The report's limit ("tamper-evident against … truncation by anyone without [the key]") is wrong. → N1 | `test_DEFECT_truncate_plus_head_rewrite_without_key_verifies` |
| G7 re-forge with a guessed key | CLOSED | `test_OK_reforge_with_guessed_key_fails` |
| G7 swap two chains' files | PARTIAL | Swapping only the jsonl fails. Swapping jsonl+key+head together verifies under the other id: records don't include the chain id. → N2 | `test_DEFECT_swap_two_chains_files_…`, `test_OK_swap_only_jsonl_fails` |
| G7 restart → no second genesis | CLOSED | `test_OK_restart_no_second_genesis` (`Chain.create` on an existing id raises) |
| G7 concurrent appends, 2+ processes | CLOSED (writers) | 4 child processes + hub, 125 authorizes, verifies. `test_OK_concurrent_appends_from_4_processes_verify`. Readers: see N4 |
| G7 one chain RECON/FORGE | CLOSED | per-page `EvidenceChain()` removed (`recon.py:308`, `forge.py:432`) |
| G7 one chain with a bound child | **OPEN** | B1, B2 |
| G6 write failure → gate refuses, nothing minted | CLOSED | fsync ENOSPC → `authorize_action` `(False, "…no durable record…")`, not in `actions()`; `executor.issue` → `TicketRefused`, `_ISSUED` unchanged. `test_OK_write_failure_refuses_authorize_and_issue`. Caveat → N3 |
| G6 for children | **OPEN** | B2 |
| refusals / executions / exit code / kills present | CLOSED (hub process) | `refuse`, `spawn`, `kill`, `exit exit_code=1` all present. `test_OK_refusal_execution_kill_recorded`. Pid content wrong → N5 |
| END while running | CLOSED | order `… spawn, kill, exit, engagement.close`. Kill and exit land in the engagement chain before close. `test_DEFECT_end_while_running_kill_record_placement` (named DEFECT, but it **passes as OK**) |
| **H9** states from the chain | **PARTIAL** | Hub-process states are correct (AUTHORIZED / EXECUTED exit 0 / FAILED exit 2 / KILLED / REFUSED). Two gaps: (a) on a tampered file, `chain_states()` shows the **cached in-memory rows** from the last good load. `verify()` fails without clearing `self.records` (`chain.py:131-163`, `engagement.py chain_states`). This breaks "never from memory". (b) Child executions are missing (B1). | `test_DEFECT_chain_states_served_from_memory_when_tampered`; `RA-CL3-poc/engagement-dark-tampered-live.png` (6 rows under NOT VERIFIED) |
| H9 render 1280×720 dark+sun | PARTIAL | Normal content: panel 1220×620 at (30,70), fits, no h-scroll (`engagement-{dark,sun}-live.png`). Stress (long target, 36 rows): **h-scroll appears** (max 4), RESULT column off-screen, right-aligned IP targets clipped to blank (`engagement-sun-tampered-stress-live.png`). The caption cuts the reason mid-word, but "NOT VERIFIED" stays visible. |
| H9 caption NOT VERIFIED on tamper | CLOSED | caption `… — NOT VERIFIED: chain …: record 2 fails its H…` |
| **C2** no `sh -c` in `evidence.py` | CLOSED | `test_OK_no_sh_c_in_evidence`; `test_c2_vault_…`. `lock_argv`/`unlock_argv`/`run_pipeline` have no callers outside tests |
| **E5** report from a verified chain only | CLOSED (report) · OPEN (FDE → CL8) | writes on a verified chain, raises on a tampered one and creates no output dir. HTML-escapes chain strings (`<script>` not reflected). `test_OK_report_refuses_tampered_and_writes_verified`, `test_report_html_escapes_chain_strings` |

## Design attack (step 2)

| Item | Result |
|---|---|
| key/head/jsonl perms | 0600 each, dir 0700 at create (`test_OK_permissions`). `open()` checks only the key's mode. A world-writable jsonl/head (0666) opens and verifies without complaint → N6 |
| `.key` < 32 bytes | 16–31 bytes accepted (`chain.py:114`, `len < 16`) → N6 |
| world-readable key | refused (`test_OK_world_readable_key_refused`) |
| symlink / pre-existing file at create | live symlink or existing file → `ChainError`. Dangling symlink → `os.replace` swaps the link, target untouched (`test_symlink_at_chain_path_on_create`). `.head` isn't pre-checked but is atomically replaced. OK |
| TOCTOU verify→append | none for writers: re-sync and append both happen under `flock` (`chain.py:182-213`). Readers don't take the lock → N4 |
| same-user attacker **with the key** | Can rewrite, re-key, truncate, swap, or delete any chain and its head, and nothing on the device detects it. Only an off-device anchor stops this (signed head shipped elsewhere; `sign_head_argv` is unused). Without the key, a same-user writer can still truncate the tail (N1) and swap whole chains (N2). |
| `canonical()` collisions | Key order, floats, NaN, NFC≠NFD, and `\n \r   \u0085 \0` in values all round-trip and verify. `default=str` maps `b"ab"` ≡ `"b'ab'"` and tuple ≡ list: lossy typing, not a forgery. Lone surrogates (`surrogateescape` argv/filenames) → `UnicodeEncodeError`; mixed int/str dict keys → `TypeError`. Neither is a `ChainError`. `authorize_action`/`executor.record` catch `Exception` (fail closed). `engagement.start` doesn't → N7 |
| newlines in user strings | JSON-escaped; `bytes.splitlines` splits only on `\n`/`\r`. Verified |
| chain id with `/` or `..` | `Chain.open(cid)` joins `cid` unvalidated. A shared-state engagement with `chain: "../../x"` opens a chain outside `DATA/engagements` (`test_DEFECT_chain_id_path_traversal_from_shared_state`). Exploiting it needs a forged gate-state file that passes the nonce check (same user) → N8 |
| session chain, TX-only tickets | Recorded (`issue` in `…-session-<pid>`). Never closed. One file per process, which per B1 includes **every bound child**, so they pile up fast. Refusals with no engagement are not recorded anywhere → N9 |

## New findings (not in the audit)

| # | Sev | Finding | PoC / ref |
|---|---|---|---|
| B1 | HIGH | bound-child executions go to a private session chain | above |
| B2 | HIGH | stale chain cache across engagement rollover | above |
| N1 | MED | `.head` unkeyed → tail truncation verifies without the key. Fix: HMAC the head as `(n, h)` with the key. The real fix is the off-device signed head (owner Q1) | `test_DEFECT_truncate_plus_head_rewrite_without_key_verifies` |
| N2 | LOW | chain id not bound into the HMAC → whole-chain swap verifies under the wrong id | `test_DEFECT_swap_two_chains_files_…` |
| N3 | MED | an append that fails **after** the line is written (fsync / head replace) leaves an orphan line → the chain never verifies again. Every later authorize refuses, the report refuses, there is no repair path. It fails closed, but one ENOSPC bricks the engagement. The orphan is an `authorize` record for an action the gate refused | `test_DEFECT_failed_append_bricks_the_chain_permanently` |
| N4 | MED | `open()`/`verify()` read without `flock` → readers racing a writer see `head ≠ last`. 202 spurious failures in one 300-append run. Effects: the panel flashes NOT VERIFIED, and a child's `_active_chain` returns None so a valid authorize is refused | `test_DEFECT_unlocked_reader_sees_spurious_tamper` |
| N5 | MED | `record()` drops any field already in the base record, so `spawn`/`kill` `pid=proc.pid` is replaced by the **hub's** pid (`chain.py:199-201`). The trail never records the spawned or killed PID, and the panel's RUNNING `pid N` names the hub | `test_DEFECT_spawn_and_kill_records_lose_the_child_pid` |
| N6 | LOW | key accepted at 16–31 bytes; jsonl/head mode and owner unchecked on open | `test_DEFECT_short_key_accepted_and_jsonl_perms_unchecked` |
| N7 | LOW | `engagement.start` raises `UnicodeEncodeError` (not `(False, why)`) on a surrogate in the name. No engagement starts (fails closed) | `test_DEFECT_start_raises_on_unencodable_name` |
| N8 | LOW | chain id not validated (`/`, `..`) in `Chain.open` | `test_DEFECT_chain_id_path_traversal_from_shared_state` |
| N9 | LOW | refusals without an engagement are not recorded. Session chains never close and have no prune policy (owner Q2) | `test_DEFECT_refusals_without_engagement_are_not_recorded` |
| N10 | LOW | H9 view: the `authorize` row never links to its ticket row, so every executed action shows two rows (AUTHORIZED + EXECUTED). A ticket refused at redeem/spawn (`executor._redeem` raises) isn't recorded and stays ISSUED | `test_OK_refusal_execution_kill_recorded` output |
| N11 | LOW | ENGAGEMENT trail gets an h-scroll under long targets / many rows. RESULT column goes off-screen and right-aligned targets clip to blank | `engagement-sun-tampered-stress-live.png` |

Merge needs B1 and B2. N3, N4 and N5 are trail-correctness bugs and cheap to fix in the same pass (recommended). N1, N2 and N6–N11 can follow up.

## Regression (step 4)

- `tests/test_cl3_evidence.py test_engagement.py test_evidence.py test_cl2_*.py`: **295 passed** (Python 3.12.13).
- Full suite (Python 3.12.13, Qt offscreen, Mac, no xvfb): **1187 passed, 3 failed, 14 skipped** (254 s). The 3 failures (`test_audit_tiles::test_undecodable_tile_is_marked_failed`, `test_hwlab::test_doctor_hwbench_check`, `test_sstvdec::test_iss_passes_use_their_own_tle_and_leave_weather_cache_alone`) **fail identically on base `93aaf27`**. They are pre-existing and outside CL3.
- pyflakes (`chain.py engagement.py executor.py evidence.py palisade_qt/panels.py palisade_qt/recon.py palisade_qt/forge.py tests/test_cl3_evidence.py`): clean (no output)
- Denial assertions vs `93aaf27`: none weakened. The two changed tests swap legacy-chain/`sh -c`-string assertions for durable-chain/argv-list ones of equal or greater strength.

## Stage → model
All stages ran on the session model (Opus 5.5), with no subagents (token budget). Renders: dark + sun live, a tampered pass, and one stress pass.

## Open questions (owner)
1. (= CL3 Q1) Automate the off-device signed head? Without it, a same-user attacker can rewrite everything.
2. (= CL3 Q2) Prune policy for session chains. This matters more now: per B1, if children keep session chains, there is one per app launch.
