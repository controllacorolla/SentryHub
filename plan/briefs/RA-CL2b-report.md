# RA-CL2b — cold re-audit of CL2-fix (`fix/cl2-gates` @ `2e83105`)

**Auditor:** a fresh session, Opus 5.5. Separate worktree `../ra-cl2b`; the shared checkout was not touched.
`CL2-report.md` was read only after the probe verdicts were fixed (brief step 3).
**Method:** every N1–N9a PoC re-derived independently in `RA-CL2b-evidence/ra_cl2b_poc.py`; results are in
`ra_cl2b_poc.json`. All spawns go to a `sleep` stand-in, so nothing radiates. One mutation run checked
whether any test was weakened (step 3).

## Verdict

**DO NOT MERGE.** N2, N3, N4, N5, N6, N8 and N9a hold against every attack I tried. Two things block the merge:

1. **N1 is PARTIAL.** The rfemit classifier matches strings and is defeated by shell quoting. A shipped
   free-text path (DEVTERM SSH) runs `hackrf_trans''fer … -f 1090000000` through the engagement gate with no
   txguard check.
2. **A denial check was weakened (brief step 3).** No assertion text changed. But 4 unchanged out-of-scope
   refusal tests now pass even with scope enforcement deleted, because the disarmed RF gate refuses first.
   `CL2-report.md` says "no denial weakened"; that is false.

## Per item

| ID | Verdict | Evidence (my probe → result) |
|---|---|---|
| **N1** SDR TX only via txguard | **PARTIAL** | **Holds** for the literal-name argv shapes: plain name, absolute path, `UPPER`, `sudo`, `env`, `sh -c`, `busybox sh -c`, the GPS-SDR-SIM pipe, and the 1090 MHz RA PoC. Direct `executor.issue` from a non-gate module is refused. **Breaks:** `engagement.issue` minted a ticket for `bash -c` with `hackrf_trans''fer`, a `?` glob, `$'\x68…'` and `${a}_transfer`; for `python3 -c` with string concat; for a Cyrillic look-alike name and a renamed or symlinked binary; and for transmitters missing from the list (rpitx `tune`/`sendook`, UHD `tx_waveforms`, `urh_cli -tx`, a GNU Radio flowgraph `.py`, `sdrangelsrv`). Shipped reachability: `devterm.prepare_ssh` (`devterm.py:138`, Tk DEVTERM `:660`) puts operator free text into `ssh <host> <cmd>`. With `127.0.0.1` in scope, `hackrf_transfer …` is refused, but `hackrf_trans''fer -t x.iq -f 1090000000 -x 47` was **issued and spawned**. `ra_cl2b_poc.py` `n1_issue`, `n1_ssh`. |
| **N2** lock + kill switch silence every emitter | **CLOSED** for every emitter class the tools ship (residuals R3, R4) | I tested all 11 classes: Wi-Fi deauth and PMKID, Zigbee inject and discover, Z-Wave query and map, BLE write, Flipper sub-GHz, an ESP32 line, Proxmark sim and clone. Each was refused at issue under `SUITE_TX_LOCK=1` (armed and unlocked otherwise) and refused at issue while disarmed. Each was issued armed and then refused at spawn after a lock or a disarm, which is 22 of 22 cases. DISARM killed a running deauth, Zigbee inject and Proxmark sim. Setting the env lock mid-run killed a deauth through the 0.25 s monitor. Wired tools are not over-blocked: nmap and USB-HID still issue under the lock. `n2_*` |
| **N3** hub identity | **CLOSED** on macOS · **Linux unverified on device** | Each of these read as STALE: a recycled pid (start time differs), a crash-stale file (dead pid), another hub (nonce mismatch), no nonce in env, a forged file naming the parent pid with its real start time but the wrong nonce, and a group- or other-writable file. End to end with a real child: genuine hub → armed; forged nonce → STALE; hub closed → STALE. **Linux:** `_linux_start` was read by code review and fed a synthetic `/proc/4242/stat` whose comm contains `) `. It correctly returns field 22 (`rindex(")")` handles the parentheses). **It has not run on Linux or on the uConsole. Unverified there.** Residual R6. `n3_*` |
| **N4** Proxmark emulated/written ID + `;` | **CLOSED** | All of these were refused: sim with an out-of-scope uid; clone with an out-of-scope id; `;` with and without a space; a newline; flag smuggling (`--4k`); a missing uid; `;` inside t55 `data`; a `.`-containing id. An in-scope `de:ad:be:ef` was normalised to `-u DEADBEEF`. With the emulated ID dropped from scope after END and a re-open, spawn was refused at the re-check (`also`). Residual R5 is already labelled in the trail. `n4`, `n4_recheck` |
| **N5** hostname pinned | **CLOSED** | `nas.lan` → argv `nmap -sS -p 1-1024 10.0.0.7` contains no name, so a later DNS change is moot. A name that resolves to an in-scope and an out-of-scope address refuses the whole scan. `n5`, `n5_multi` |
| **N6** `"2e6"` | **CLOSED** | `2e6` → `-s 2000000` and `2.5e6` → `2500000`. `nan`, `inf`, `1e400`, `True` and `0x200000` are refused cleanly, with no crash. `n6` |
| **N8** live settings | **CLOSED** | Clearing `tx_enabled` in the live dict killed a running replay. Clearing the bench `opt_in()` (the saved value) killed a running bench key-up. `n8` |
| **N9a** demo ticket → synthetic port only | **CLOSED** (contract) | A real port object is refused; `DemoSerial` wrote 6 bytes. This is still contract-based: any class can declare `SYNTHETIC = True`, which is acceptable under the executor's stated threat model. `n9a` |

## Step 3 — the CL2-report claims

| Claim | Check |
|---|---|
| "No denial weakened" | **FALSE.** Mutation: `engagement._match` made to always return in-scope, run over the 7 module and gate test files. **211fa0c catches it in 17 tests; 2e83105 in only 13.** These 4 now pass with scope enforcement gone, because they never arm and the RF gate refuses instead: `test_wifipent::test_out_of_scope_blocked`, `test_blepent::test_out_of_scope_blocked`, `test_zigbee::test_inject_out_of_scope_blocked`, `test_proxmark::test_active_op_blocked_out_of_scope`. Fix: arm in each and assert the scope reason (`"scope" in why`). |
| The 16 tests that now arm first | Re-read all 16 hunks. Arming only makes a test more permissive, so every refusal asserted after the arm still proves its own reason. None of these was weakened. `test_forge_proxmark_write…` is stricter, as the report says. |
| 56/59 fail before, 59 pass after | Matches `CL2-fix-evidence/before_dcb7c4f.txt` and `after.txt`. |
| N1 "wrappers / sh -c / look-alikes caught; unknown names fail closed" | **Overstated.** "Look-alike" here means a transmit-shaped name (`*siggen*`), not a homoglyph. Quoting, globbing, variables, interpreters and renamed binaries all pass (see N1). |
| N2 "Flipper verbs not on the non-RF list fail closed" | True, but `input` is on the non-RF list and can drive the Flipper UI into a Sub-GHz transmit (R4). |
| file:line refs (12 sampled) | All correct. |
| Suite / pyflakes figures | Reproduced; see below. |

## New findings (not in N1–N9)

| # | Sev | Finding | Fix |
|---|---|---|---|
| **R1** | **Medium** | **N1 bypass through a shipped free-text path.** DEVTERM SSH (`devterm.py:138`) wraps operator text in `ssh`. rfemit treats `ssh` as a plain program, so it scans only for literal names: shell quoting gets an SDR TX command past it when the in-scope host is the device itself (`127.0.0.1`, or its own LAN IP inside a scoped /24). The same path also skips the RF hard lock for a remote `aireplay-ng` (issued under `SUITE_TX_LOCK=1` and disarmed). | Make it structural, not a name match. `engagement.issue` accepts only an **allowlist** of argv[0] programs (the engagement tools the suite ships), and refuses shells, interpreters and `ssh` with free text. For DEVTERM SSH, either refuse loopback and own addresses and treat the remote command as an RF emitter of unknown class (fails closed under lock or disarm), or have the owner decide that remote-host TX is outside txguard. |
| **R2** | **Medium** (test integrity) | 4 out-of-scope refusal tests no longer test scope (step 3 above). | Arm, then assert the scope reason. |
| **R3** | **Low** (latent) | rfemit defaults unknown programs to non-RF. Real emitters it misses (none is invoked by shipped code today): rpitx `tune`/`sendook`/`pocsag`/`pisstv`/`pichirp`/`spectrumpaint`; UHD `tx_waveforms`/`tx_bursts`; `urh_cli`; `sdrangelsrv`; `meshtastic`; BT `l2ping`, `rfcomm`, `hciconfig leadv`; `ubertooth-btle`; `btlejuice`; nRF24 `jackit`/`mousejack`; `wpa_supplicant`; `airgeddon`, `eaphammer`, `wifiphisher`; `minimodem --tx`; `direwolf`; libnfc `nfc-mfsetuid`, `mfoc`, `nfc-relay-picc`. | The R1 allowlist closes this too: an unknown program is refused, not treated as non-RF. |
| **R4** | **Low** | Flipper `input send …` is classed as non-RF, so it is issued under `SUITE_TX_LOCK=1`. It can press buttons to open Sub-GHz and replay a saved signal. | Remove `input` from `FLIPPER_NON_RF`. |
| **R5** | **Low** (already labelled) | `lf_t55_write` can write any HID or EM ID through raw blocks, so it is a clone with no identity binding; the trail says "label-only". | This is owner open question 2 in CL2-report. I recommend refusing it, or decoding the block 0–2 content into an ID. |
| **R6** | **Low** (latent) | `txguard.issue_ticket` does not cross-check the argv against what it authorized. `issue_ticket("replay", [hackrf_transfer … -f 1090000000 -x 47], freq_hz=915e6)` **was issued**. Every shipped caller builds the argv from the same freq, so this is latent. | In `issue_ticket`, parse `-f`, `-s` and `-x` from a hackrf argv and require them to equal the authorized frequency and sample rate, and the gain to be at most the cap. |
| **R7** | **Info** | The hub nonce sits in the child's environment, which is readable by the same user (`/proc/<pid>/environ`). The same user can also write the state file, so this adds no exposure; it is outside the threat model. | None. |

## Suite, lint

```text
$ QT_QPA_PLATFORM=offscreen python -m pytest -q tests     # Py 3.12, fresh venv: PySide6 pyqtgraph flask numpy, macOS
FAILED tests/test_audit_tiles.py::test_undecodable_tile_is_marked_failed            # known main failure
FAILED tests/test_hwlab.py::test_doctor_hwbench_check - assert (None is True)       # env: also fails on dcb7c4f (pre-fix)
FAILED tests/test_sstvdec.py::test_iss_passes_use_their_own_tle_and_leave_weather_cache_alone   # known: no skyfield
3 failed, 1043 passed, 14 skipped in 253.17s
```
```text
$ pyflakes rfemit.py executor.py engagement.py txguard.py gatestate.py proxmark.py netpent.py replay.py bench.py \
    hwlab.py loopback.py palisade_qt/bench_app.py tests/test_cl2_fix.py
(no output, rc=0)
```
The implementer's 1044 passed + `test_hwlab` matches: it fails here on `dcb7c4f` too, so it comes from this fresh venv's
missing optional deps, not from CL2-fix. **No CL2-fix regression in the suite.** Not run on Python 3.13 or on the uConsole. No renders: this audit changed no UI, and CL2-fix's own renders
(`CL2-fix-renders/`) cover the touched pages.

## Stage → model

| Stage | Model |
|---|---|
| Gate analysis, probes, mutation test, every verdict | session model (Opus 5.5), inline |
| Suite / pyflakes | run directly in the shell (no model stage) |
| Subagents | none |

## Open questions (owner)

1. **R1:** should a command run over SSH on a target host count as the suite radiating (RF lock and txguard
   apply), or is it outside PALISADE's TX gate? Either way, the device's own address should not be an SSH
   target that sidesteps txguard.
2. **R5:** refuse `lf_t55_write`, `hf_mf_restore` and `hf_iclass_clone`, or keep them label-only?

**DO NOT MERGE.** R1 (N1 PARTIAL) and R2 block the merge. The rest can follow in a later cluster.
