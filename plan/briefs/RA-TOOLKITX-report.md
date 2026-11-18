# RA-TOOLKITX — cold re-audit report

Cluster: internal pentest toolkit (items 1–5) + installer
Branch: `claude/project-thread-o8b70k` @ `ee4f09c` (PR #31)
Base: `af52aa1` (merge of #30 + #27's RX-fix4)
Method: cold audit — read only the code (engines, gate, UI, installer, tests); author's
`plan/briefs/TOOLKIT-exec-report.md` deliberately NOT read. Claims verified by running the
tests and by independent adversarial probes in a real venv (PySide6 + pyqtgraph + numpy + flask
+ pytest, Python 3.13).

## Verification environment

- venv deps installed and import-clean.
- `QT_QPA_PLATFORM=offscreen xvfb-run -a python3 -m pytest -q`:
  - `tests/test_toolkit_exec.py` → **19 passed** (1.3s)
  - `tests/test_cl2_gates.py tests/test_cl1_screen.py` → **125 passed** (356s)
  - No pre-existing baseline failures in the targeted set (toolkit tests are new; the two gate
    suites are fully green on this branch).
- `pyflakes` on all changed modules → clean.
- `bash build_installer.sh` → assembles, markers OK, **`bash -n: OK`**.

## Focus-area findings (brief §"Focus the audit here")

| # | Claim under audit | Status | Evidence |
|---|---|---|---|
| 1 | No gate routed around; every ACTIVE tool reaches the executor only via `engagement.issue`, re-checked at spawn; per-module `ALLOWED_PROGRAMS` resolves correctly | **CLOSED** | All 5 engines call `engagement.issue` directly (frame[1] == caller module). `issue` reads `sys._getframe(1).f_globals["ALLOWED_PROGRAMS"]` (engagement.py:1052) and refuses via `program_allowed` (1008). Probed independently: path-prefixed binary, `sudo`, and non-declared program all refused; a cross-module `issue` call whose frame globals lack the program is refused ("nxc is not a program evil may run"). `nxc`/`netexec`, `testssl.sh`/`testssl`, `impacket-*` all bare + allowlisted. Allowlist is fail-safe when `ALLOWED_PROGRAMS` is absent (None → refused). Tests: `test_ad_enum_gate_and_argv`, `test_web_triage_gate_and_url`, `test_responder_poison_is_gated_and_scope_bound`, `test_discovery_*`. |
| 2 | Passive path is genuinely passive, cannot run an active tool, is lifecycle-registered, leaks no process | **CLOSED (one Low note, F-1)** | `PassiveRunPane._spawn_passive` (recon_tools.py:193) is fed only `capture.{pcap,live}_argv` and `responder.analyze_argv` (both validated builders) — no active-tool argv is wired to it. Spawns in its own session (`start_new_session=True`); `_kill_group` SIGTERM→SIGKILL on the group. Registered in `app._tool_panes`; stopped by `ReconApp.stop()` (via `run_panes()`) and `ReconApp.on_panic()` ("PANIC"). Offscreen the spawner refuses, so nothing spawns in CI. Test `test_capture_page_runs_a_passive_capture_and_logs_it` drives a real pcap through a fake spawner and asserts `passive.start`/`passive.exit` logged. |
| 3 | argv safety: BPF injection, option-injection targets/ifaces, no secret on AD argv, URL/port validation, scope-binding via pinned addresses | **CLOSED** | capture: filter tokens with a leading `-` refused, non-leading dash (`10.0.0.1-10.0.0.9`) allowed, pcap path confined to `<DATA>/captures` via `realpath` (subdir and `/etc/passwd` refused). netpent/adtools/webtriage/responder: `-`-leading target refused; iface validated by strict regex; hostname resolved via `pin_host` and argv built from the pinned IP (probed: `server.lan` → `https://10.0.0.5`, no second lookup). adtools argv carries no `-p`/password (test asserts). webtriage port 1–65535 enforced. Range targets expand to covering CIDRs and every block is scope-checked via `also` (probed: a range spilling past the /24 is refused). |
| 4 | Installer: capabilities + sudoers narrow, validated, best-effort, non-fatal; assembled installer passes `bash -n` | **CLOSED** | `setcap cap_net_raw,cap_net_admin` on tcpdump/arp-scan/netdiscover only; one `wireshark` group add; one `/etc/sudoers.d/palisade-responder` rule `"$USER ALL=(root) NOPASSWD: $PY3 $RESP_PY *"`, **validated with `visudo -cf` before `install`** and skipped if validation fails. Rule is scoped to the fixed interpreter+script; the `*` is trailing-args only (cannot become arbitrary python — first arg must be `Responder.py`). The `responder` shim keeps argv[0] a bare name so the gate still refuses `sudo …`. All steps guarded (`|| true`, `2>/dev/null`, `command -v` checks); none fatal. `build_installer.sh` assembles and `bash -n` passes. |
| 5 | `test_cl2_gates` allowlist additions are #27's passive own-host reads, correctly justified | **CLOSED** | Two entries added: `recon.py::_associated_bssid` (`iw dev` / `iw dev <sta> link`) and `recon.py::_default_gateway` (`ip -4 route show default`) — both fixed-argv, read-only reads of THIS host's own association/routing, no target contact, no TX. The stale-allowlist guard (`test…allowlist_entries_all_match_a_live_call`) passed, so both match live calls and neither is drift. |

## New findings (not in the 93)

**F-1 (Low / hygiene) — the "no spawn outside the executor" static proof does not scan
`palisade_qt/recon_tools.py`.**
`tests/test_cl2_gates.py::test_one_gate_no_spawn_or_device_write_outside_the_executor` walks a
fixed `GATED_MODULES` list (test_cl2_gates.py:1033). The new file `palisade_qt/recon_tools.py`,
which introduces a raw `subprocess.Popen` (`_spawn_passive`), is not in that list. The spawn is
correct and intentional (the passive runner, by design not the executor — the same class as
recon.py's allowlisted Wi-Fi/BLE scans) and is functionally covered by
`test_capture_page_runs_a_passive_capture_and_logs_it`. But the *static guard* that is supposed
to catch "someone added a raw spawn" will not examine future edits to this file, and there is no
reviewed-exception line pinning this spawn the way recon.py's passive spawns are pinned.
Fails safe (no behavioural impact); recommend adding `palisade_qt/recon_tools.py` to
`GATED_MODULES` with a `SPAWN_ALLOWLIST` entry for `_spawn_passive`. Does not block merge.

No Critical/High/Medium issues found. No gate bypass, no secret on any recorded argv, no
option/BPF/path injection reproduced, no passive-path escape to an active tool, no leaked
process on stop/close/PANIC in the tested paths.

## Regression check

The two full gate/screen suites the cluster touches (`test_cl2_gates`, `test_cl1_screen`) are
green on this branch — the frame-based `ALLOWED_PROGRAMS` change and the expanded
`netpent.ALLOWED_PROGRAMS` did not regress the existing single-gate / screen-structure proofs.
`pyflakes` clean across changed modules.

## Verdict

MERGE
