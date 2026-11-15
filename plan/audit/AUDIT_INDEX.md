# Independent audit — 2026-11-15 — index

Source of truth: `PALISADE_full_audit_report_2026-11-15.pdf` (36 pages, 93 findings:
2 critical, 41 high, 39 medium, 11 low). Audited `main @ e6184c6`. This file is only an
index; every fix references the PDF's ID, location and fix text.

## Verdict (from the report)

Not ready for field use. Both claims under test are false:

- **Gate claim** ("every transmit/inject/write path funnels through two choke points"): false.
  Three gate policies, an ungated write path to emitting hardware (serial → Flipper-class
  devices), a transmit path whose kill switch the UI overrides (BENCH), an ungated network
  scanner in the Tk app (Scout → nmap). Gates look intact mainly because nothing they
  authorize is wired to execute.
- **Honesty claim** ("live shows only real backend output; empty is never a real negative"):
  false. COUNTER shows an empty findings table with every detector offline; ATLAS republishes
  hour-old aircraft as live; PROWL dBm, PRISM peak-hold and OPS decode rate are not measured.
- **Screen does not fit.** Shell needs 551 px on a 480 px panel; status text ~0.9 mm.
  **CORRECTION 2026-11-15:** the panel is **1280×720**, not 1280×480 (device diagnostic: CWU50 DSI,
  native 720×1280 rotated right; ~294 ppi). The repo had the DevTerm's resolution. The 551 px shell
  fits. D1 drops to **High** (BENCH still widens to 1845 px; add a fits-1280×720 test). D2/D3 remain
  valid in substance (status text too small; chrome and left rail waste width) at reduced severity.
- Most of RECON and FORGE does nothing in live mode (PRINTS ONLY / DEMO ONLY / DEAD).
- Installer does not ship the Qt app.

What held: all 11 `prepare()` gates deny correctly for well-formed input; `txguard.authorize()`
chain enforced in order; ~150k malformed inputs across every parser, no crash; event-bus
publish is lock-guarded; sky math accurate; no `eval`/`exec`/`pickle`/`os.system`.

## Top 20 in fix order (report §3)

| # | ID | Sev | Finding |
|---|---|---|---|
| 1 | D1 | Critical | Window needs 551 px on a 480 px panel; BENCH widens to 1845 px |
| 2 | K1 | Critical | Bug sweep discards any new emitter outside seven hard-coded bands |
| 3 | G1 | High (latent Critical) | BENCH keys a transmitter on one checkbox, incl. 121.5 MHz |
| 4 | H1, D5 | High | COUNTER empty table with all detectors offline; no real sweep feeds them |
| 5 | G2 | High | FORGE serial console writes ungated to Flipper-class devices |
| 6 | G7, G6 | High | Evidence chain is RAM-only, editable, optional |
| 7 | L1, G8 | High | Tk kill switch connected to nothing; strict gate unreachable |
| 8 | E1 | High | ATLAS republishes hour-old aircraft as live |
| 9 | R1, R2 | High | BABEL takes the radio and never returns it; relaunch loop cycles readsb |
| 10 | A1, A4, H2 | High | Radio handoff: revoked holder not told, orphaned decoders, frozen PRISM under green |
| 11 | S1 | High | Installer does not install or launch the Qt app |
| 12 | S2 | High | Tk Scout runs nmap on the subnet with no engagement check |
| 13 | L4 | High | A settings file can run shell commands in both apps |
| 14 | D4, H7 | High | Live/demo, radio, TX, engagement share one overwritable 10 px chip |
| 15 | D2 | High | Body text 1.2 mm, labels 0.9 mm |
| 16 | A2 | High | A worker that outlives its 3 s join aborts the process |
| 17 | G4, G5, G3 | High | Scope checks are string globs / unbound labels; Flipper classifier is a denylist |
| 18 | H11, H12, H14 | High | PROWL dBm, PRISM peak-hold, OPS decode rate are not measurements |
| 19 | K5, K6 | High | IMSI-catcher and GNSS detectors false-alarm on normal input |
| 20 | D6, H5 | High | OPS empty until other pages opened; all geometry computed from Seattle |

## Fix clusters (report §14), one branch + independent re-audit each

Clusters are **CL1–CL9** (finding IDs C1, C2, C4, C5 are the report's security findings — different namespace).

| Cluster | Branch | IDs |
|---|---|---|
| CL1 Screen fit + structure | `fix/cl1-screen-structure` | D1 D2 D3 D4(slots) D7 D8 D9 D10 · §9 RADIOS panel, audio |
| CL2 Gate integrity | `fix/cl2-gates` | G1 G2 G3 G4 G5 G8 G9 G10 G11 G12 G13 L1 S2 S3 — regression test per PoC |
| CL3 Evidence chain | `fix/cl3-evidence` | G6 G7 H9 E5 C2 |
| CL4 Honest state | `fix/cl4-honest-state` | H1 H2 H3 H4 H5 H6 H7 H8 H10 H11 H12 H13 H14 H15 H16 H17 H18 H19 E1 E4 D4(empty-state) L5 |
| CL5 Radio handling | `fix/cl5-radio` | A1 A2 A3 A4 A5 A6 R1 R2 R3 R4 R5 E2 E3 B1 B2 B3 |
| CL6 Structure + functional gaps | `fix/cl6-structure` | D6 · §9 executor + output pane, settings drawer, start/stop, export, search/sort, offline map, GPS; wire BLE scan, CAN monitor, rtl_433, detectors from PRISM sweep |
| CL7 Detectors + SWEEP | `fix/cl7-detectors` | K1 K2 K3 K4 K5 K6 D5 — validated against recorded real captures before trusted |
| CL8 Security + shipping | `fix/cl8-ship` | L4 C1 L3 L2 L6 S1 S4 C4 C5 P1 P2 P3 B4 B5 B6 E6 |
| CL9 Tests | with each cluster | T1 T2 T3 T4 T5 — fakes at the process boundary; remove offscreen checks from production |

## Decisions the report left to the owner

- Conducted bench on protected bands (tests assert a 1090 MHz key-up with only a settings flag)
- LoRa bypass (`decide(service="lora")` passes with `tx_enabled` false)
- `opprofile.tx_settings` enabling TX whenever a callsign exists
- Callsign grouping and names (D7) — **decided 2026-11-15: 8 keys, function label beside each;
  SWEEP promoted; BABEL merged into PROWL; BENCH and OVERWATCH folded (see plan/briefs/CL1.md)**

## Process rule adopted

No cluster is "done" on the implementer's own review. Each cluster branch gets a cold-read
re-audit against the PDF's IDs before merge. The audit prompt lives at
`plan/audit/REAUDIT_PROMPT.md`.
