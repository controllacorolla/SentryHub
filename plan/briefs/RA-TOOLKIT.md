# RA-TOOLKIT — cold audit of the full-toolkit scope cluster

**FRESH session, Opus. Auditor only — you did not write this.** Own worktree off
`origin/claude/project-thread-cp3fi6` (branched from `origin/main`). Read
`plan/audit/REAUDIT_PROMPT.md` first, then the diff:
`git diff origin/main...origin/claude/project-thread-cp3fi6`. Read
`plan/briefs/TOOLKIT-report.md` on the branch only at step 5.

## What this cluster is
Owner decision 2026-11-17: **every tool in the inventory is in scope; nothing leaves scope without
his authorization.** This cluster does **scope docs + installer + gate catalog only** — it must
**not** wire any tool's execution into the UI (that is the executor cluster, PR #27+). It must not
touch TX paths or `txguard`, must not relax any gate default, and must not change any
data/decoding/radio behaviour.

## Verify
1. **No gate is routed around.** New catalog builders are `netpent.catalog_prepare`,
   `blepent.catalog_prepare`, `proxmark.catalog_prepare`. Each must go through
   `engagement.issue(...)` exactly like the existing `prepare()` in that module — same scope check,
   same evidence-chain requirement, same single-use ticket. Confirm none of them:
   - mints a ticket with no open engagement, or for an out-of-scope target (IP / MAC / label);
   - bakes in attack-specific flags (the argv is `[program] + caller_tokens + target`, nothing else);
   - accepts a program not in that module's `ALLOWED_PROGRAMS`, a path, a shell/interpreter, or a
     renamed binary (lean on `engagement.program_allowed` / `NEVER_PROGRAMS`);
   - lets a target that starts with `-` through as an argv option;
   - bypasses `txguard` for an RF-emitter program (bettercap=wifi, btlejack=ble must still be
     refused while TX is locked — the emitter path in `engagement.issue` must fire).
2. **Catalog correctness.** Every program added to an `ALLOWED_PROGRAMS` is a real tool name, a bare
   basename, and not in `engagement.NEVER_PROGRAMS`. `netpent.CATALOG_PROGRAMS`,
   `blepent.CATALOG_PROGRAMS`, `proxmark.CATALOG_PROGRAMS` ⊆ the module's `ALLOWED_PROGRAMS`.
3. **proxmark label-only.** mfoc/mfcuk cannot be bound to a UID; `catalog_prepare` must pass
   `binding="label-only"` and the ticket must carry it. A `uid:`-only scope with no matching
   `label:` must refuse.
4. **Installer.** `install_head.sh` `[1b/8]`/`[2c/8]`: every auto-installed package goes through
   `safe_apt` (optional, `--` when absent, never fatal, never removes a system/kernel package).
   `tshark` must **not** be auto-installed (debconf prompt). Build the installer
   (`bash build_installer.sh /tmp/t.sh`) and confirm `bash -n` passes and the payload is intact.
   Spot-check 5–6 package names against Debian trixie arm64 (apt-cache / packages.debian.org):
   nikto is non-free; `python3-impacket`, `aircrack-ng`, `can-utils`, `libnfc-bin`, `testssl.sh`
   exist. Source/pip/go tools are only **documented**, never auto-built.
5. **Scope docs honesty.** `FEATURE_MAP.md` "Tool scope" matrix: passive/active labels right
   (an active tool never called passive), hardware column right, install sources match what apt/pip
   actually offers. The two guardrail conflicts (aireplay-ng `--deauth` vs CLAUDE.md; Responder
   poisoning) are **flagged, not resolved** — correct for this cluster.
6. **Tests.** `tests/test_toolkit_scope.py` — one refusal path per catalogued program (no
   engagement + out of scope), plus allowlist wiring and the emitter double-gate. Run it, then the
   full suite once:
   `QT_QPA_PLATFORM=offscreen xvfb-run -a python3 -m pytest -q tests`.
   Known baseline (not this cluster): `test_audit_tiles::test_undecodable_tile_is_marked_failed`,
   `test_hwlab::test_doctor_hwbench_check`, `test_sstvdec` skyfield, flaky `test_cl1_fix2` ack_all,
   and `test_shell`/Qt-collection errors in a bare env without tkinter/PySide6.

## Deliver
Write `plan/briefs/RA-TOOLKIT-report.md` on `claude/project-thread-cp3fi6`, push, remove the
worktree. Table per section (CLOSED / PARTIAL / OPEN), new findings with severity, then one line:
**MERGE** or **DO NOT MERGE**. Blockers: any gate routed around, a ticket minted out of scope, an
emitter past txguard, a TX/txguard change, execution wired beyond the catalog, a regression in an
existing test, or a dishonest scope label.

Trailer: `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>` +
`Claude-Session: https://claude.ai/code/session_01DNwALQSs25svjfFEpxjJ32`
