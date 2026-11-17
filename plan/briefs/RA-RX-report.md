# RA-RX — cold audit of RX (RECON NET + Wi-Fi execution)

Auditor: fresh session, Opus. Branch `claude/project-thread-st3z1x` audited at **5288ae5**
(first pass at 6ac1b89; 5288ae5 adds one line in `GatedTool._authorize` and the suite section of
`RX-report.md`; I re-ran the RX tests and the probes at that head). Diff `origin/main...5288ae5`.
Env: Python 3.13, PySide6 6.8.2.1, xvfb + offscreen; nmap 7.94 installed in the sandbox only, for
target-parsing checks (`-sL -n`, no packets sent) and one loopback scan.

## Gate files

`engagement.py`, `executor.py`, `chain.py`, `txguard.py`, `rfemit.py`, `opprofile.py` are
**byte-identical to main** (`git diff --quiet origin/main 5288ae5 -- <file>` for each).

## Per-check table

| # | Check | Result | Evidence |
|---|---|---|---|
| 1 | Reproduce on main and branch | **PASS** | main 01afe7b: in-scope PORTSCAN → chain `open, authorize, issue`, spawner never called. Branch: spawner called with `nmap -sS -p 1-1024 10.0.0.5`, output streamed to the pane, chain `… issue, spawn(pid), exit(0)`. Real nmap on loopback (spawner=None): `DONE · exit 0`, real nmap output, chain state `EXECUTED`. |
| 2a | Ticketless path to `executor.start` / subprocess | **PASS** | Only `RunPane.run` → `executor.start(ticket)` (runpane.py:103). The only other subprocess in recon.py (:83) is the passive survey and is unchanged from main. |
| 2b | Out-of-scope literal targets (CIDR edges, /23, ranges, whitespace, leading `-`, `,`, tab+option, `0x…`, `10.5`, `10.0.0.05`, IPv6, mapped v6, `*`) | **PASS** | All refused before `issue` (probe output in the audit log). `10.0.0.255` and `/24` accepted (in scope). Hostnames are pinned to the checked addresses (`pin_host` + `also=`). |
| 2c | **Does nmap scan what the gate checked?** | **FAIL — H1** | An address range (`10.0.0.250-10.0.0.255`) and `ip:`/`host:`-prefixed literals pass the gate and go to nmap **verbatim**. nmap cannot parse them as addresses, so it sends the string to the system resolver (`Failed to resolve "10.0.0.250-10.0.0.255"`). Whatever the resolver returns is then scanned. PoC, run in a private mount namespace with a hosts entry standing in for a wildcard/NXDOMAIN-hijacking resolver: `nmap -sL -n 10.0.0.250-10.0.0.255` → `Nmap scan report for 10.0.0.250-10.0.0.255 (192.0.2.77)`, an address outside the scope. The executor's recheck checks the *string*, so it passes too. |
| 2d | IFACE / CH / CLIENT / capture path injection, program change | **PASS** | iface `-w`, `../x`, `wlan0 -w`, `wlan0\n`, `w;id`, 20 chars → refused by `wifipent.prepare`. CH is a QSpinBox, so always an int. CLIENT goes through `_mac` and scope (`ff:ff…` and out-of-scope MACs refused). The capture path is built by code under `<DATA>/captures`. argv[0] is fixed per action, and `ALLOWED_PROGRAMS` is still enforced by `engagement.issue`. |
| 2e | `-sT`/`-sS` alters only the scan type | **PASS** | `_port_scan_argv(..., syn=…)` changes the flag only, and the target/scope path is the same. |
| 2f | Ticket across END+START | **PASS** | `recheck` compares the chain id (engagement.py, unchanged). Pinned by `test_rx_a_ticket_whose_engagement_ended_before_run_is_refused_at_spawn`. |
| 2g | BLEPENT / PASSAUDIT / FORGE spawn? | **PASS** | The BLE/PASSAUDIT `GatedTool`s have `runner=None`, so they stay authorize-only. FORGE is not touched. Pinned by `test_rx_blepent_and_passaudit_stay_authorize_only`. |
| 3a | END kills group incl. SIGTERM-ignoring child; kill/exit before close | **PASS** | Leader starts a child that ignores SIGTERM. After `E.end()`, leader and child are gone (/proc state, not counting zombies). Chain: `spawn, kill, exit, engagement.close`. State `KILLED`. |
| 3b | PANIC (real hub `panic()`) | **PASS** | `test_rx_panic_kills_the_running_tool` (real `PalisadeHub.panic`) passes. The kill path is the same executor sweep as 3a. |
| 3c | STOP / closing RECON | **PASS** | Same SIGTERM-ignoring tree: both gone, one `kill` with reason `operator STOP` / `RECON closed`, then `exit`. |
| 3d | Flooding output | **PASS** | `print` loop at full speed for 3 s: the largest gap in the event loop is 0.14 s, the pane is capped at 2000 blocks, RSS grows 4 MB. STOP takes 0.02 s, and the exit is recorded. |
| 3e | **Output that never ends a line** | **FAIL — M1** | Writing `y`×4096 with no newline for 3 s: RSS grows **+700–780 MB** (the executor's `for line in out` buffers the unterminated line). STOP blocks the GUI thread **9–10 s**. The giant line then reaches `appendPlainText`, and the event loop does not tick at all for the following 2 s (15 s gap in the first run). Kill and exit are still recorded, so this fails safe. On the device, a longer run reaches the OOM killer, and the hub is the process holding the memory. |
| 3f | Reader thread → GUI is a queued signal | **PASS** | `RunPane._line` is a Signal emitted from the reader thread. Instrumented `_append`: 0 calls off the GUI thread. `finished` is emitted on the GUI thread (`_check` timer). |
| 4a | Missing binary | **PASS** | `NOT INSTALLED — nothing was run`, card says `NOT RUN: nmap is not installed`, no `spawn` record. At END the unused ticket settles as `REFUSED`. |
| 4b | Absent interface | **PASS** | `NOT RUN: interface wlan9mon is not present …`, nothing issued. The monitor-mode note is honest. |
| 4c | Non-root failure | **PARTIAL (not run)** | The sandbox runs as root, and I could not drop privileges for a live run. `_is_root()` → `-sT` is pinned by `test_rx_unprivileged_portscan_is_a_connect_scan`, and a non-zero exit shows `FAILED · exit N` (`test_rx_a_failing_tool_shows_its_real_exit_code`, and my probes showed real `-15` exits). No `RUNNING` after exit anywhere. |
| 4d | Renders 1280×720 dark + sun, live | **PASS** | NET (running nmap stand-in, STOP enabled) and WIFI (IFACE/CH/CLIENT, monitor note, idle pane), dark and sun. Nothing is clipped at 1280×720. Cosmetic: in the pane header, `OUTPUT` and the state label sit flush (`OUTPUT IDLE — …`), and the CLIENT placeholder is truncated (L3). |
| 5a | `tests/test_rx_recon_exec.py` + `test_netpent.py` + `test_palisade_qt.py` @5288ae5 | **PASS** | 143 passed. pyflakes clean on all touched files. |
| 5b | Full suite (at 6ac1b89; 5288ae5 changes one display line, and its affected file was re-run in 5a) | **as baseline + 1 flaky** | `4 failed, 1506 passed, 7 skipped, 7 errors`. Baseline: test_audit_tiles, test_hwlab doctor, and 7 test_shell errors (no tkinter). `test_palisade_qt::test_recon_gate…` was an RX regression, **fixed at 5288ae5** (passes). `test_cl1_screen::test_up_down_drive_the_list…` (PROWL): order-dependent. It passes alone, and it passed in two full `test_cl1_screen.py` runs (51 passed each). RX does not touch it. |
| 5c | Weakened assertions | **PASS** | The only edit to an existing test is `test_netpent.py`, which adds `syn=True` (root-independent, same assertion). The 5288ae5 fix restores the G5 `--bssid` display, and the test is unchanged. |

## New findings

| ID | Sev | Finding | Fix |
|---|---|---|---|
| **H1** | **High (blocker: out-of-scope scan)** | `netpent.prepare` passes an authorized *range* (`a.b.c.d-a.b.c.e`) or an `ip:`/`host:`-prefixed literal to nmap unchanged. nmap does not parse these as addresses and resolves them through DNS instead. With a wildcard search domain, NXDOMAIN-hijacking ISP resolver or hostile DNS, nmap actively scans whatever address comes back, outside the engagement scope, while the trail records an in-scope authorization. If nothing resolves, the run still shows `DONE · exit 0` with 0 hosts scanned, which is misleading. The bug was latent on main, where nothing executed; RX makes it live. | In `netpent.prepare`, hand nmap only literals nmap parses identically: strip `ip:`/`host:`, and turn a range into `ipaddress.summarize_address_range` CIDRs (or nmap octet syntax). Add a regression test asserting every target token in argv is an `ip_address`/`ip_network` literal, and add `-n` so nmap never resolves names. |
| M1 | Medium (fails safe) | Output with no line terminator grows memory without bound in the hub process (~250 MB/s here), and freezes the GUI for many seconds on STOP/exit (the 9–10 s block on STOP followed by a ≥2 s total stall). Kill and exit are still recorded. | Cap the line in RunPane before `appendPlainText` (e.g. 4 KB). The unbounded buffer itself is in `executor.Handle._pump` (a gate file), so bounding it there (chunked reads) needs the owner's approval. |
| L1 | Low | STOP / close / END run `Handle.stop` on the GUI thread: about 1 s for a SIGTERM-ignoring child, and up to about 6 s worst case (executor grace + `done.wait(3)`). | Accept, or move stop to a worker. |
| L2 | Low | The Wi-Fi monitor-mode note and the IFACE default are computed once when the page is built, so they go stale if an adapter is hot-plugged. | Refresh on page show. |
| L3 | Low | Pane header: the title and state label run together, and the CLIENT placeholder is truncated at 1280×720. | Spacing. |
| L4 | Low | `_wifi_extra` creates `<DATA>/captures` before the gate decides. | Create it after `prepare` succeeds. |
| Flag | Owner | DEAUTH now really transmits when txguard is armed and unlocked and both MACs are in scope (gated correctly). RX-report already flags the conflict with the project's no-deauth rule. It still needs the owner's decision before merge. | — |

**DO NOT MERGE.** Blocker: H1, an authorized in-scope address range reaches nmap as a hostname, so
the scanned host is chosen by DNS, not by the scope check.
