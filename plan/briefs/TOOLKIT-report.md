# TOOLKIT — full pentest toolkit into scope (report)

Branch: `claude/project-thread-cp3fi6` (off `main` @ 22941ba).
Scope: owner decision 2026-11-17 — **every tool in the inventory is in scope; nothing is removed
without his authorization.** This cluster delivers scope docs + installer + gate catalog only. It
wires no execution (that is the executor cluster, PR #27+), touches no TX path or `txguard`, and
relaxes no gate default.

## What changed
| Area | File | Change |
|---|---|---|
| Scope matrix | `FEATURE_MAP.md` | New "Tool scope" appendix: full per-tool matrix (page, passive/active, hardware, verified arm64 install source) for ~55 tools, grouped network/web/Wi-Fi/BLE/RF/NFC/bus/OSINT, + the two guardrail conflicts flagged. |
| Backlog | `plan/BACKLOG.md` | Standing scope rule + landing order + hardware-needed list + the flagged owner calls. |
| Installer | `install_head.sh` | `[1b/8]` optional apt block (33 plain-apt tools via `safe_apt`, best-effort, never fatal); `[2c/8]` documented pip/go/cargo/source list (not auto-built). `tshark` deliberately omitted (debconf prompt). |
| Gate catalog | `netpent.py` | `CATALOG_PROGRAMS` (active network + web enumerators) added to `ALLOWED_PROGRAMS`; `catalog_prepare()` routes through `engagement.issue` (kind=ip, host pinned). |
| Gate catalog | `blepent.py` | `btlejack` catalogued; `catalog_prepare()` (kind=mac). |
| Gate catalog | `proxmark.py` | `mfoc`/`mfcuk` catalogued; `catalog_prepare()` label-only (kind=label). |
| Tests | `tests/test_toolkit_scope.py` | Refusal path per catalogued program (no engagement + out of scope), allowlist wiring, emitter double-gate, label-only binding. |

## Install-source verification (Debian trixie arm64, 2026-11-17)
Checked against the trixie `Packages` + `Contents-arm64`/`Contents-all` index and PyPI /
proxy.golang.org / crates.io. In apt main ✓: nmap, arp-scan, tcpdump, tshark, nbtscan,
netdiscover, masscan, smbmap, python3-impacket, hydra, bettercap, sqlmap, whatweb, gobuster, ffuf,
testssl.sh, aircrack-ng, hcxdumptool, hcxtools, gqrx-sdr, inspectrum, rtl-433, dsdcc, libnfc-bin,
libnfc-examples, mfoc, mfcuk, sigrok-cli, pulseview, flashrom, openocd, picocom, minicom,
can-utils, libimage-exiftool-perl, cewl, hashcat, python3-scapy. non-free: nikto. Not in apt →
pip: mitmproxy, netexec, enum4linux-ng, urh, btlejack, bluing(⚠). go: rtlamr, nuclei. cargo/GitHub:
feroxbuster. Kismet: official apt repo (trixie arm64 confirmed present). Source build: Responder,
OP25, dsd-fme, Proxmark3 client.

## Findings per section
| Section | State | Note |
|---|---|---|
| Scope docs | CLOSED | Matrix + backlog written; passive/active + hardware + source per tool. |
| Installer optional apt | CLOSED | `safe_apt` best-effort; assembled installer `bash -n` OK, payload intact (2 B64EOF). |
| Installer source/pip/go step | CLOSED | Documented, not auto-built. |
| Gate catalog netpent | CLOSED | `catalog_prepare` gated; refusal tests per program. |
| Gate catalog blepent | CLOSED | `btlejack` gated (+ txguard as emitter). |
| Gate catalog proxmark | CLOSED | mfoc/mfcuk label-only, gated. |

## Deliberately NOT done (flagged for the owner — his call, per the brief)
1. **Deauth conflict** — `wifipent` approves a capped `aireplay-ng --deauth`; CLAUDE.md forbids
   deauth/jamming. Left as-is. Keep the capped deauth or drop it?
2. **Responder poisoning** — broadcast-scope, un-targetable (same class as deauth). Catalogued as
   analyze/passive only; **no poisoning builder written**. Responder is also not in apt (source
   build). Owner's call before it gets an active builder.
3. Hardware still needed (no buy): USB monitor-mode Wi-Fi adapter, PN532, Proxmark3, SocketCAN
   adapter, SPI programmer, JTAG/SWD adapter, logic analyzer, micro:bit.

## Tests
`tests/test_toolkit_scope.py`: 86 passed (targeted run).
Full suite (`QT_QPA_PLATFORM=offscreen python3 -m pytest -q tests`, PySide6/numpy/pyqtgraph/flask
installed via pip in the container; tkinter still absent): `3 failed, 1783 passed, 18 skipped in 788s`. The 3 failures are the documented baseline (test_audit_tiles undecodable tile, test_hwlab doctor_hwbench, test_sstvdec skyfield) — all in modules this cluster does not touch. `tests/test_toolkit_scope.py` = 86 passed.

Baseline failures not from this cluster (per handoff): `test_audit_tiles` undecodable tile,
`test_hwlab` doctor_hwbench, `test_sstvdec` skyfield, flaky `test_cl1_fix2` ack_all, and
`test_shell`/Qt modules where tkinter is unavailable.

## Next
Cold audit `RA-TOOLKIT` (Opus subagent). On MERGE → draft PR off main, tell the owner one line.
Executor wiring per tool is the following cluster.
