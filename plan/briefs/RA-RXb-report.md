# RA-RXb — cold re-audit of RX (round 2), branch `claude/project-thread-st3z1x`

Auditor: fresh session, Opus. Audited at **e941037** (RX-fix 2ffb2da + report). Diff
`origin/main...e941037`. Env: Python 3.13, PySide6 6.8.2.1, xvfb + offscreen, nmap 7.94 in the
sandbox (used only for `-sL -n` target parsing; no packets sent).

## Gate files

`engagement.py`, `chain.py`, `txguard.py`, `rfemit.py`, `opprofile.py` are **byte-identical to main**
(`git diff --quiet origin/main HEAD -- <file>`). `executor.py` differs **only** in the bounded
reader: `LINE_MAX = 4096`, new `_lines(out)` (`readline(LINE_MAX)` loop), and `_pump` iterating
`_lines(out)` instead of `out`. Redeem, recheck, spawn/exit/kill recording and `_kill_group` are
untouched.

## Round-1 findings (RA-RX) re-verified

| ID | Status | Evidence | Test |
|---|---|---|---|
| H1 nmap given non-literal targets / resolving | **CLOSED** | `netpent._literal_targets` (netpent.py:52-73) and `prepare` (:101-117). I fuzzed 33 targets against scope `10.0.0.0/24` (and again with v6 + 127/8 in scope). Every accepted target reaches argv only as `ipaddress` literals, each inside scope. `10.0.0.250-10.0.0.255` → `10.0.0.250/31 10.0.0.252/30`, `ip:`/`ip:host:` prefixes stripped. Refused before `issue`: reversed range, `10.0.0.250-255`, comma/space/tab lists, `\t-iL…`, `-iL`, octal/hex/int forms, Arabic digits, `*`, mixed v4-v6 range, `10.0.0.250-10.0.1.5` (the out-of-scope CIDR block is caught by `also=`), `/23`, host-bits-set `/24`. On every accepted argv, `nmap -sL` reports no resolve attempt. Hostnames: `pin_host` addresses only; partly-out-of-scope → refused; `-x.lab` → refused. | `test_rx_h1_nmap_only_ever_gets_address_literals_and_never_resolves` (7×3), `test_rx_h1_a_range_becomes_exactly_its_cidr_cover`, `test_rx_h1_out_of_scope_range_and_prefixed_targets_are_still_refused` |
| M1 unbounded line growth / GUI freeze | **CLOSED** | `y`×4096 with no newline, live RunPane: RSS flat at 149→153 MB over 12 s (round 1: +700 MB in 3 s), largest event-loop gap 0.26 s, STOP 0.05 s, state `STOPPED (operator STOP) · exit -15`, pane capped at 2000 blocks. Newline flood: gap 0.06 s, STOP 0.04 s, chain `spawn, kill, exit`. | `test_rx_m1_an_endless_line_is_read_in_bounded_pieces`, `test_rx_m1_the_pane_batches_and_truncates_a_flood` |
| L1 STOP/END block GUI ~1 s | **OPEN (accepted)** | Still 1.01–1.02 s on the GUI thread for a SIGTERM-ignoring tree (executor grace). RX-report records the owner's acceptance. | — |
| L2 monitor note stale | **CLOSED** | `_sync_monitor_note` runs on WIFI tab show and in `_wifi_extra` before each action. | `test_rx_l2_the_monitor_note_follows_the_adapter` |
| L3 pane header spacing / CLIENT placeholder | **PARTIAL** | Header spacing is fixed (12 px). The CLIENT placeholder `deauth only` still renders as `deauth …` at 1280×720 (see `rx/rarxb-wifi-sun.png`). This is cosmetic. | render only |
| L4 captures dir before gate | **CLOSED** | Created in `prepare_run` only after `prepare` succeeds, and only if argv points under it. | `test_rx_l4_a_refused_capture_creates_no_directory` |

## Fresh checks (brief steps 1–5)

| # | Check | Result | Evidence |
|---|---|---|---|
| 1 | main vs branch | **PASS** | main `recon.py:811` "nothing is spawned here", and there is no executor call in recon.py. Branch: spawn, streamed output and `spawn`/`exit` in the chain (`test_rx_in_scope_nmap_runs_streams_output_and_records_spawn_and_exit`, plus my live probes). |
| 2a | Ticketless / out-of-scope path to spawn | **PASS** | The only spawn is `RunPane.run` → `executor.start(ticket)`. The ticket comes only from `engagement.issue`. Every refusal in 2b happens in `netpent.prepare` before `issue`, so there is no authorize record and nothing is spawned. |
| 2b | IFACE / CH / CLIENT / capture path | **PASS** | `wifipent.prepare` regex `[A-Za-z0-9][A-Za-z0-9_.-]{0,14}` (no leading `-`, no `/`). CH is a QSpinBox int. CLIENT goes through `_mac` + scope. The capture path is built by code, and a leading `-` is refused. argv[0] is fixed per action, and `ALLOWED_PROGRAMS` is enforced in `issue`. |
| 2c | `-sT`/`-sS` | **PASS** | `_port_scan_argv(syn=)` toggles only that flag. The scope path is identical. |
| 2d | Ticket across END+START | **PASS** | `recheck` chain-id compare (engagement.py unchanged); `test_rx_a_ticket_whose_engagement_ended_before_run_is_refused_at_spawn`. |
| 2e | BLEPENT / PASSAUDIT / FORGE | **PASS** | `runner=None`, so they stay authorize-only (`test_rx_blepent_and_passaudit_stay_authorize_only`). FORGE is not in the diff. |
| 3a | END / STOP / close / PANIC kill whole group incl. SIGTERM-ignoring child | **PASS** | Leader and child both ignore SIGTERM. After each of END, STOP, `ReconApp.stop()` and `executor.kill_all("PANIC")`, neither is alive (/proc, zombies excluded). Chain order: `spawn, kill(reason), exit` (END adds `engagement.close` after). Real hub `panic()`: `test_rx_panic_kills_the_running_tool` passes. |
| 3b | Unterminated / flooding output | **PASS** | See M1. |
| 3c | Reader → GUI handoff | **PASS** | The reader thread only appends to a bounded deque, and the GUI drains it on a QTimer. Instrumented `_append`: 0 off-GUI-thread calls. |
| 3d | Exit / tail integrity | **PASS** | 40 instant-exit runs: the last output line is always shown, and `spawn` always comes before `exit`. 200 runs of `/bin/true` straight through `executor.start`: spawn/exit never out of order. |
| 4a | Missing binary / absent iface / non-root | **PASS (non-root not run live, as in round 1)** | Unchanged from round 1 (`test_rx_a_missing_tool_is_not_spawned_and_says_so`, `test_rx_unprivileged_portscan_is_a_connect_scan`). No `RUNNING` after exit anywhere in my probes. |
| 4b | Renders 1280×720 dark + sun, live | **PASS** | `rx/rarxb-{net,wifi}-{dark,sun}.png`: NET with a running nmap stand-in (pane RUNNING, STOP live), WIFI idle with IFACE/CH/CLIENT and the monitor note. Nothing clipped except the L3 placeholder. |
| 5a | RX tests + pyflakes | **PASS** | `test_rx_recon_exec.py` + `test_netpent.py`: 35 passed. pyflakes is clean on every touched file. |
| 5b | Full suite | **baseline** | `2 failed, 1521 passed, 7 skipped, 7 errors` (720 s). Failures are all baseline: test_audit_tiles, test_hwlab doctor, and 7 test_shell errors (no tkinter). The flaky cl1 tests passed this run. |
| 5c | Weakened assertions | **PASS** | The only edit to an existing test is `test_netpent.py`: the exact argv gains `-n`, and `syn=True` is pinned. Neither is weakened. |

## New findings

| ID | Sev | Finding | Fix |
|---|---|---|---|
| N1 | Medium (fails safe) | **IPv6 targets are never scanned, but the run reads as done.** An in-scope IPv6 address, range or network (or a hostname whose AAAA is in scope) is put in argv without `-6`. nmap prints `looks like an IPv6 target specification -- you have to use the -6 option`, scans 0 hosts and exits 0, so the pane shows `DONE · exit 0`. For a mixed v4+v6 hostname, only the v4 addresses get scanned. nmap's warning does appear in the pane, and nothing out of scope is touched. | Add `-6` when all addresses are v6. Refuse mixed families, or split them into two runs. Add a test asserting `-6` iff v6. |
| N2 | Low | The comment in `_literal_targets` says "With -n … nmap itself never resolves anything". That is wrong: `-n` disables only reverse DNS (`nmap -sL -n localhost` still resolves forward). The protection actually comes from the literal-only argv, which holds. | Correct the comment so nobody relies on `-n`. |
| N3 | Low (pre-existing, not RX) | After `E.end()`, the executor sweep's `kill` record gives the reason "engagement 'job' has **expired**" instead of "ended", because `check()` is unchanged in engagement.py. The kill is still recorded correctly. | Out of RX scope (gate file); note for a later cluster. |
| Flag | Owner | DEAUTH really transmits when txguard is armed and unlocked and both MACs are in scope. RX-report flags the conflict with the no-deauth rule, and it is still waiting on the owner's decision. | — |

No gate is weakened or bypassed, no out-of-scope spawn was found, every kill is recorded before
`engagement.close`, the gate files are identical to main (executor.py differs only in the bounded
reader), and BLE/PASSAUDIT/FORGE do not execute.

**MERGE** (the DEAUTH owner decision is still outstanding; N1 should follow up soon).
