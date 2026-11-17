# RA-DEAUTH — cold audit of gated targeted Wi-Fi deauth (`claude/project-thread-1m4ns8` @ e542627)

Auditor: fresh session, own worktree. Scope = `git diff origin/claude/project-thread-st3z1x...HEAD`
(CLAUDE.md, PALISADE_BUILD_PLAN.md, plan/BACKLOG.md, plan/PROJECT_PROMPT.md, palisade_qt/recon.py,
tests/test_deauth_gate.py, plan/briefs/DEAUTH-renders/render.py, plan/briefs/DEAUTH-report.md).
Probes: `test_ra_probe.py` (scratch, 17 cases, injected harmless spawner — nothing transmits);
its cases are summarised below so they can be turned into regression tests.

Note: the RX head has moved since this branch was cut (746ca7a → 3cf6fd4, RX-fix3). The gate
files are byte-identical to **both** 746ca7a and 3cf6fd4, and `git merge-tree` with 3cf6fd4 is clean.

## Checks

| # | Check | Result | Evidence |
|---|---|---|---|
| 0 | Gate files byte-identical to RX head (engagement, chain, txguard, rfemit, opprofile, executor, wifipent) | PASS | `git diff --stat 746ca7a HEAD -- …` and `… origin/claude/project-thread-st3z1x HEAD -- …` both empty |
| 1a | CLAUDE.md states the gated rule exactly (engagement; AP + client in scope; `txguard.emit_allowed`; issue/spawn/exit in chain; jamming unbuilt) | PASS | CLAUDE.md:40-45 |
| 1b | No doc still carries the "no deauth" ban | **PARTIAL** | BUILD_PLAN, BACKLOG, PROJECT_PROMPT rewritten. **`FEATURE_MAP.md:534-538` still says "`CLAUDE.md` forbids 'deauth/jamming.' These conflict … owner's call"** — stale, and states a ban that no longer exists (N2). |
| 1c | Broadband jamming not built | PASS | No new TX path; jammer.py untouched; rfemit unchanged |
| 2a | No engagement / ended / expired | PASS | refused (DENIED), no `issue`/`spawn` record, nothing spawned (button and direct `_authorize`) |
| 2b | Out-of-scope AP / out-of-scope client | PASS | `test_deauth_out_of_scope_{bssid,client}_…`; probe confirms no issue/spawn |
| 2c | Empty / malformed / option-like client (`-c`) | PASS | refused in `wifipent.prepare` before `issue` |
| 2d | Option-like iface (`-x`, `--ignore-negative-one`) | PASS | refused ("not a network interface name") |
| 2e | TX disarmed; `SUITE_TX_LOCK=1` | PASS | refused before `issue` (engagement.issue `txguard.emit_allowed` after scope), no spawn |
| 2f | **Broadcast / multicast client** | **FAIL** | With `FF:FF:FF:FF:FF:FF` (or `01:00:5E:00:00:01`, or an OUI wildcard `FF:FF:FF:*`) in the scope: **AUTHORIZED and spawned** `aireplay-ng --deauth 3 -a AP -c FF:FF:FF:FF:FF:FF wlan1mon` (N1). Client == AP also authorized (N3). |
| 2g | Pane path reaches `executor.start` without a `wifipent.prepare` ticket, or runs a ticket for a different action | PASS | `_authorize(action)` picks `_runner_for(action)` and `prepare(action)` from the same `action`; `RunPane.run` only takes the ticket the gate returned; executor redeems single-use, argv-hashed |
| 3a | One process per pane; no second capture via deauth pane; no double deauth | PASS | probe: deauth running → DEAUTH disabled, direct second `_authorize("deauth")` refused; HANDSHAKE goes to `wifi_run`; PMKID refused while capture runs; 2 spawns total |
| 3b | Card status follows the right pane | PASS (with Low N5) | `_last_pane` guard: deauth ENDED never stamps the capture line and vice versa |
| 4 | Kill + evidence: STOP on DEAUTH pane, DISARM, env lock, END, PANIC (`executor.kill_all`), close RECON | PASS | each kills the substituted long process; chain shows `issue, spawn, kill, exit` (END: spawn < kill < exit < engagement.close); capture pane keeps running after a deauth STOP; `run_panes()`/`stop()` include `wifi_deauth_run` |
| 5 | Render RECON WIFI 1280×720 dark + sun | PASS (with Low N4) | Both panes and their states (`RUNNING · pid`, `DONE · exit 0`) readable. Sun: card's `ENDED — DONE · exit 0` line half-clipped; IFACE/CLIENT fields show only `lan1mon` / `F:00:01`; deauth output scrolled to `[exit 0]` only. The PNGs the DEAUTH report cites (`before/after-recon-wifi-*.png`) are **not committed** — only render.py. |
| 6 | Regression | PASS | 4 named files: 116 passed (known segfault at interpreter exit after the RX tests). pyflakes clean on recon.py, test_deauth_gate.py, render.py. No assertion in `tests/` removed or weakened vs RX head (only addition: test_deauth_gate.py). Full suite: see below. |

## Findings

**N1 — HIGH (blocker): broadcast/multicast "client" passes the deauth gate.**
`wifipent.prepare("deauth")` only checks `_mac(client)` is 12 hex digits and in scope. If the
group address is in the scope (exact, or via an OUI entry such as `FF:FF:FF:*` / `01:00:5E:*`),
it issues and spawns `aireplay-ng --deauth N -a <AP> -c FF:FF:FF:FF:FF:FF` — a broadcast
deauth that hits every station on the AP, none of which need be in scope. This contradicts the
owner rule (a *client MAC* in scope), wifipent's own docstring ("There is no broadcast form"),
FEATURE_MAP ("never broadcast/flood") and the DEAUTH report. The branch's
`test_deauth_has_no_broadcast_or_clientless_form[FF:FF:FF:FF:FF:FF]` is **vacuous**: the scope
it uses does not contain FF:…, so it passes on the scope check, not on a broadcast rule.
Pre-existing in wifipent.py on the RX head, but this branch is the one that declares the
capability and its tests claim the property. Fix (needs a gate-file change, owner OK): refuse a
client whose first octet has the I/G bit set (`int(cl[:2],16) & 1`), refuse client == AP, and
consider refusing group addresses as scope entries in `engagement.parse_entry`; test with the
address *in* scope.

**N2 — MEDIUM: stale "CLAUDE.md forbids deauth" in FEATURE_MAP.md:534-538** (still lists it as an
open owner conflict). Brief item 1 requires no doc to carry the ban.

**N3 — LOW: client == AP is authorized** (`-a AP -c AP`). Not a station; refuse with N1.

**N4 — LOW: layout/honesty of evidence.** Sun render clips the card's final state line; IFACE and
CLIENT fields too narrow to read the MAC being deauthed (the full argv is on the card line).
DEAUTH-report cites before/after PNGs that are not in the branch, and its Suite line is still the
placeholder `SUITE_RESULT`.

**N5 — LOW: card line lost on refusal.** A refused/"already running" press overwrites the card's
`RUNNING — output below` line while a pane still runs, so that pane's end never updates the card
(pre-existing RX behaviour, more reachable with two panes). Pane headers stay correct. The survey
headline "· no deauth/inject" beside a DEAUTH button reads oddly (already noted in DEAUTH report).

**Info:** the client MAC is checked at issue but not re-checked at spawn (`also=` not used).
Scope is immutable within an engagement and the ticket is void across END/START, so no
exploitable gap; passing `also=((cl,"mac"),)` would make it uniform with netpent/proxmark.

## Full suite
`QT_QPA_PLATFORM=offscreen xvfb-run -a python -m pytest -q tests` (venv, Python 3.12+PySide6): **3 failed, 1839 passed, 9 skipped, 7 errors** in 834 s, then the known segfault at interpreter exit. All failures/errors are the stated baseline: test_shell ×7 (no tkinter), test_audit_tiles undecodable tile, test_hwlab doctor_hwbench, test_sstvdec iss. Nothing new.

## Verdict
DO NOT MERGE — N1 (broadcast deauth authorized and spawned when the group address is in scope; the test claiming otherwise is vacuous). N2 should land in the same fix round.
