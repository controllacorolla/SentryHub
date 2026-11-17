# RA-DEAUTHb — cold re-audit of DEAUTH-fix, branch `claude/project-thread-1m4ns8`

Auditor: fresh session, own worktree (`wt-RA-DEAUTHb`). Round 2, re-verifying the DEAUTH-fix
against `plan/briefs/RA-DEAUTH-report.md`.

**Head audited:** `f65db21` (`DEAUTH-fix: correct a third multicast deauth-client fixture`),
parent `9ebc439` (`DEAUTH-fix (RA-DEAUTH): refuse a broadcast/group or self client; readable
fields`). The branch advanced from `9ebc439` to `f65db21` mid-audit; `f65db21` is fixture-only
(see below) and I re-ran against it.

**RX head:** `origin/claude/project-thread-st3z1x` = `8ff7504` (RX-fix3 tip).

## Scope of the fix (what changed vs RX head)

- **`wifipent.py`** (gate file, +8 lines): in `prepare("deauth", …)`, before `engagement.check`
  / `engagement.issue`, refuse a client whose first-octet I/G bit is set
  (`int(cl[:2],16) & 1` — covers `ff:ff:ff:ff:ff:ff` and any multicast) and a client equal to
  the AP. Strictly **narrower** (refuses more); no refusal loosened.
- **`palisade_qt/recon.py`** (deauth pane + N4 layout): all changes are deauth-related (the
  per-action `runners` map / second DEAUTH pane, `_last_pane` guard) or the N4 field-row change
  (≤2 label/field pairs per row so the CLIENT MAC gets a full-width row). No non-deauth path
  changed.
- **`engagement.py`, `chain.py`, `txguard.py`, `rfemit.py`, `opprofile.py`, `executor.py`** —
  byte-identical to the RX head (verified `git diff` empty for each, at `f65db21`).
- Docs: `FEATURE_MAP.md`, `DEAUTH-report.md`. Renders: 4 PNGs committed. Tests: see below.

## Re-verification of RA-DEAUTH findings

| ID | Sev | Status | Evidence |
|---|---|---|---|
| **N1** | High (blocker) | **CLOSED** | `wifipent.py:101-106`: I/G-bit refusal before any `issue`; `t is None`, nothing spawned. Probe (client *in scope*): `FF:FF:FF:FF:FF:FF`, `01:00:5E:00:00:FB`, `33:33:00:00:00:01`, odd-octet unicast-looking `03:…`/`0D:…`/`11:…`, `ff-ff-…` dash form, mixed case, colonless `ffffffffffff` — **all REFUSED** with "broadcast/multicast"; normal unicast `00:…`, `12:…`, `AA:…`, `0A:…` still ISSUED (not over-refused). Test: `test_wifipent::test_deauth_refuses_a_broadcast_or_multicast_client_even_in_scope` (broadcast + `01:00:5E` multicast, both in scope); `test_deauth_gate::test_deauth_has_no_broadcast_or_clientless_form` now puts `FF:…` in scope, so it is no longer vacuous. |
| **N2** | Medium | **CLOSED** | `FEATURE_MAP.md:534-539`: the "`CLAUDE.md` forbids deauth / owner's call" conflict is gone; now "DECIDED (owner, 2026-11-17): gated capability". No doc carries the ban. (Remaining `owner's call` at :543 is item 2, Responder poisoning — unrelated.) |
| **N3** | Low | **CLOSED** | `wifipent.py:107-108`: `cl == ap` refused ("cannot be the AP itself"). Probe confirms. Test: `test_wifipent::test_deauth_refuses_a_client_equal_to_the_ap`. |
| **N4** | Low | **CLOSED (primary) / PARTIAL (residual)** | CLIENT MAC now on its own full-width row — renders `after-recon-wifi-{dark,sun}.png` at 1280×720 show `DE:AD:BE:EF:00:01`, IFACE `wlan1mon`, CH `6` all fully readable (prior `lan1mon` / `F:00:01` clipping fixed). Renders now committed (were absent before). `DEAUTH-report.md` `SUITE_RESULT` placeholder filled. **Residual:** the card's echoed `$ aireplay-ng …` line is still clipped at the card bottom in both themes — accepted per brief item 4 (same argv is announced via `on_authorized`; cosmetic Low, no honesty impact). |
| **N5** | Low | **OPEN (accepted)** | A refused/"already running" press still overwrites the card's `RUNNING — output below` line (pre-existing RX behaviour). The `_last_pane is pane` guard added here fixes the *cross-pane* mis-stamp (deauth ENDED never stamps the capture line). Pane headers stay correct. Low, not a blocker. |
| Info | — | Unchanged | Client MAC checked at issue, not re-checked at spawn (`also=` unused). Scope immutable within an engagement, ticket void across END/START, argv-hashed single-use — no exploitable gap. |

## Brief-specific checks

1. **Gate strictly narrower, in-scope group/self refused before issue, nothing spawned** — PASS.
   Direct probe of `wifipent.prepare` (17 cases) with the group address *in the engagement
   scope*: every group/multicast/odd-I/G/self client returns `(False, …, None)` before
   `engagement.issue`; no ticket, so the RunPane never receives one. Count still capped
   (`count=9999 → 10`). Existing out-of-scope AP, out-of-scope client, no-client, TX-off,
   no-engagement refusals all still hold.
2. **No other refusal loosened; no non-deauth path changed** — PASS. Gate files
   engagement/chain/txguard/rfemit/opprofile/executor byte-identical to RX head;
   `wifipent.py` diff adds only two refusals; `recon.py` diff is deauth-pane + N4 layout only.
3. **Fixture corrections genuine, not weakened** — PASS. `11:22:33:44:55:66` (0x11, I/G set)
   and `99:99:99:99:99:99` (0x99, I/G set) were in fact group addresses; corrected to unicast
   `12:22:33:44:55:66` in `test_cl2_fix.py`, `test_cl2_gates.py`, and (in `f65db21`)
   `test_cl2_fix2.py`. Each test asserts the **same** ok/refuse outcome and argv; the
   `99:…` case is an out-of-scope assertion (`not ok`) that still holds. No assertion weakened.
4. **N4 render 1280×720 dark + sun, capture running + deauth done** — PASS (CLIENT MAC fully
   readable in both); residual card-line clipping noted above.
5. **Regression** — targeted set `test_deauth_gate test_wifipent test_cl2_fix test_cl2_gates
   test_rx_recon_exec` + `test_cl2_fix2`: **260 passed** (segfault at interpreter exit = known
   Qt baseline). Full suite at parent `9ebc439`
   (`QT_QPA_PLATFORM=offscreen xvfb-run -a python -m pytest -q tests`): **5 failed, 1842 passed,
   9 skipped, 7 errors**, exit 139. The 7 errors + 3 of the 5 failures are the stated baseline
   (test_shell ×7 no-tkinter, test_audit_tiles, test_hwlab doctor, test_sstvdec iss). The other
   two failures were `test_cl2_fix2::test_r1…` and `::test_r2…` — the *third* multicast
   deauth-client fixture (`11:22:33:44:55:66`) that `9ebc439` missed. **`f65db21` corrects it**
   (fixture-only, production code byte-identical to `9ebc439`); both now pass, so the final-head
   full suite returns to the known baseline (3 failed + 7 errors + flaky `test_cl1_screen` +
   exit segfault). pyflakes clean on all changed files.

## New findings

| ID | Sev | Finding |
|---|---|---|
| B1 | Low (resolved on final head) | `9ebc439` left a third multicast deauth-client fixture (`test_cl2_fix2.py` R1/R2) uncorrected, so the suite showed 2 extra failures at that commit. The sibling fix landed `test_cl2_fix`/`test_cl2_gates` but not `test_cl2_fix2`. **Resolved in `f65db21`.** No production impact — the gate was behaving correctly; the fixture was stale. |

No new gate bypass, no out-of-scope / disarmed / broadcast spawn, no missing kill/exit record,
no weakened assertion.

## Verdict

**MERGE** — audit the branch at head `f65db21`. N1 (High) is closed with a non-vacuous,
in-scope regression test; N2/N3 closed; N4 CLIENT-MAC readability closed (residual card-line
clipping is an accepted Low). The gate change is strictly narrower, all other gate files are
byte-identical to the RX head, and the fixture corrections are genuine (the old MACs were
group addresses) with no weakened assertions. Full suite at the final head is back to the known
baseline. Merge `f65db21`, not `9ebc439` (which has the two stale-fixture failures).
