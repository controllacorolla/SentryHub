# RA-CL2d — scoped cold re-audit of CL2-fix3 (`fix/cl2-gates` @ `b711b57`)

**Auditor:** a fresh headless session, Opus 5.5. Worktree `../wt-RA-CL2d`; the shared checkout was not touched.
Probes: `RA-CL2d-evidence/ra_cl2d_poc.py` → `ra_cl2d_poc.json`. This Mac's real addresses and hostname are redacted.
Nothing radiated. Every ssh target was unreachable (TEST-NET `192.0.2.10`, or the foreign link-local `fe80::2`). Every payload was a `touch` marker under `/tmp/ra_cl2d_x`.

## Verdict: **DO NOT MERGE.** Operator text in the DEVTERM **host** field runs a local shell command on this device through the "open terminal" path when the terminal is `xterm` (D1). The fix3 changes (C1–C4) hold.

## Per item

| ID | Verdict | Evidence |
|---|---|---|
| **C1** ssh option injection (`prepare_ssh`) | **CLOSED** | Run against real OpenSSH 10.5p1. **Refused at issue:** `-oKnownHostsCommand…`, `-GoKnownHostsCommand…`, `--`, `-- -F…`, an empty or all-space command, and a `-` after a leading space, tab, LF, CR or NBSP (`str.lstrip` covers Unicode whitespace). **Issued:** an en dash, a minus sign (U+2212), a full-width hyphen, `uname -F<cfg>`, `uname\n-F<cfg>` and `uname\r-oKnownHostsCommand=…`. For every issued argv, `ssh -G` shows no injected `knownhostscommand`, `pkcs11provider`, `localcommand` or `proxycommand`. Running the real argv created **no** `Match exec` or KnownHostsCommand marker (`c1_cmd`). The text after `--` is the remote command only, so it runs on the target and is label-only. **Host token:** a leading `-`, whitespace, `@`, `:port`, `ssh://`, `%h`, an en dash, `v4%x` and an embedded LF are all refused. `[v4]` is unwrapped (`c1_host`). Test: `test_c1_*` (incl. real `ssh -G`, which ran here and was not skipped). |
| **C2** scoped own link-local | **CLOSED** | `own_addresses()` on macOS returns 14 addresses, all **unscoped** (8 link-local). `_canon` strips the scope on both sides. Refused: own LL scoped, own LL unscoped, own LL with a wrong scope (`%lo0`) and `[own LL%en0]`. All 7 own link-locals pass the RA-CL2c PoC, scoped and unscoped (`rerun_ra_cl2c_poc*.json`). Foreign `fe80::2%en0` passes. Test: `test_c2_*`. |
| **C3** embedded IPv4 | **CLOSED** | Refused: `::127.0.0.1`, `::7f00:1`, `::<own4>`, `::8.8.8.8` (the whole `::/96` range), `::ffff:0:127.0.0.1`, `::ffff:0:<own4>`, `::ffff:0:8.8.8.8` (the whole range), `64:ff9b::127.0.0.1`, `64:ff9b::<own4>`, `64:ff9b::`, `::ffff:127.0.0.1` and `::ffff:<own4>`. Passes: `64:ff9b::808:808`, a real NAT64 remote. Test: `test_c3_*`. |
| **C4** Flipper control bytes | **CLOSED** | Classed `serial-rf`: a CR chain, an LF chain, NUL, TAB, ESC, DEL, a leading CR, a leading LF before a read, `device_info\r\r\nsubghz tx`, `^C` + verb, and raw `0x9b`. **Still non-RF:** `device_info\r\n`, `led r 0\r`, `storage list /ext\r\n` and a trailing `\r\n\r\n`. UTF-8 NEL (U+0085), LS (U+2028) and raw `0x85` stay non-RF (`led …`). The Flipper CLI splits lines only on CR/LF, so these do not chain. Test: `test_c4_*`. |
| C5 / C6 | Unchanged (DEFERRED / owner) | As reported in RA-CL2c. |

## New finding

| # | Sev | Finding | Fix |
|---|---|---|---|
| **D1** | **High (blocks)** | `devterm.py:768` "open terminal" builds `[term, "-e", "ssh %s" % host]` for `lxterminal`/`xterm`. That is **one string**. When `execvp` of a single `-e` argument fails, xterm runs `$SHELL -c <string>`. Source: xterm `main.c` `spawnXTerm`, `if (command_to_exec[1] == NULL) execlp(shell_path, shname, "-c", command_to_exec[0], …)`. The host is only checked by `_self_target` (no leading `-`, no whitespace) and `authorize_action`. Python's `ipaddress` accepts **any** IPv6 scope id except `/` and `%`, and the engagement matcher ignores the scope. So with an in-scope link-local engagement (e.g. `fe80::/64`), the hosts `fe80::2%;touch$IFS.m`, ``fe80::2%`…` ``, `fe80::2%$(…)` and `fe80::2%en0&&…` are all **authorized** (`d1_ssh_open`). `sh -c 'ssh fe80::2%;touch$IFS.ra_cl2d_marker'` **created the marker on this Mac** with the target unreachable. The payload can be any local program (`hackrf_transfer …`), past the RF lock and the allowlist. This is the same class as RA-CL2c C1. Existing code (since `57616f1`, not fix3), but it falls under brief item 1 ("a host token with `%`"). **Limits:** the host must be in the engagement scope, and the terminal must be xterm. `term_launcher()` picks `lxterminal` first, and lxterminal parses `-e` with `g_shell_parse_argv`, which does no expansion. xterm itself was **not run** here (not installed on this Mac); the shell step was run with `/bin/sh`. | (1) In `_self_target`, allow a scope id only if it matches `[A-Za-z0-9_.-]{1,15}` (an interface name), or refuse scoped hosts and resolve the scope from the interface. (2) Never hand a terminal one command string: use `[term, "-e", "ssh", "--", host]` for xterm, and `shlex.quote` the host for lxterminal's string form. Test: each D1 host is refused by `authorize_ssh_host`, and the xterm argv has `len > 3` with `--` before the host. |
| D2 | Low | `64:ff9b:1::/48` (RFC 8215 local-use NAT64) with an embedded `127.0.0.1` passes `_self_target`. Translation happens on a NAT64 gateway, not on this device, unless the device runs its own CLAT/NAT64. | Follow-up. Optionally add it to `_V4_EMBED`. |
| D3 | Info | `prepare_ssh` puts a scoped host into `HostName=fe80::2%en0`. OpenSSH percent-expands HostName, so `%e…` fails (`percent_expand: failed`), and a scoped link-local remote cannot be reached by one-shot SSH. This is functional, not security: it fails closed. | Follow-up. Escape `%` as `%%` in HostName. |

## Regression (item 4)

| Check | Result |
|---|---|
| `tests/test_cl2_*.py` (Py 3.12.16, macOS) | `223 passed` (`cl2_tests.txt`). The real `ssh -G` test ran. |
| Full suite (Py 3.12.16, macOS, offscreen) | `3 failed, 1133 passed, 14 skipped`. The 3 are the known baseline failures (`audit_tiles`, `hwlab` env, `sstvdec` skyfield), the same as RA-CL2c. +25 passing tests from `test_cl2_fix3`. (`suite_py312.txt`) |
| pyflakes `devterm.py rfemit.py tests/test_cl2_fix3.py` + my PoC | Clean, rc=0. |
| RA-CL2c PoCs re-run | `ra_cl2c_poc.py` rc=0; `ra_cl2c_poc2.py <own en0 LL>` rc=0 (`rerun_*.json`). **Every outcome that changed went from issued to refused:** the 5 `r1a` ssh injections, `::127.0.0.1`, `::ffff:0:127.0.0.1`, `64:ff9b::7f00:1`, `fe80::1%lo0`, the scoped own link-locals (poc and poc2, every scope form). **Nothing went from refused to issued.** The other diff lines are only the redacted address labels. |
| Denial assertions vs `488f31e` | `git diff 488f31e HEAD -- tests/` adds only `tests/test_cl2_fix3.py` (168 lines). No assertion was removed or weakened. In code, the only gate change is stricter: `_self_target` gains `_canon` and `_embeds_v4`, `prepare_ssh` gains a refusal, and `_payload_class` gains a fail-closed branch. |

## CL2-fix3 claims

| Claim | Check |
|---|---|
| C1–C4 CLOSED, with the tests named | True, as above. |
| Fail-first 19 failed / 5 passed on `488f31e` | Not re-run (the diff is test-additive only). |
| "Not run: Py 3.12 on the Mac" | Now run here. |

## Stage → model

| Stage | Model |
|---|---|
| Gate analysis, OpenSSH probes, D1 discovery and confirmation, every verdict | Session model (Opus 5.5), inline |
| Suite / pyflakes / PoC reruns | Run directly in the shell; no subagents |

## Open questions (owner)

1. D1 fix shape: whitelist the scope id at `_self_target` (my recommendation, since it also covers `prepare_ssh` and the engagement trail), argv-form the terminal launch, or both. I recommend both.

**DO NOT MERGE.** D1 is a bypass to execution on this device. It is conditional (xterm, link-local in scope) but demonstrated.
