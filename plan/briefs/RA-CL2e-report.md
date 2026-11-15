# RA-CL2e — scoped cold re-audit of CL2-fix4 (`fix/cl2-gates` @ `a0a7f7e`)

**Auditor:** a fresh headless session, Opus 5.5. Worktree `../wt-RA-CL2e`; the shared checkout was not touched.
**Probes:** `RA-CL2e-evidence/ra_cl2e_poc.py` → `ra_cl2e_poc.json`. This Mac's real addresses and hostname are redacted in every evidence file.
**Safety:** nothing radiated. No ssh connection was made for D1, D2 or D3 (`ssh -G` only). The RA-CL2c/RA-CL2d PoC reruns only reached unreachable targets. Payloads were `touch` markers under `/tmp/ra_cl2e_x`.

## Verdict: **MERGE.** D1, D2 and D3 are closed. No bypass to execution on this device, no bypass to emission, and no weakened denial.

## Per item

| ID | Verdict | Evidence |
|---|---|---|
| **D1** host → shell, via the terminal launch and `prepare_ssh` | **CLOSED** | **Fuzz:** 1,112 host strings, made from 8 templates (scope middle/head/tail, bracketed scope, IPv4 head/tail, hostname, after `]`) × all of ASCII 0x00–0x7F and 11 Unicode lookalikes (NEL, NBSP, LS, U+2212, full-width `$` `;` `0`, Arabic-Indic 0, `²`, dotless ı, Kelvin K). Scope `fe80::/64` + `192.0.2.0/24`. **No accepted host contains a shell metacharacter, quote, `$`, backtick, redirect, glob, `~`, `{}`, `!`, `#`, `=`, `\` or `%%`.** The only accepted strings with a character outside `[A-Za-z0-9.:%_\-\[\]]` have Python whitespace at the very start or end. The gates validate `host.strip()`, and both real callers pass the stripped value to the argv (`devterm.py:776` → `786`/`796`; `prepare_ssh` `h = str(host).strip()`, `:285`). An embedded `\n` (`fe80::2%en0\nid`) is refused. **Named cases** (`d1_named`): every RA-CL2d PoC host (`;`, backtick, `$()`, `&&`) is now refused by both `authorize_ssh_host` and `prepare_ssh`, as are `\|`, `<`, `>`, quotes, `*`, `?`, `~`, `{a,b}`, `#`, `!`, `=`, `%en0%x`, a bare `%`, `%%en0`, a 16-char scope, `%-oProxyCommand`, `%-F` and `[[…]]`. A 15-char scope, `%7` and `%en0.5` are accepted. **Terminal argv:** for every accepted host and for xterm, kitty, x-terminal-emulator, konsole, alacritty, gnome-terminal and xfce4-terminal, the argv after `-e` is exactly `["ssh", "--", host]`, so argc after `-e` is ≥ 3 (min = 3). In xterm-412 `main.c:2492`, `command_to_exec = argv + n + 1` (everything after `-e`). The `$SHELL -c` fallback at `main.c:5380` runs only when `command_to_exec[1] == NULL`, so it cannot fire. The source was fetched with `brew fetch -s xterm` and read. **lxterminal:** the `-e` string was split with the **real GLib 2.88 `g_shell_parse_argv`** (a compiled helper). It gives `["ssh", "--", host]` for every accepted, stripped host (e.g. `ssh -- '[fe80::2%en0]'`). As defence in depth, `sh -c` over every accepted stripped host produced no marker and no token change. **xterm itself was not run:** brew has xterm but no X server (no Xvfb formula), and XQuartz needs a system install, which `CLAUDE.md` forbids. Tests: `test_d1_*` (all pass). |
| **D2** `64:ff9b:1::/48` | **CLOSED** | Refused by both `prepare_ssh` and `authorize_ssh_host`: `::7f00:1`, `::` (0.0.0.0), `::<own4>`, `64:ff9b:1:ffff:ffff::7f00:1`, `[64:ff9b:1::7f00:1]` and `…7f00:1%en0`. Allowed: the foreign `::808:808` and `::c000:20a`. Regression: `64:ff9b::7f00:1` is refused and `64:ff9b::808:808` is allowed. Tests: `test_d2_*`. |
| **D3** scoped HostName | **CLOSED** | Run with real `ssh -G` on OpenSSH 10.5p1 for `fe80::2%en0`, `[fe80::2%en0]`, `%lo0` and `%7`. The argv has `HostName=fe80::2%%en0`, rc = 0, no stderr, and `hostname fe80::2%en0` comes back intact. `%7` resolves to the interface name. Tests: `test_d3_*`; the `ssh -G` test ran and was not skipped. |

## New findings (none block)

| # | Sev | Finding | Suggested follow-up |
|---|---|---|---|
| E1 | Low | `_embeds_v4` reads only the low 32 bits. Under the RFC 6052 **/48** layout, `64:ff9b:1:7f00:0:100:808:808` embeds `127.0.0.1` (bits 48–63 and 72–87) and is **issued** (`d2_extra.txt`). A /48 local-use NAT64 would translate it on the **gateway**, not on this device, so this is the same class as D2 (Low). | Refuse `64:ff9b:1::/48` unless the low 32 bits hold the IPv4 *and* bits 32–95 are zero, or refuse the /48 outright. |
| E2 | Info | `authorize_ssh_host` validates `host.strip()`, but `_terminal_argv(term, host)` uses whatever string the caller passes. It is safe today because the only caller strips first (`devterm.py:776`). If an unstripped value were passed, the only effect is an extra empty argv element (whitespace only; no execution). | Have `authorize_ssh_host` return the canonical host and use that in the argv. |
| E3 | Info | `[fe80::2%en0]` and `[fe80::2]` are **refused** by `authorize_ssh_host` (the engagement matcher does not strip brackets) but **issued** by `prepare_ssh`. This fails closed, so it only affects function. | Unbracket before `authorize_action`. |
| E4 | Info | gnome-terminal and xfce4-terminal take `-e` as a single string. `[term, "-e", "ssh", "--", host]` will not open ssh there (gnome-terminal treats the text after `--` as the command). This affects function only; the host whitelist leaves nothing to inject. Neither terminal is the default on the uConsole (`lxterminal` is first). | Use `--` for gnome-terminal and `-x` for xfce4-terminal. |

## Regression (item 3)

| Check | Result |
|---|---|
| `tests/test_cl2_*.py` (Py 3.12.16, macOS, offscreen) | **259 passed** (`cl2_tests.txt`). The real `ssh -G` D3 test ran. |
| Full suite (Py 3.12.16, macOS, offscreen) | **`3 failed, 1169 passed, 14 skipped`** (`suite_py312.txt`). The 3 failures are the known baseline ones (`audit_tiles`, `hwlab` env, `sstvdec` skyfield), the same as RA-CL2c and RA-CL2d. That is +36 passing vs RA-CL2d, which is the 36 tests in `test_cl2_fix4`. |
| pyflakes `devterm.py tests/test_cl2_fix4.py ra_cl2e_poc.py` | Clean, rc = 0. |
| RA-CL2c PoCs rerun (`poc`, `poc2 <own en0 LL>`) | Both rc = 0. Ignoring the address/hostname redaction labels, the outputs are **identical** to RA-CL2d's reruns. `issued:true` counts are unchanged (5 / 3). `refused:true` went 30 → 38: this Mac has more interfaces today, and every own address is refused (`rerun_ra_cl2c_poc*.json`). |
| RA-CL2d PoC rerun | rc = 0. Every non-label change went from **passes/authorized to refused**: the 4 `d1_ssh_open` hosts, `fe80::2%;touch…` and `fe80::2%en0\|touch` in `c1_host`, and `64:ff9b:1::127.0.0.1` in `c2c3`. The other changes are only reworded refusal reasons (`a@b`, `ssh://`, en dash). **Nothing went from refused to issued** (`rerun_ra_cl2d_poc.json`). |
| Denial assertions vs `f44d1b7` | `git diff f44d1b7 -- tests/` adds only `tests/test_cl2_fix4.py` (+144, 0 lines removed). In code, every gate change is stricter: `_HOST_TOKEN` / `_SCOPE_ID` refusals are added before `authorize_action`; `_V4_EMBED` gains a prefix, and the predicate `pre != "64:ff9b::/96"` → `not pre.startswith("64:ff9b")` is equivalent on the old set; the HostName `%` is escaped; the terminal argv no longer carries one command string. |

## CL2-fix4 claims

| Claim | Check |
|---|---|
| D1 / D2 / D3 CLOSED, with the named tests | True, as above. |
| "Not run: Py 3.12 on the Mac, xterm itself" | Py 3.12 has now been run here. xterm still has not been run (no X server); its exec path was verified from the xterm-412 source instead. |
| Fail-first 17 failed / 19 passed on `f44d1b7` | Not re-run (the change is test-additive only). |

## Stage → model

| Stage | Model |
|---|---|
| Gate analysis, fuzz design, xterm source read, every verdict | Session model (Opus 5.5), inline |
| Suite, pyflakes and PoC reruns | Run directly in the shell; no subagents |

## Open questions (owner)

None blocking. E1–E4 are optional follow-ups for a later cluster.

**MERGE.**
