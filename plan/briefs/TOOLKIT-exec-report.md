# TOOLKIT (items 1–5 + installer) — report + backcheck

Branch `claude/project-thread-o8b70k`, PR #31, based on #30 (gated deauth) with #27's RX-fix4 merged
in (matches `demo/v0.1`). One branch, one PR. No gate routed around.

## Coverage vs the coordinator's scope (implemented / partial / missing · file · test)

| Ask | State | File(s) | Test |
|-----|-------|---------|------|
| **1** tcpdump/tshark passive capture, start/stop, pcap file | implemented | `capture.py`, `palisade_qt/recon_tools.py` (CAPTURE tab, `PassiveRunPane`) | `test_capture_*`, `test_capture_page_runs_a_passive_capture_and_logs_it` |
| 1 · logged, no gate | implemented (ungated, recorded to chain: `passive.start`/`passive.exit`) | `recon_tools.PassiveRunPane._record` | `..._logs_it` |
| 1 · in installer | implemented (tshark preseeded + added; tcpdump already) | `install_head.sh` [1b] | — |
| **2** arp-scan/nbtscan/netdiscover as RECON discovery | implemented | `netpent.discover_prepare`, NET tab `LAN DISCOVERY` card | `test_discovery_*` |
| 2 · engagement-gated (active, send packets) | implemented (scope-checked like nmap; iface/target option-injection refused) | `netpent.discover_prepare` → `engagement.issue` | `test_discovery_out_of_scope…`, `…iface_cannot_inject…` |
| 2 · in installer | implemented (all three already in [1b]; arp-scan gets caps) | `install_head.sh` [1b],[1c] | — |
| **3** Responder analyze (passive, ungated) | implemented | `responder.analyze_argv`, CAPTURE tab | `test_responder_analyze_is_passive_argv` |
| 3 · Responder poison (engagement-gated, engagement.py + opprofile.py) | implemented (scope-bound; opprofile enforced via engagement.start) | `responder.poison_prepare`, ENUM tab | `test_responder_poison_is_gated_and_scope_bound` |
| 3 · in installer | implemented (clone + launcher shim + NOPASSWD sudoers, owner card) | `install_head.sh` [1c] | — |
| **4** impacket/netexec/enum4linux-ng/smbmap AD/SMB enum, gated | implemented (null-session first pass; no secret on argv) | `adtools.py`, ENUM tab | `test_ad_enum_gate_and_argv`, `…never_puts_a_secret…` |
| 4 · in installer | implemented (smbmap+python3-impacket apt; netexec+enum4linux-ng pip best-effort) | `install_head.sh` [1b],[2c] | — |
| **5** testssl.sh/whatweb/nuclei web/TLS triage, gated | implemented (URL from pinned addr; nuclei `-duc`) | `webtriage.py`, ENUM tab | `test_web_triage_gate_and_url`, `…bad_port…` |
| 5 · in installer | implemented (whatweb+testssl.sh apt; nuclei go best-effort) | `install_head.sh` [1b],[2c] | — |
| **Installer** approved-but-missing: arp-scan, aircrack suite, gatttool/bluetoothctl, pm3, flashrom, openocd, can-utils | implemented (arp-scan/aircrack-ng/flashrom/openocd/can-utils in [1b]; bluez in [1]; pm3 = source note) | `install_head.sh` | — |
| Installer · hashcat stays catalog-only | respected (listed in [1b] apt but documented too-slow; no exec wiring) | — | — |
| "also worth having" as optional/catalog, no exec wiring | implemented (masscan/hydra/sqlmap/gobuster/ffuf/inspectrum/libnfc/exiftool in [1b]; mitmproxy/urh/bluing in [2c] notes) | `install_head.sh` | — |

## Deliberately NOT in this PR (noted, not dropped)
- **Credentialed** AD/SMB enum: a password would land on the argv, which `engagement.issue` records
  into the tamper-evident chain. Null-session only here; credentialed runs carry the secret out of
  band in a follow-up.
- **Responder RespondTo scoping** (answer only in-scope hosts): the engagement scope already refuses
  an unauthorized segment outright; fine-scoping Responder's reply list via a generated conf is a
  follow-up. Responder poisons the local segment it listens on — the scope is the authorization.
- Items 6–10 (Proxmark3, rtlamr/rtl_433, flashrom/sigrok, Kismet/hcxdumptool, bettercap) = next cluster.

## Device-notes backcheck (`plan/briefs/device-notes.md`)
- "everything needs to be scanable … no scan networks" → LAN host discovery (arp/nbt/netdiscover)
  gives RECON › NET a visible SCAN for networks under an engagement, and CAPTURE gives a passive
  packet view. Wi-Fi/BLE/frequency scans are prior clusters; RECON layout (font/collapsible, items
  11/13) is the UI thread's `fix/ui-polish`, untouched here.
- Privilege dead-ends: the tools that refuse to run as a normal user (tcpdump/tshark/arp-scan/
  netdiscover/Responder) are addressed by the installer's capabilities + Responder rule (owner's
  card, 2026-11-18), so the UI isn't a permission dead-end on the device.

## Suite
`QT_QPA_PLATFORM=offscreen xvfb-run -a python3 -m pytest -q tests` — result appended on the final
commit. Pre-existing baseline failures (main/branch, not this cluster): `test_audit_tiles::
test_undecodable_tile_is_marked_failed`, `test_hwlab::test_doctor_hwbench_check`, `test_shell.py`
errors (no tkinter in the container), the 3.13 `test_all_callsigns` segfault. `test_cl2_gates` was
red on the #27 merge (RX-fix4 passive reads un-allowlisted) and is **fixed** here.

## Final suite result (2026-11-18, container venv, Python 3.13)
`QT_QPA_PLATFORM=offscreen xvfb-run -a python3 -m pytest -q tests` →
**2 failed, 1874 passed, 7 skipped, 7 errors**. The 2 failures (`test_audit_tiles::
test_undecodable_tile_is_marked_failed`, `test_hwlab::test_doctor_hwbench_check`) and the 7
`test_shell` errors (no tkinter in the container) are the documented baseline, present on main.
**This cluster adds zero new failures.** `test_cl2_gates` is green (the #27 RX-fix4 allowlist + the
F-1 recon_tools entry). Cold audit RA-TOOLKITX: **MERGE** (one Low/hygiene finding F-1, now closed).
