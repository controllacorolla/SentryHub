# PLANNER HANDOFF — read this first in a new chat/Project (written 2026-11-15 16:20 MT; updated 2026-11-16 CL5 merged)

You are the **planner** for PALISADE (repo `controllacorolla/SentryHub`). The owner, Dalton, is
not a software engineer. Communicate in short, decisive messages with one action at a time, and
report what you did and why (merges, decisions taken, anything found) so he can see and correct
it. He asked not to be consulted on routine steps, so: proceed on routine merges that passed a
cold audit and **tell him each time**; stop and ask before anything irreversible or outside the
audit protocol (force-push, deleting branches, system changes, relaxing a gate default, anything
touching a protected band or the device). Decisions he reserved: Tk vs web, logo/SVG, second SDR,
ham callsign, head signing automation, session-chain prune policy, the v0.1 launch line.

## How work flows (owner decision 2026-11-15 16:33; README "Where audits run")
- One Project chat (`PALISADE`, repo attached) is the planner: writes fixes on the cluster branch,
  runs the suite (`QT_QPA_PLATFORM=offscreen xvfb-run -a python3 -m pytest -q tests`), opens and
  merges PRs, updates this file after every merge. Owner reads and approves what is flagged.
- **Cold audits run as subagents from that chat**: spawn a fresh `general-purpose` agent on Opus,
  own worktree, prompt = "git fetch origin docs/briefs && read plan/briefs/<RA-ID>.md and
  plan/audit/REAUDIT_PROMPT.md; do exactly that; push the report to the cluster branch". It must
  not be given anything from the planner's context. Verdict MERGE / DO NOT MERGE; on DO NOT MERGE
  fix, push, spawn `RA-<cluster><next letter>`.
- The Mac runner is retired (owner closes the Terminal windows). Mac = hardware/device checks only.
- Models: planner Mythos; gate/evidence/TX code Mythos; audits Opus; mechanical Sonnet/Haiku.
- Token rules: suite once per stage, renders only for touched screens, ≤4 subagents, no polling or
  sleep-and-check loops, new chat every 1–2 clusters (write this file first). Never force-push.

## State at handoff
| Cluster | Branch | State |
|---|---|---|
| CL1 screen | merged (PR #19) | RA-CL1d MERGE |
| CL2 gates | merged (PR #20) | RA-CL2e MERGE. **RA-MAIN-1** (post-merge check) was queued on the Mac runner; if no `RA-MAIN-1-report.md` exists on `audit/ra-main-1`, run it as a subagent |
| CL3 evidence chain | **merged (PR #21, 5c5607b)** | RA-CL3d MERGE (via RA-CL3b → CL3-fix2 B3/N14 → RA-CL3c → CL3-fix3 N16–N19). Owner decisions: 2 s END drain accepted; N16 = kill orphan only on pid+start-time match ("orphan at END"), else UNCONFIRMED. Follow-ups for CL4: **N20 Med** (verified_gone/`_kill_group` check only the group leader — probe killpg(pg,0), SIGKILL rest, UNCONFIRMED if any survive), N21–N25 Low (see RA-CL3d-report), plus N11 N12 N13 N15 R1 |
| CL5 radio/threads | **merged (PR #22, 04a76ab)** | RA-CL5d MERGE (via RA-CL5 → CL5-fix → RA-CL5b → CL5-fix2 → RA-CL5c → CL5-fix3). Owner decision: NWR LIVE requires the decoder to be continuously reading audio (multimon-ng rchar heartbeat). Follow-ups: **N-m Med** (late SSTV refinement after a ≥1 s decode counted as a 2nd frame: `_stop_rec` each second resets `_stale_frame`), **N-r Med** (NWR no minimum audio rate), N-s/N-t Low (switching chip lingers after a cancelled switch; PROWL resumes only on Enter after a revoke-cancelled switch), pre-existing N-o (granted while readsb restarts — needs RELEASING state), N-p, N13 (legacy Tk shell=True) — see RA-CL5d-report |
| CL4 honest state | **merged (PR #23, 1bc8ad1)** | RA-CL4 DO NOT MERGE (N26 High: rings from guessed origin) → CL4-fix → RA-CL4b MERGE (faa6c54). Follow-ups: N33 Low (torn last line bricks chain, fails closed), N35 Med (OPS keeps pre-HOME contacts ≤12 s after HOME set — clear on home_changed like ATLAS), N36 Med pre-existing (leader gone at END → group survivor not signalled, recorded UNCONFIRMED), N37 Low (FORGE serial-connect counts as a feed), BABEL runners say LIVE before first decode (CL7), H5 GPS source (CL6) |
| CL6, CL7 | not started | `plan/audit/AUDIT_INDEX.md` |
| CL8 | **merged (PR #24, ed4e068)** on Dalton's "merge" 2026-11-17 | RA-CL8f MERGE; decoder-liveness class → CL5 follow-up |
| SCAN | **merged (PR #25, 22941ba)** on the same OK | RA-SCAN → SCAN-fix → RA-SCANb MERGE; follow-ups in `plan/briefs/SCAN-report.md` |

## Owner decisions 2026-11-16
- Keep the PERMITTED TX word for v0.1. CL3's 2 s END wait accepted (deliberate). CL3 B3 fix is in a separate thread.
- Sonnet is not enabled for this org (switch refused); mechanical work runs on Opus.

## Known environment facts
- Linux (FreeType) renders the top strip **1284 px** wide in the worst case (Mac: 1279). The repo
  does not ship `palisade_qt/fonts/` (load_fonts is a no-op). Fix = bundle fonts + 8 px headroom;
  flagged in RA-MAIN-1; do it in CL5 or a small CL1-fix4. The uConsole runs Debian.
- Known baseline failures on main: `test_audit_tiles::test_undecodable_tile_is_marked_failed`,
  `test_hwlab::test_doctor_hwbench_check` (env), `test_sstvdec::…iss_passes…` (skyfield). Without
  tkinter, `tests/test_shell.py` errors; `test_all_callsigns_build_in_both_themes` segfaults on
  3.13 only on branches that predate CL1's `_retain`.
- Owner decisions so far are recorded in the briefs: CL2 (strict TX defaults), CL2-fix (SDR
  transmitters txguard-only; lock silences every emitter; Tk gated tools stay blocked → retire in
  CL8), CL2-fix2 (SSH program allowlist, no ProxyJump in v0.1, digimodes refused until CL8),
  CL1-fix2 (PANIC unchecks BENCH ack, nav labels visible, ATLAS no h-scroll), CL3 (strict
  defaults; head signing not automated — owner question open).
- **Launch line CONFIRMED by owner 2026-11-16:** v0.1 = CL1–CL5 + CL8 with SWEEP and unfinished
  tools hidden; CL6/CL7 → v0.2. Ask him when CL5 is in.

## First actions in a new chat
1. `git fetch origin`; check for `RA-CL3b-report.md` on `fix/cl3-evidence` and `RA-MAIN-1-report.md`
   on `audit/ra-main-1`. Missing → spawn each as a cold subagent. Present → act on the verdict.
2. CL5: fix the 3 tests above, report, `RA-CL5` subagent. 3. CL4 off main once CL3 merges, then CL8.
4. CL5 merged 2026-11-16; v0.1 launch line confirmed. Next: CL4 off main, then CL8. Tell him in one line after each merge.

5. 2026-11-16: CL4 merged (PR #23, 1bc8ad1) on Dalton's OK. Next: CL8 off main.
6. 2026-11-16 CL8 on `fix/cl8-ship`, draft PR #24. Six audit rounds (RA-CL8 … RA-CL8f; briefs on
   docs/briefs, reports on the branch). Each round after the first found older radio-hold bugs
   (decoder dies, radio kept) and they were fixed in CL8-fix … fix5. RA-CL8f: all CLOSED except
   the decoder-liveness class (decoder starts, then stalls or dies later: NFM SCAN after the 1 s
   kill, AM SCAN/SSTV/BABEL/ATLAS stalls, slow deaths) — on main too. Verdict MERGE if that class
   goes to a CL5 follow-up (one stall watchdog for every radio path, like NWR's). Owner decision
   card posted; merge only on Dalton's explicit OK. Device check: `python3
   plan/briefs/device_check_cl8.py` → `DEVICE CHECK CL8: PASS (10/10)`.
   CL8 follow-ups: decoder liveness watchdog (CL5-fu), L3 LAN DNS rebinding, DNS lookups ignore
   NET mode, L6 code under user-owned $APP, AIS/RDS duplication (CL6), legacy Tk excepts, OPSEC
   slot needs strip room back, RID 3-advert / TPMS 30 s tuning, session log cap can drop an
   unseen fault, restore drops any file with a tx_ key silently, SCAN HOLD keeps the radio with
   no rtl_fm, flaky test_cl1_fix2 alerts test (main too).
7. 2026-11-17 first uConsole install (thread "Install PALISADE on the uConsole"). Procedure:
   clone, `git checkout fix/cl8-ship`, `bash build_installer.sh ~/install-palisade.sh && bash
   ~/install-palisade.sh`, `python3 -m pip install --user --break-system-packages pytest`, device
   check, re-login (plugdev), `palisade`. Install OK on device (kernel-hold warning only; not acted
   on). Commit 7837619 on fix/cl8-ship: device check names a missing pytest (test_device_check.py).
   Device: Debian 13, Python 3.13.5, PySide6 6.8.2.1, pyqtgraph 0.13.7, numpy 2.2.4, pytest 8.3.5,
   Wayland (grim). Device check FAIL 9/10: test_cl8_ship "1 failed, 151 passed". The same file with
   those exact pinned versions + skyfield passes 152/152 in the container, so the failure is
   device-environment specific (real ~, readsb/iw present, real display) — failing test name pending.
   **Follow-up N-ui1 (Med, v0.1 polish): top-strip nav keys overlap on the device.** First launch
   at 1280x720: callsigns run together ("4 PROWL5 RECON") and function labels sit at different
   heights, so "survey" reads as belonging to the wrong key. Reproduced in the container under
   xvfb with the device's pinned versions (not platform-specific). Causes: (a) keys are packed at
   their minimum text width with 1 px layout spacing and SIDE=1, so adjacent callsigns have no gap
   (CL8 took the strip slack for NET); (b) NavKey._place centres each key's own ink box, so a label
   with descenders (spectrum, listen, hardware) sits lower than one without (map, survey) and the
   row has no common baseline. Fix: shared baseline for all keys + visible gap/separator between
   keys, within the 1270 px worst-case budget (test_cl1 strip-width tests).
Screenshot: Dalton's upload 2026-11-17 04:47 MT.
8. **v0.1 BLOCKER N-op1 (High, found on device 2026-11-17): the UI cannot set the operator, so no
   engagement can be opened from PALISADE.** SYSTEM › SETTINGS prefills Operator from
   `opprofile.load(suite.settings)` (operator.json) but SAVE SETTINGS writes `callsign` into
   `palisade_ui.json` (`palisade_qt/system.py` `_write_settings`/`_save_settings`), while
   `engagement._profile_operator()` reads operator.json. Result: start_engagement always says
   "no operator profile", and the save message falsely says "persisted: operator". Present on
   **main and fix/cl8-ship** (same code). Dalton has a manual workaround (edit operator.json).
   Fix in its own cluster branch off main after PR #24 merges, before the v0.1 tag: SAVE writes
   the operator identity through opprofile (operator.json) only, never sets or changes
   `tx_enabled` (CL2 strict default: a callsign alone never enables TX), validates per
   opprofile, reports honestly; regression test = save in SETTINGS → `engagement._profile_operator()`
   returns it → start_engagement succeeds; plus a test that tx_enabled is untouched. Gate-adjacent:
   planner writes it; cold audit RA-<cluster> before merge.
9. 2026-11-17 **N-op1 MERGED (PR #26, 01afe7b) on Dalton's OK.** Was `fix/n-op1-operator` (off main 1bc8ad1), cold audit
   RA-N-op1 **MERGE** (report on the branch). SAVE SETTINGS now writes callsign/name to operator.json
   via opprofile DEFAULTS; tx_enabled untouched; honest message. Merge only on Dalton's OK; if PR #24
   lands first, merge main into the branch (system.py identical on both, expect no conflict).
   Low follow-ups: N1 wrong-typed profile values written back corrected; N2 field keeps lowercase
   after a callsign save; N3 corrupt operator.json reset not named in the save message.
9. 2026-11-17 SCAN cluster (thread "Make Wi-Fi and Bluetooth scans work"): PR #25, branch
   `claude/project-thread-08f65f`, **stacked on #24** (merge #24 first, then #25 shows only SCAN).
   RA-SCAN DO NOT MERGE (11 findings) → SCAN-fix → **RA-SCANb MERGE** (47fa6ff). Live Wi-Fi via
   nmcli fallback (labelled ACTIVE), live BLE (bleak / bluetoothctl), ATLAS Remote-ID active
   fallback (bluetoothd lacks --experimental), rtl-sdr in installer, doctor Wi-Fi/BLE checks.
   Owner decisions open: setcap cap_net_admin on iw (passive Wi-Fi); bluetoothd --experimental
   (passive Remote-ID). Follow-ups in plan/briefs/SCAN-report.md (B1 Med rid note chip never
   clears, N5, N8, B2–B7). Still-placeholder scans: SWEEP bugsweep/jammer/gnss/imsicatch, FORGE
   SENSORS/CAN, RECON RF RFFINGER/SCOUT — next: SWEEP gnss (gpsd) + SCOUT.
10. 2026-11-17 06:40Z: PR #24 (CL8) and PR #25 (SCAN) merged to main on Dalton's "merge". Device
   moves from fix/cl8-ship to main: `cd ~/SentryHub && git fetch origin && git checkout main &&
   git pull --ff-only && bash build_installer.sh ~/install-palisade.sh && bash ~/install-palisade.sh
   && python3 plan/briefs/device_check_cl8.py` → expect `DEVICE CHECK CL8: PASS (10/10)`; the
   PASS line from the device on main is still owed (pre-merge re-run line never posted here).
   Open before the v0.1 tag: **N-op1 BLOCKER** (operator save → operator.json, gate-adjacent),
   N-ui1 + device-notes UI cluster, SAT basemap (Esri key), CL5 decoder-liveness watchdog, SCAN
   follow-ups (B1 Med). Next scan cluster: SWEEP gnss (gpsd) + SCOUT. CL6/CL7 = v0.2.
