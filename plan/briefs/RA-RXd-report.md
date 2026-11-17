# RA-RXd — narrow cold audit of RX-fix3, branch `claude/project-thread-st3z1x`

Auditor: fresh session, Opus. Audited at **3cf6fd4** (RX-fix3). Scope:
`git diff 62c938a..HEAD -- netpent.py palisade_qt/recon.py palisade_qt/runpane.py tests/`
(+14/−4 netpent, +15/−4 recon, +17/−4 runpane, +44 tests). Env: Python 3.13, PySide6 6.8.2.1,
offscreen/xvfb, real nmap 7.94SVN at /usr/bin/nmap, container is root, no IPv6 route.

## 1 · Findings from RA-RXc / RA-RXb

| ID | Status | Evidence | Test (mutation-checked) |
|---|---|---|---|
| RA-RXc N4 (same-second evidence overwrite) | **CLOSED** | `recon._unique` (recon.py:47) builds `<stem>-<UTC second>-<6 hex of uuid4><ext>`. Both NET (`_net_extra`, l.850) and Wi-Fi (`_wifi_extra`, l.876) use it. **Live:** two real-nmap portscans of 127.0.0.1 in the same second (`…T143959Z-7b83fa.txt` and `…T143959Z-e2655d.txt`) went to two files, each 461 B with its own report. The chain has two spawn records with different `-oN` paths. | `test_rx_n4_two_scans_in_one_second_never_share_a_results_file`. It fails when `_unique` drops the suffix. |
| RA-RXc N5 (engine does not confine `out`) | **PARTIAL** | **netpent: closed.** `netpent.prepare` (netpent.py:115-121) refuses unless `dirname(realpath(out)) == realpath(DATA/captures)`, and refuses before `pin_host`/issue. **wifipent: still open.** The fix suggested "netpent (and wifipent)", but wifipent.py:80 is unchanged. With an engagement open and TX armed, `wifipent.prepare("pmkid", …, out="/etc/cron.d/x")` is accepted with argv `-o /etc/cron.d/x.pcapng` and `files={'/etc/cron.d/x.bssid': …}`. `rel` and `../../x` are accepted too. No UI path reaches this, because RECON passes `_unique(DATA/captures…)`. | `test_rx_n5_results_path_must_be_in_the_captures_folder` (netpent only). It fails when the realpath check is removed. There is no wifipent test. |
| RA-RXc N6 ("results saved" after NOTHING SCANNED) | **CLOSED** | runpane.py:161 prints `[nothing scanned — no results in …]`, sets `saved=None` and leaves the state `NOTHING SCANNED · exit 0`. **Live:** real nmap `-6 ::1` with scope `::1/128` (no v6 route) gave exactly that line. The 399 B header-only file exists and is not claimed as results. | `test_rx_n6_nothing_scanned_never_claims_results_saved`. It fails when the branch is disabled. |
| RA-RXc note (`RunPane.saved` not reset) | **CLOSED (untested)** | `self.saved = None` at the top of `run()` (runpane.py:111). | None. Removing the line leaves all 42 tests in the file green. Nothing reads `saved` yet. |
| RA-RXb N2 (`-n` docstring) | **CLOSED** | The `_literal_targets` docstring now says that literal-only input stops forward lookups and that `-n` stops reverse lookups. That matches the code. This is a comment-only change, so no regression test is possible. The `-n` argv itself is pinned by the existing `test_netpent.py` argv tests. | n/a (doc) |

## 2 · Attack on the diff

| Vector | Result | Evidence (ad-hoc script against `netpent.prepare`, target in scope) |
|---|---|---|
| Relative path (`x.txt`), `cap/../x.txt`, `cap/sub/x.txt`, `/etc/cron.d/x`, `/dev/sda` | **refused** | realpath dirname ≠ captures |
| Trailing slash `cap/`, `cap/.` | **refused** | dirname is the parent of captures |
| Symlink inside captures → `/etc/cron.d/evil` | **refused** | realpath follows the link (and also follows a dangling one) |
| Symlink inside captures → `cap/real.txt` | accepted | harmless, it stays inside captures |
| `cap/sub/../x`, `cap//x`, `cap/x.txt/`, an existing dir in captures, a name with `\n` | accepted | each normalises to a direct child of captures. The last three make nmap fail to open the file, which fails safe and leads to the `[results file NOT written]` line. A newline is a single argv token. |
| `DATA` is itself a symlink (e.g. a symlinked /home) | accepted, correct | both sides are realpath'd, so the paths RECON really builds are **not** refused |
| captures dir does not exist yet (first run) | accepted, correct | `realpath` of a missing path is the lexical path. Live first run under a fresh HOME worked. |
| **captures is itself a symlink to `/etc`** | **accepted** (Low, N7) | `cap = realpath(captures)` = `/etc`. Then the UI path `captures/nmap-…-xxxxxx.txt` and even engine `out="/etc/passwd"` pass, and root nmap's `-oN` truncates the target. This needs same-uid write access to `~/.local/share/uconsole-suite`. |
| TOCTOU: swap the accepted file for a symlink between prepare and spawn | possible (Low, part of N7) | the check is only at prepare. nmap `fopen`s and follows the link. The random 6-hex suffix makes a pre-planted link impractical, but an inotify race is still possible. Same-uid attacker. |
| `_unique` naming still readable | **PASS** | `nmap-portscan-20261117T143959Z-7b83fa.txt`, `wifi-pmkid-<UTC>-<hex>` (+ `.pcapng`/`.bssid`/`-01.cap`). Sorting by name is still chronological to the second. No code parses these names (grep). |
| Which program runs / scope check / kill-record path changed? | **No** | The diff touches only the `out` check (which runs before scope and returns before issue), the name builder, and the RunPane result/`saved` lines. argv[0] builders, `pin_host`/`_ip_ok`, executor stop/kill, and `ReconApp.stop()` are unchanged. The live chain is `engagement.open → authorize → issue → spawn → exit` per run and verifies (13 records intact). |
| Gate files vs `origin/main` | **PASS** | engagement.py, chain.py, txguard.py, rfemit.py, opprofile.py and install_head.sh are byte-identical. In executor.py only `LINE_MAX`, `_lines()` and `_pump` iterating `_lines(out)` differ. |

## 3 · Tests and live run

| Check | Result |
|---|---|
| `test_rx_recon_exec.py` + `test_netpent.py` + `test_palisade_qt.py` | **167 passed** |
| pyflakes on netpent.py, recon.py, runpane.py, test_rx_recon_exec.py | clean |
| Mutation: revert N4 / N5 / N6 individually | each one makes its own test fail (N6's message branch disabled → only `test_rx_n6_…` fails) |
| Full suite | `2 failed, 1832 passed, 7 skipped, 7 errors` (966 s). All of these are baseline: `test_audit_tiles` undecodable tile, `test_hwlab` doctor, and 7 `test_shell` errors (no tkinter). |
| **Real RECON, real nmap, loopback** (ReconApp with `QT_QPA_PLATFORM=minimal` so the offscreen spawn seam is off; scope `127.0.0.0/8`; fresh HOME) | portscan 127.0.0.1 ×2 in the same second gave `DONE · exit 0` and `[results saved: …]` for each, with two distinct files ("1024 closed tcp ports"). discover `127.0.0.1-127.0.0.3` became `127.0.0.1/32 127.0.0.2/31`, with "3 hosts up" in its file. All files are under `<DATA>/captures`. |

## New findings

| ID | Sev | Finding | Fix |
|---|---|---|---|
| N5-rest | Low | `wifipent.prepare(out=…)` is still unconfined: absolute paths, relative paths and `..` are accepted, and the executor writes `<out>.bssid`, where hcxdumptool/airodump then write as root. Engine API only, with no UI caller. This is the wifipent half of RA-RXc N5's fix. | Apply the same realpath check in wifipent and add a test. |
| N7 | Low | The captures check trusts `realpath(DATA/captures)`. If `captures` is a symlink (for example to `/etc`), any file in its target passes, including `out="/etc/passwd"`, and the check is not repeated at spawn (TOCTOU). This needs same-uid write access to the data dir. | Refuse when `DATA/captures` is a symlink (`os.path.islink`) or not owned by the user. Optionally open the file in prepare_run with `O_CREAT\|O_EXCL\|O_NOFOLLOW` before the spawn. |
| N8 | Low (hygiene) | The `saved = None` reset in `RunPane.run()` has no test (mutation survives). | Add a one-line assertion to an existing refused/not-installed test. |

No gate is weakened. No out-of-scope spawn was found. The diff does not change the program, the scope
check or the kill/record paths. The UI writes nothing outside `<DATA>/captures`. Both remaining
items are engine-API-only or need a local attacker with the operator's uid, and both fail safe for the UI path.

**MERGE** (RA-RXc N4/N6 and RA-RXb N2 are closed with tests. N5 is closed for netpent, and its wifipent half (N5-rest) is
Low and may follow. The DEAUTH owner decision from RA-RXb is still outstanding.)
