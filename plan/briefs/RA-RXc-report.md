# RA-RXc — cold audit of RX round 3, branch `claude/project-thread-st3z1x`

Auditor: fresh session, Opus. Audited at **e3d9545** (RX-fix2 on top of merge 5567641 of main
@ c911825). Diff `origin/main...e3d9545`. Env: Python 3.13, PySide6 6.8.2.1, xvfb + offscreen,
**real nmap 7.94** (container is root, no IPv6 route). I read RX-report's RX-fix2 section only at
step 4.

## 1 · Merge sanity

| Check | Result | Evidence |
|---|---|---|
| Diff contains only RX files | **PASS** | `origin/main...HEAD`: executor.py, netpent.py, palisade_qt/recon.py, palisade_qt/runpane.py, wifipent.py, tests/test_netpent.py, tests/test_rx_recon_exec.py, plus RX reports and renders. Nothing else. |
| Gate files byte-identical to main | **PASS** | `git diff --quiet origin/main HEAD --` holds for engagement.py, chain.py, txguard.py, rfemit.py and opprofile.py. |
| executor.py differs only in the bounded reader | **PASS** | The only changes are `LINE_MAX`, `_lines()`, and `_pump` iterating `_lines(out)`. |
| recon.py: SCAN kept, no duplicates | **PASS** | The recon.py diff against main is additions only (RunPane, `monitor_iface`, `_wifi_extra`/`_net_extra`, `_spawner`, `prepare_run`, and the stop() pane kill). Main's `_kill_group`, the interruptible `_run_scan`, the iw→nmcli fallback, `WIFI_MODE`/`BLE_MODE` and the BLE worker are all present and appear once each. `tests/test_scan_live.py` passes. |
| install_head.sh | **PASS** | Byte-identical to main. Main's toolkit list already installs nmap (l.55/64) and aircrack-ng, hcxdumptool and hcxtools (l.83), so dropping RX's own loop loses nothing. |
| Toolkit #28 | **PASS** | `CATALOG_PROGRAMS` / `catalog_prepare` are unchanged from main and have no UI caller. `test_toolkit_scope.py` passes. |

## 2 · Attack on RX-fix2 (`-oN`, `-6`, family logic)

| Vector | Result | Evidence |
|---|---|---|
| `-oN` path as option injection | **PASS** | The UI builds the path in code: `<suite.DATA>/captures/nmap-<fixed action>-<UTC>.txt`, which is absolute. The engine refuses `out` when it is empty or starts with `-` (`-oX`, `--script=x`, `""`). |
| Write outside `<DATA>/captures` from the UI | **PASS** | The only caller is `ReconApp._net_extra`. `prepare_run` creates the directory only after the gate passes, and only when an argv token is under captures. In my live runs, every file appeared under `data/captures/`. |
| Write outside captures through the engine API | **Low (N5)** | `netpent.prepare(out=…)` accepts `/etc/cron.d/x`, `relative.txt`, `../../x` and `/dev/sda`. No UI path reaches this, and the path is chained at issue and spawn. wifipent's `out` behaves the same way (accepted in RA-RXb). |
| Program change | **PASS** | argv[0] is fixed per builder, and `ALLOWED_PROGRAMS` is enforced in `issue` (gate file unchanged). |
| Dual-stack name | **PASS** | Refused with both addresses named; nothing is issued. |
| IPv4-mapped `::ffff:10.0.0.5`, `::ffff:a00:5`, `0:0:0:0:0:ffff:10.0.0.5`, `::10.0.0.5`, `64:ff9b::a00:5`, `2002:a00:5::1` against a v4 scope `10.0.0.0/24` | **PASS (refused)** | `_ip_ok` compares address versions, so a mapped address never matches a v4 entry. A mapped address passes only when the operator typed a mapped v6 scope (`::ffff:10.0.0.0/120`), and then it gets `-6`. That is exactly the typed scope. |
| Scoped `fe80::1%wlan0` | **PASS** | It is in scope only under a v6 `fe80::/64` entry. argv `-6 fe80::1%wlan0` is a single non-option token. `fe80::1%-oNx`, `fe80::1%../../etc` and `fe80::1%a-b` are refused before issue. Accepted odd scope IDs (`fe80::1%a,b`, `fd00::5%x`) make nmap print `Failed to resolve` and scan 0 hosts. strace shows nss is consulted but **no** /etc/hosts or DNS access, so nothing out of scope is reached. The pane says NOTHING SCANNED. |
| v6 ranges / networks | **PASS** | `fd00::1-fd00::ff` becomes 8 exact CIDR blocks plus `-6`, each re-checked via `also=`. `fd00::/120` gets `-6`. |
| Saved-file claim honest | **PARTIAL (N4)** | The file exists and is the one nmap wrote, **unless** two runs of the same action start in the same UTC second. The filename has 1-second resolution and `-oN` truncates, so the second run silently overwrites the first run's evidence. Reproduced live: the `::1` and `fd00::5` portscans both wrote `nmap-portscan-20261117T141154Z.txt`, and the chain records two spawns naming the same file. `isfile()` also does not check that this run wrote the file (no mtime/size check against spawn time). |

## 3 · Earlier findings after the main merge

| ID | Status | Evidence | Test |
|---|---|---|---|
| RA-RXb N1 (IPv6 without `-6`) | **CLOSED** | `-6` is added when every address is v6 and omitted for v4. Mixed families are refused. Real nmap: `-sL -n -6 fd00::/126` lists 4 hosts. In the live RECON run, `fd00::5` and `::1` reach nmap with `-6`. With no v6 route here, nmap reports "No targets were specified", and the pane shows `NOTHING SCANNED · exit 0` instead of DONE. | `test_rx_fix2_ipv6_targets_get_dash_6`, `…_ipv4_targets_never_get_dash_6`, `…_dual_stack_name_is_refused…`, `…_nmap_that_scanned_nothing_is_not_done` |
| RA-RXb N2 (`-n` comment) | **OPEN (Low)** | The `_literal_targets` docstring still says "With -n … nmap itself never resolves anything". | — |
| RA-RXb N3 (kill reason "expired" after END) | **OPEN (pre-existing, gate file)** | Reproduced: END kill reason is `engagement 'job-END' has expired`. | — |
| H1 literal-only argv | **CLOSED** | Unchanged logic. Fuzz above: every accepted argv holds only `ipaddress` literals inside scope. | `test_rx_h1_*` (pass) |
| M1 bounded reader | **CLOSED** | executor `_lines` / RunPane deque are unchanged. | `test_rx_m1_*` (pass) |
| Kill paths | **CLOSED** | Live run with a **real-spawner** fake `nmap` on PATH (leader and child both ignore SIGTERM). For STOP, END, RECON close (`ReconApp.stop()`) and PANIC (`executor.kill_all`): both pids are dead afterwards. Chain is `spawn, kill(reason), exit`, with END adding `engagement.close` **after** them. Each kill record carries pid + wpid + ticket. Each kill takes 1.01–1.02 s (L1, accepted). | `test_rx_panic_kills_the_running_tool` (real hub `panic()`), END/STOP/close tests (pass) |
| Out-of-scope refusal before spawn | **CLOSED** | Every refusal in §2 returns from `prepare` before `issue`, so there is no authorize/issue record and no spawn. | `test_rx_h1_out_of_scope…`, `test_rx_a_ticket_whose_engagement_ended…` |
| **Real RECON path, real nmap, loopback** | **PASS** | Scope `127.0.0.0/8`. portscan on 127.0.0.1 gave `DONE · exit 0` and `[results saved: …]`, and the file exists. discover on `127.0.0.1-127.0.0.3` became `127.0.0.1/32 127.0.0.2/31` and found 3 hosts up. Chain for each run: `issue` → `spawn` (argv incl. `-oN` path) → `exit`. Renders `rx/rarxc-net-{dark,sun}.png` are 1280×720 and unclipped. |

## 4 · Regression

| Check | Result |
|---|---|
| `test_rx_recon_exec.py` + `test_netpent.py` + `test_scan_live.py` + `test_toolkit_scope.py` | 195 passed |
| pyflakes on every touched file | clean |
| Full suite | `2 failed, 1829 passed, 7 skipped, 7 errors` (919 s). All of these are baseline: `test_audit_tiles` undecodable tile, `test_hwlab` doctor, and 7 `test_shell` errors (no tkinter). cl1_screen passed. |
| Weakened assertions | **None.** Against main, the only edit is `test_netpent.py` (argv gains `-n`; `syn=True` pinned). That was justified in RA-RXb. Since da8cdd4, the only changed line in test_rx_recon_exec.py adds `-oN` to the helper's skip-next-token set. The path is an option value, not a target, so this is not weakened. |

## New findings

| ID | Sev | Finding | Fix |
|---|---|---|---|
| N4 | Medium (fails safe) | **Same-second scans overwrite each other's saved evidence.** `nmap-<action>-%Y%m%dT%H%M%SZ.txt` has 1-second resolution and `-oN` truncates. A quick re-run, such as a single-host scan or a NOTHING SCANNED retry, overwrites the earlier results. The chain then holds two runs pointing to one file, and the first pane's `[results saved]` claim becomes false. Reproduced live (see §2). The chain also stores no hash of the file at exit, so the evidence file is not pinned. | Make the name unique (ticket id or a sub-second/counter suffix, or `O_EXCL`-check before issue). Optionally chain the file's sha256 on exit. Add a test with two runs in the same second. |
| N5 | Low | The engine gate does not confine `out`. `netpent.prepare(out=…)` accepts any absolute or relative path outside captures (`/etc/cron.d/x`, `/dev/sda`), and nmap usually runs as root. No UI path reaches this. | Require `out` to resolve under `<DATA>/captures` in netpent (and wifipent). |
| N6 | Low | After `NOTHING SCANNED`, the pane still prints `[results saved: …]`. The file contains only nmap's header, which reads as if results exist. | For that state, say "log saved (no hosts scanned)". |
| — | note | `RunPane.saved` is not reset when a later run is refused or not installed, so it keeps the previous run's path. Nothing in the UI reads it yet. | Reset in `run()`. |

No gate is weakened. I found no out-of-scope spawn. Every kill is recorded before
`engagement.close`. The UI writes nothing outside `<DATA>/captures`. The gate files are identical
to main. SCAN and toolkit behaviour from main survive the merge.

**MERGE** (N4 should follow soon, before field use, because it loses evidence; the DEAUTH owner
decision from RA-RXb is still outstanding).
