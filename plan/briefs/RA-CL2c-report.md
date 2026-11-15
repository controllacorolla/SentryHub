# RA-CL2c — final cold re-audit of CL2 (`fix/cl2-gates` @ `35ba0ef`)

**Auditor:** a fresh session, Opus 5.5. Worktree `../ra-cl2c`; the shared checkout was not touched.
`CL2-report.md` was read only at step 3. Probes are in `RA-CL2c-evidence/` (`ra_cl2c_poc.py`, `ra_cl2c_poc2.py` and their `.json`).
No probe radiated: every spawn went to a `sleep` stand-in. The one OpenSSH execution check used a throwaway user `sshd` on this Mac and `touch` as the payload.
This Mac's real addresses and hostname are redacted in the evidence.

## Verdict: **DO NOT MERGE.** The DEVTERM SSH command text is parsed as **ssh options**, so it runs a local program on this device, under the hard lock and disarmed.

## Per item

| ID | Verdict | Evidence |
|---|---|---|
| **R1** allowlist (`engagement.program_allowed`) | **CLOSED** | Every RA-CL2b bypass is refused through the gate (`test_cl2_fix2` RA_BYPASSES). My extra argv[0] forms were all refused: `NMAP`, `nmap\x00`, `nmap​`, `nmap.exe`, `./nmap`, `b"nmap"` and empty. Shells, interpreters and wrappers are refused, and a module with no `ALLOWED_PROGRAMS` is refused. `r1c_allowlist` |
| **R1** DEVTERM SSH | **OPEN (blocking)** | **The self-target check holds:** `127.0.0.1`, `127.8.9.10`, `::1`, `[::1]`, `::ffff:127.0.0.1`, `0.0.0.0`, `::`, `localhost`, `LocalHost.`, this host's own `.local` name, its LAN IPv4, its global IPv6 and its unscoped link-local are all refused. A failed interface listing fails closed (test). `127.1`, `0x7f000001`, `2130706433`, `0177.0.0.1` and `0` are refused as invalid. **The bypass:** OpenSSH re-parses options that come *after* the destination unless `--` comes before it. `prepare_ssh("192.0.2.10", "-oKnownHostsCommand=<anything>")` is **issued and spawned** with `SUITE_TX_LOCK=1` while disarmed (`r1a_ssh_option_injection`). Each of `-oKnownHostsCommand=…`, `-F<file>` (with `Match exec`), `-oPKCS11Provider=<.so>` and the bundled form `-GoKnownHostsCommand=…` was issued. **Local execution was confirmed** on OpenSSH 10.5: the exact issued argv with `-F/tmp/cfg` (`Match exec "touch …"`) created the marker on this device **before any connection**, with the target unreachable. `KnownHostsCommand` against a reachable sshd also created the marker, even though authentication failed. The payload can be `/bin/sh -c "hackrf_trans''fer -f 1090000000 …"`, which is exactly the RA-CL2b R1 PoC again, reached through Tk DEVTERM `devterm.py:753`. `ProxyCommand=none` does hold, because the first value wins. |
| **R2** weakened tests | **CLOSED** | The 4 tests now arm and unlock, then assert the scope reason and an in-scope positive. My own mutation (`engagement.check`: `if not ok` → `if False`, 14 gate test files) is caught by **22** tests, above the 17 required (`mutation_all_in_scope.txt`). |
| **R4** Flipper `input` | **CLOSED** | `input` in any case or with leading whitespace is classed `serial-rf` and refused under the lock. `loader`, `js`, `subghz`, `nfc`, `rfid` and `bt` are refused too. A CR-chained line is refused by `prepare_command`. |
| **R5** label-only | **CLOSED** | With the gate armed, all 3 ops show `binding=label-only` in **trail and ticket**. The UI shows LABEL-ONLY (`palisade_qt/forge.py:61`, `recon.py:141`). `ra_cl2c_poc2.json` `r5` |
| **R6** frequency binding | **CLOSED** (frequency) | 17 argv forms. Refused: 1090 on a 915 authorization, `-f1090…` attached, two `-f`, `--`, `--freq=`, `+915…`, full-width digits, `915e6`, `-a`, `-c`, a positional token, a path as argv[0], and `sudo`. Issued: an exact match, a leading zero and `-t -f -f 915…`; each matches how hackrf getopt reads the value. Digimodes is refused (the owner keeps it refused until CL8). |

## Regression sweep (step 2)

| Check | Result |
|---|---|
| RA-CL2 PoCs (`ra_cl2_poc*.py`) | All PASS (`rerun_ra_cl2_poc*.txt`). |
| RA-CL2b PoCs | Every probe that was closed still HOLDs. There are 2 BREAKs, and both are expected. (1) "SSH remote deauth ignores RF lock" is owner decision R1: a remote command is label-only. (2) "rfemit misses emitters" is unchanged by design, because the allowlist now refuses those tools at the gate. |
| Denial assertions vs `18770be` | Only strengthened: scope reason plus in-scope positive. Digimodes changed from allow to refuse. |
| Denial assertions vs `main` | I sampled the removed deny-asserts: engagement start refusals, protected bands, bench conducted, keyed-once. Each is still present with a different operator or call path, or is stronger. None was found weakened. |
| Suite (Py 3.12, fresh venv, macOS) | `3 failed, 1108 passed, 14 skipped`. The 3 are the known baseline failures (`audit_tiles`, `hwlab` env, `sstvdec` skyfield). This matches CL2-report. |
| pyflakes (13 touched modules + 6 tests) | Clean, rc=0. |

## CL2-report claims (step 3)

| Claim | Check |
|---|---|
| R1 DEVTERM SSH CLOSED | **False.** Option injection, above. |
| 54/65 new tests fail on `18770be` | True (`before_18770be.txt`). |
| R2 17 catch, R4, R5 trail/ticket/UI, R6 | True. |
| file:line refs (`engagement.py:648`, `devterm.py:177`, `txguard.py:443/502`, `rfemit.py:55`) | All correct. |
| "Found, not fixed" (-s/-x not bound, SSH self check only at issue, Linux getifaddrs not run) | Accurate. |

## New findings

| # | Sev | Finding | Fix |
|---|---|---|---|
| **C1** | **High (blocks)** | `prepare_ssh` puts operator text after the host with no `--`, so OpenSSH parses it as options. It executes on this device (`KnownHostsCommand`, `-F` + `Match exec`, `PKCS11Provider`) past the allowlist, the RF lock and the kill switch. | Build `ssh … -o ProxyJump=none -- <host> <cmd>`. Verified: with `--`, `-G` shows no `knownhostscommand`, and the `-F` marker was not created. Also refuse a `cmd` whose first character is `-`. Test: each of the 4 PoC tokens is refused, or is not parsed as an option (`ssh -G` check). |
| C2 | Low (latent) | `_self_target` compares a **scoped** IPv6 (`fe80::x%en0`) with unscoped own addresses, so this device's own scoped link-local passes and is issued (`poc2`). Today only ssh's `%` expansion stops it (`HostName=…%en0` → `percent_expand: failed`). Without the `%` expansion, sshd on this device was reached. | Compare with the scope id stripped (`ipaddress.ip_address(str(ip).split('%')[0])`). |
| C3 | Low | `::127.0.0.1` (IPv4-compatible), `::ffff:0:127.0.0.1` and `64:ff9b::7f00:1` are not refused. On macOS they did not reach this device (timeout). **Not checked on Linux or the uConsole.** | Refuse `::/96`, `::ffff:0:0/96` and `64:ff9b::/96` that embed loopback or own addresses, or refuse those prefixes outright. |
| C4 | Low (latent) | `rfemit._payload_class` classifies a multi-line Flipper payload by its first verb, so `led r 0\rsubghz tx …` → non-RF. The only shipped minter (`flipper.prepare_command`) refuses control characters first. | Fail closed (`serial-rf`) on any control character inside the payload. |
| C5 | Low | R6 does not bind `-x` to the power cap: `-x 47` issued at a 0 dBm cap. This is already listed in CL2-report. | Follow-up, as RA-CL2b R6 recommended. |
| C6 | Info | The Flipper verbs `update` (`install`) and `storage` (`write`) are non-RF and issue under the lock. They can stage firmware or a `.sub` file, but do not key RF themselves. | Owner's call. |

## Stage → model

| Stage | Model |
|---|---|
| Gate analysis, probes, OpenSSH execution check, mutation, every verdict | Session model (Opus 5.5), inline |
| Suite / pyflakes / PoC reruns | Run directly in the shell; no subagents |

## Open questions (owner)

1. C1 fix: `--` alone, or also refuse a remote command that starts with `-`? I recommend both.

**DO NOT MERGE.** C1 is a bypass to local execution, and so to emission. Everything else holds; C2–C6 are follow-ups.
