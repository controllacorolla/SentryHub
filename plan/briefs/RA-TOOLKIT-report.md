# RA-TOOLKIT — cold re-audit report

**Auditor:** independent (did not write this cluster). Worktree off
`origin/claude/project-thread-cp3fi6` (branched from `origin/main`).
**Date:** 2026-11-17.
**Diff audited:** `git diff origin/main...origin/claude/project-thread-cp3fi6` — 9 files:
`FEATURE_MAP.md`, `plan/BACKLOG.md`, `install_head.sh`, `netpent.py`, `blepent.py`,
`proxmark.py`, `tests/test_toolkit_scope.py`, `plan/briefs/{RA-TOOLKIT,TOOLKIT-report}.md`.

Cluster contract: **scope docs + installer + gate catalog ONLY.** No execution wiring, no TX /
`txguard` change, no relaxed gate default, no routing around engagement/opprofile/txguard.

## Scope-boundary check (the cluster must stay inside its lane)
- **No gate/TX core file touched.** `engagement.py`, `txguard.py`, `rfemit.py`, `executor.py`,
  `opprofile.py`, `wifipent.py` are all byte-identical to `main` on this branch. The deauth path
  was not modified. CONFIRMED.
- **No execution wired.** `catalog_prepare` has zero call sites outside `tests/` (grep across the
  tree). It mints a ticket object and returns it; nothing spawns it. Catalog-only. CONFIRMED.

## Section table

| Section | State | Evidence |
|---|---|---|
| 1. No gate routed around | CLOSED | All three `catalog_prepare` route through `engagement.issue(...)`. `issue()` is unchanged and still: (a) classifies emitters via `rfemit` first (SDR_TX refused outright), (b) reads the CALLER module's `ALLOWED_PROGRAMS` via `sys._getframe(1).f_globals` and runs `program_allowed` (bare-name only, `NEVER_PROGRAMS`/interpreter reject), (c) `check()` scope gate, (d) `txguard.emit_allowed()` for any emitter, (e) `also`-targets, (f) `_authorize`. No parameter in the three callers bypasses any of these. No ticket is minted with no engagement or out of scope (tests `test_*_catalog_refused_without_engagement`, `_refused_out_of_scope` — 1 per program). |
| 1a. No attack-specific flags baked in | CLOSED | argv is exactly `[tool] + caller_tokens + target(s)` in all three. No `--deauth`, `-O`, `--script`, etc. hard-coded. |
| 1b. Option-like target rejected | CLOSED | Each caller rejects a `target`/`address` beginning `-` before building argv (`test_net_catalog_rejects_option_like_target`). Tokens are forced plain, non-empty, stripped. |
| 1c. Renamed binary / path / shell rejected | CLOSED | Unchanged `program_allowed`: `os.sep`/`/` → reject; `NEVER_PROGRAMS` + `_INTERP` → reject; not in `ALLOWED_PROGRAMS` → reject (`test_net_catalog_rejects_unknown_tool` with `rm`). |
| 1d. Emitter double-gate (bettercap=wifi, btlejack=ble) | CLOSED | Both are in `rfemit.EMITTER_PROGRAMS`; `issue()` fires `txguard.emit_allowed()`, refused while TX locked (strict default). Tests assert in-scope-but-refused for the emitter branch (`test_net_catalog_in_scope_builds_gated_ticket`, `test_ble_catalog_in_scope_is_gated`). |
| 2. Catalog correctness | CLOSED | `CATALOG_PROGRAMS ⊆ ALLOWED_PROGRAMS` for all three modules; every entry is a real bare basename and none is in `NEVER_PROGRAMS` (`test_catalog_programs_are_allowed_and_never_shells`). |
| 3. proxmark label-only | CLOSED | `catalog_prepare` passes `kind="label"`, `binding="label-only"`; ticket carries `binding == "label-only"` (`test_rfid_catalog_in_scope_builds_label_only_ticket`). A uid-only scope has no `label:` entry, so `_match`'s label path refuses — transitively exercised by the label-mismatch refusal test (see Finding F2). |
| 4. Installer / safe_apt | CLOSED | `[1b/8]` + `[2c/8]` added. Every auto package goes through `safe_apt`: skips already-installed, `return 2`/`--` when missing from sources (never fatal), simulates and refuses any `Remv` or kernel/firmware/bootloader change, `--no-upgrade`. `tshark` intentionally omitted (debconf). Source/pip/go/cargo tools only echoed, never built. `bash build_installer.sh` → `bash -n` OK, payload intact (2 B64EOF, safe_apt present in assembly). |
| 5. Scope-doc honesty | CLOSED | `FEATURE_MAP.md` matrix: passive/active labels sane (Responder split analyze=P / poison=A; tcpdump/tshark P; kismet P; airodump P / aireplay A). Hardware column correct (monitor-mode adapter for Wi-Fi, PN532 for mfoc/mfcuk, micro:bit for btlejack). Install-source claims spot-checked below — all accurate. |
| 5a. Guardrail conflicts flagged not resolved | CLOSED | Deauth (`aireplay-ng --deauth` vs CLAUDE.md) and Responder poisoning both flagged as "owner's call", left as-is; no poisoning builder written; `wifipent` untouched. Correct for this cluster. |
| 6. Tests | CLOSED | `tests/test_toolkit_scope.py` = **86 passed** (0.64s). One refusal path per catalogued program, allowlist wiring, emitter double-gate, label-only binding. |

## Install-source spot-check (Debian trixie arm64, via `qa.debian.org` madison, 2026-11-17)
All claims accurate, including arm64 availability via `+bN` rebuild lines where the first index
line omitted it:

| Package | FEATURE_MAP claim | madison (trixie) | OK |
|---|---|---|---|
| masscan | apt ✓ arm64 | `2:1.3.2+ds1-2` arm64 | ✓ |
| nikto | apt ✓ **non-free** | `1:2.1.5-3.1` trixie/non-free | ✓ |
| python3-impacket | apt ✓ (ships `impacket-*`) | `0.12.0-3` all | ✓ |
| aircrack-ng | apt ✓ arm64 | `1:1.7...` arm64 | ✓ |
| can-utils | apt ✓ arm64 | `2023.03-1+b2` arm64 | ✓ |
| libnfc-bin | apt ✓ arm64 | `1.8.0-3.1+b1` arm64 | ✓ |
| testssl.sh | apt ✓ (bin `testssl`) | `3.2.1+dfsg-1` all | ✓ |
| hydra / smbmap / nbtscan / netdiscover / whatweb / sqlmap / cewl / hashcat | apt ✓ | all present arm64 (hashcat/nbtscan via `+b1`) | ✓ |
| mfoc / mfcuk | apt ✓ (PN532) | arm64 via `+b1` | ✓ |
| gobuster / ffuf | apt ✓ arm64 | arm64 via `+b10`/`+b9` | ✓ |
| netexec / enum4linux-ng | "not in apt → pip" | not in trixie | ✓ |
| bettercap | apt ✓ arm64 | `2.33.0-1+deb13u2` arm64 | ✓ |

## Suite result
`QT_QPA_PLATFORM=offscreen python3 -m pytest tests --timeout=90 --timeout-method=thread -q`
→ **3 failed, 1783 passed, 18 skipped in 808.79s.**
The 3 failures are the documented baseline, all in modules this cluster does not touch:
`test_audit_tiles::test_undecodable_tile_is_marked_failed`,
`test_hwlab::test_doctor_hwbench_check`,
`test_sstvdec::test_iss_passes_use_their_own_tle_and_leave_weather_cache_alone` (skyfield).
No cluster test fails; no regression introduced.

## New findings
| ID | Sev | Finding |
|---|---|---|
| F1 | Low (hygiene) | `plan/BACKLOG.md` landing-order checkboxes for the two installer items are left `[ ]` unchecked, although `install_head.sh` was modified in this same PR. Cosmetic doc drift; not a gate or behaviour issue. |
| F2 | Low (hygiene) | Brief point 3 ("a `uid:`-only scope with no matching `label:` must refuse") holds by construction — `proxmark.catalog_prepare` passes `kind="label"`, and `engagement._match`'s label path only matches `kind=="label"` entries — but there is no *dedicated* regression test pinning the uid-only-refuses case. The existing label-mismatch refusal test covers it transitively. Adding one explicit test would close the gap. |

Neither finding is a blocker. No gate is routed around; no ticket is minted out of scope; no
emitter reaches the executor past `txguard`; no TX/`txguard` change; no execution wired beyond the
catalog; no existing test regressed; no dishonest scope label.

## FINAL VERDICT
MERGE
