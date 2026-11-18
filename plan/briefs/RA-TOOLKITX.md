# RA-TOOLKITX — cold audit brief: internal pentest toolkit (items 1–5) + installer

Audit the cluster on branch **`claude/project-thread-o8b70k`** (PR #31), based on `#30` with `#27`'s
RX-fix4 merged in. Follow `plan/audit/REAUDIT_PROMPT.md`. This is a cold audit: read only the code,
not the author's notes. Verdict line: `MERGE` or `DO NOT MERGE`.

## What the cluster does
Wires items 1–5 of the internal-pentest gap analysis into RECON and the installer.

New engines (pure command-building + gating, unit-testable):
- `capture.py` — tcpdump/tshark passive capture argv. **Ungated** by design (passive), but runs are
  logged. Assert the built argv can't smuggle a tcpdump `-z` postrotate command or a tshark option
  out of the BPF filter box, and that the pcap path is confined to `<DATA>/captures`.
- `netpent.discover_prepare` — arp-scan/nbtscan/netdiscover. **Engagement-gated** exactly like
  `netpent.prepare` (target checked as one IP interval; iface/target option-injection refused).
- `responder.py` — `analyze_argv` (passive `-A`) and `poison_prepare` (**engagement-gated**,
  scope-bound to the named segment).
- `adtools.py` — smbmap/netexec/enum4linux-ng/impacket, **engagement-gated**, null-session only
  (assert NO credential/secret can reach the recorded argv).
- `webtriage.py` — testssl/whatweb/nuclei, **engagement-gated** (URL built from the pinned,
  scope-checked address — no second DNS lookup handed to the tool).

UI (`palisade_qt/recon_tools.py`, `palisade_qt/recon.py`): RECON gains CAPTURE + ENUM sub-tabs and a
LAN DISCOVERY card on NET. Active tools reuse `GatedTool` + `RunPane` → the **executor** (ticket,
gate re-checked at spawn, killed on END/PANIC/scope-change). Passive tools run through a new
`PassiveRunPane` (NOT the executor — no gate to re-check) that is lifecycle-managed and stopped on
close/PANIC, logging `passive.start`/`passive.exit`.

Installer (`install_head.sh`): tshark (preseeded), `cap_net_raw,cap_net_admin` on
tcpdump/arp-scan/netdiscover, a `wireshark` group add, a Responder launcher shim + one NOPASSWD
sudoers rule scoped to exactly that launcher (owner-authorized "Capabilities + Responder rule",
2026-11-18), and best-effort pip/go installs for netexec/enum4linux-ng/nuclei.

## Focus the audit here
1. **No gate routed around.** Every ACTIVE tool must reach the executor only via `engagement.issue`
   (so argv[0] is an allowlisted bare program, re-checked at spawn). Confirm `adtools.ALLOWED_PROGRAMS`,
   `webtriage.ALLOWED_PROGRAMS`, `responder.ALLOWED_PROGRAMS`, and netpent's expanded list are correct
   and that the frame-based `ALLOWED_PROGRAMS` lookup in `engagement.issue` resolves to the right
   module for each caller.
2. **Passive path is genuinely passive and can't run an active tool.** `PassiveRunPane` spawns a raw
   subprocess — confirm it is only ever fed capture/Responder-analyze argv the engines built, that it
   is registered for stop()/PANIC, and that it leaks no process on close.
3. **argv safety**: BPF filter injection, option-injection targets/interfaces, no secret on AD argv,
   URL/port validation in webtriage, scope binding (pinned addresses) in all five.
4. **Installer**: the capabilities + sudoers steps are narrow, validated (`visudo -cf`), best-effort,
   and never fatal; the assembled installer passes `bash -n` (build_installer.sh checks this).
5. **test_cl2_gates** allowlist additions are for #27's passive own-host reads only, correctly justified.

Report → `plan/briefs/RA-TOOLKITX-report.md` on the cluster branch. Verdict: `MERGE` / `DO NOT MERGE`.
