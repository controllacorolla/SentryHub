# RA-N-op1 — cold audit of N-op1 (`fix/n-op1-operator`)

Auditor: fresh session, Opus. Audited head `856c925` against `origin/main` `1bc8ad1`.
Scope diff: `palisade_qt/system.py`, `tests/conftest.py`, `tests/test_n_op1_operator.py` (+ author report).
Gate code `engagement.py`, `opprofile.py`, `txguard.py`, `gatestate.py`: **unchanged** (`git diff --stat` empty).
Env: Python 3.13 venv, PySide6, pyqtgraph, numpy, flask, no tkinter; `QT_QPA_PLATFORM=offscreen xvfb-run -a`.

## 1. Reproduction (main vs branch)
I drove the real SYSTEM › SETTINGS page: typed text in Operator, clicked SAVE, then called `engagement.start(...)`
with the **real** `engagement._profile_operator` (no conftest stub), using a temp `suite.CFG`/`suite.DATA` and a temp `$HOME`.

| Typed | main: message / operator.json / start | branch: message / operator.json / start |
|---|---|---|
| `DALTON` | "persisted: operator, theme" (**false**) / callsign "" name "" / **refused** "no operator profile" | "operator saved: name DALTON (…TX needs a callsign)" / name DALTON / **OK**, records `DALTON` |
| `kd0xyz` | same false claim / empty / refused | "operator saved: callsign KD0XYZ" / callsign KD0XYZ / OK, `KD0XYZ` |
| `N0CALL-9` (SSID) | refused | callsign `N0CALL-9` / OK, `N0CALL-9` (txguard CALL_RE accepts SSID; matches what was typed) |
| `  w1aw  ` | refused | callsign `W1AW` / OK, `W1AW` |
| `Dalton Smith` | refused | name `Dalton Smith` / OK |
| `   ` (whitespace) | refused | "operator cleared — engagements will be refused" (warn colour) / both empty / **refused** |

Defect reproduced on main and fixed on the branch.

## 2. Attacks on the fix
| Check | Result | Evidence |
|---|---|---|
| SAVE sets / flips / creates `tx_enabled` | **No.** Absent stays absent; True, False and "yes" are preserved byte-for-byte; `tx_settings` gives `tx_enabled` True only for a stored True (pre-existing), never because of the save | repro; `test_save_never_touches_tx_enabled_or_other_keys[None/True/False/yes]` |
| Other operator.json keys | grid, authorization, license_class: untouched. Unknown keys kept (`suite.settings` keeps extra keys). **Side effect (N1, Low):** wrong-typed default keys are written back coerced, e.g. `wsprnet_opt_in: "yes"` is saved as `False`. That is the more restrictive direction, and every reader already sees the coerced value on load | repro "wrongtype" |
| Old callsign shadowing a new name | Fixed. A profile with callsign KD0XYZ and name OLD, then typing `DALTON` and saving, gives callsign "" and name DALTON, so the identity is DALTON. Typing the callsign again restores KD0XYZ, keeps the name, and leaves `tx_enabled` alone | repro "shadow"; `test_typed_name_replaces_an_older_callsign_identity` |
| Case / whitespace / SSID | Upper-cased, stripped; SSID kept as typed. The engagement record equals the normalized typed text. Cosmetic **N2 (Low):** after saving `kd0xyz` the field still shows lowercase while the message and profile say `KD0XYZ` (see sun render) | renders |
| Empty / whitespace | Engagement refused; message warns | `test_clearing_the_operator_refuses_engagements_again` |
| Unwritable store | With `suite.CFG` unwritable, the message reads "operator NOT saved … · NOT persisted …: theme" in the warn colour, and `_profile_operator()` returns None. Nothing claims "saved". (A chmod read-only test was not meaningful here because the sandbox runs as root, so I used a non-creatable CFG path) | repro "unwritable"; `test_save_message_is_honest_when_no_operator_store` |
| Corrupt operator.json | `suite.settings()` (pre-existing, unchanged) moves the file to `operator.json.corrupt` and loads defaults when the page opens. The prefill is blank, and SAVE then writes the typed operator into a defaults profile. Fails closed: `tx_enabled` is absent, so TX stays off. The message does not mention that grid and authorization were reset by the corrupt-file recovery (**N3, Low**, pre-existing behaviour of `settings()`, now reachable from SAVE). The `.corrupt` copy is kept | repro "corrupt" |
| Invalid HOME | Returns before any write: "nothing saved". operator.json holds only the defaults that `settings()` already wrote at prefill (same on main) | repro "badhome"; existing `test_more_settings_persists_home_and_theme_no_false_save` |
| Other readers of `palisade_ui.json` `callsign` | None. `palisade_ui` is read only by `system.py` `_write_settings` and `eventbus.py` (HOME). Old files may keep a stale `callsign` key that nothing reads (author notes this) | `grep -rn palisade_ui` |
| conftest `suite.CFG` redirect | Safe. `settings()` resolves `CFG` at call time. Tests that set `CFG` themselves (`test_bughunt`, `test_data`, `test_shell`) override it later and keep their meaning. It is also *needed*: `test_more_settings_persists_home_and_theme_no_false_save` (demo=True, `N0CALL`) would otherwise write the developer's real operator.json | code read |
| Demo mode | SAVE in `--demo` writes the real operator profile. Only an explicit operator action can do this, and demo never pre-fills a fake identity (the prefill reads the real profile), so no identity is invented. Informational | code read |
| Mid-engagement change | The open engagement keeps the operator recorded at open; `_profile_operator` is read only in `start()` | `grep _profile_operator` |

## 3. UI-only rule and renders
No data/decoding/radio path is touched; the only store change is that the Operator field now goes to operator.json (the purpose of the fix).
Renders at 1280×720, live, after SAVE: `plan/briefs/RA-N-op1-renders/RA-N-op1-settings-{dark,sun}-{dalton,kd0xyz}.png`.
The message wraps to 2 lines on dark/DALTON and nothing is clipped. The layout is otherwise identical to main.
**N4 (Low, hygiene):** the author report cites `plan/briefs/N-op1-renders/{before,after}-settings-save-{dark,sun}.png`, but those files are on neither the branch nor `docs/briefs`. The DoD before/after screenshots are missing; the renders in this audit stand in for the "after" set.

## 4. Regression
- `tests/test_n_op1_operator.py`: **12 passed**.
- pyflakes on the changed files: clean.
- Diff of `tests/` against main: additions only, **no assertion removed or weakened**.
- Full suite at `856c925`: **2 failed, 1490 passed, 7 skipped, 7 errors**. All of these are the known baseline: `test_audit_tiles::test_undecodable_tile_is_marked_failed`, `test_hwlab::test_doctor_hwbench_check`, and `test_shell` x7 (no tkinter). The count matches the author report.

## New findings
| ID | Severity | Finding |
|---|---|---|
| N1 | Low | SAVE persists `suite.settings` type-coercion of wrong-typed default keys (e.g. `wsprnet_opt_in:"yes"` saved as False). Fails safe. |
| N2 | Low | Operator field is not normalized after SAVE (shows `kd0xyz` while `KD0XYZ` was saved). |
| N3 | Low | A corrupt operator.json gives "operator saved" with no note that the other profile fields were reset (pre-existing `settings()` recovery; `.corrupt` kept; TX off). |
| N4 | Low | Author's before/after renders are referenced but were never committed. |

No Critical, High or Medium findings. No gate is weakened, `tx_enabled` is never touched, engagements open from the UI, and there is no false "saved".

**Verdict: MERGE**
