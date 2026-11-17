# N-op1 report — SYSTEM › SETTINGS saves the operator the engagement gate reads

Branch `fix/n-op1-operator` (off main 1bc8ad1). Severity High, v0.1 blocker (PLANNER-HANDOFF item 8).

## Defect
`palisade_qt/system.py` `_save_settings` wrote the Operator field as `callsign` into
`palisade_ui.json`. `engagement._profile_operator()` reads `operator.json` via
`opprofile.load(suite.settings)`. So no engagement could be opened from the UI ("no operator
profile"), and the save message falsely said "persisted: operator". Present on main and fix/cl8-ship.

## Fix (UI/settings side only; engagement.py, opprofile.py, txguard untouched)
| Item | Where | Test |
|---|---|---|
| New `_write_operator(text)` writes `operator.json` through `suite.settings("operator", opprofile.DEFAULTS)`: valid ham call → `callsign` (upper, name kept); other text → `name`, callsign cleared (so the engagement records exactly what was typed); empty → both cleared | `palisade_qt/system.py` `_write_operator` | `test_saving_a_name_in_settings_opens_an_engagement`, `test_saving_a_callsign_in_settings_opens_an_engagement`, `test_typed_name_replaces_an_older_callsign_identity`, `test_clearing_the_operator_refuses_engagements_again` |
| Only `callsign`/`name` written; `tx_enabled` (absent/True/False/"yes"), grid, authorization untouched; `opprofile.tx_settings` unchanged | same | `test_save_never_touches_tx_enabled_or_other_keys[*]` |
| Operator no longer written into `palisade_ui.json` | `_save_settings` | `test_operator_is_no_longer_written_to_the_ui_store` |
| Honest message: "operator saved: callsign X" / "operator saved: name X (not a valid ham callsign — engagements OK, TX needs a callsign)" / "operator cleared — engagements will be refused" (warn) / "operator NOT saved" (warn) | `_save_settings` | `test_save_message_is_honest_when_no_operator_store` |
| Prefill round-trips | `_prefill_settings` (unchanged) | `test_settings_prefill_round_trips` |
| Empty profile still refused by the real gate | `engagement.start` (unchanged) | `test_empty_profile_refuses_engagement` |

Tests use the REAL `engagement._profile_operator` (conftest stubs it globally; the test file restores
the real one). New conftest autouse fixture redirects `suite.CFG` to a per-test temp dir, so no test
writes the developer's real `~/.config/uconsole-suite` (same pattern as the CL3 `DATA` redirect).

Regression proof: on main's `system.py` 7 of 12 new tests fail; the 5 that pass are guards (empty
refused, tx_enabled untouched ×4) that must hold both before and after.

## Notes / not fixed
- A stale `callsign` key may remain in existing `palisade_ui.json` files; nothing reads it.
- SETTINGS prefill is read at page build; if the profile is edited elsewhere afterwards (legacy Tk
  Operator Profile), SAVE overwrites callsign/name with the field. Low; same as other fields.
- Changing the operator mid-engagement does not change the open engagement (operator is recorded
  at open). Unchanged behaviour.

## Renders (1280×720, live, after SAVE with "DALTON")
`plan/briefs/N-op1-renders/before-settings-save-{dark,sun}.png` (main: "persisted: operator, theme")
`plan/briefs/N-op1-renders/after-settings-save-{dark,sun}.png`

## Suite
`QT_QPA_PLATFORM=offscreen xvfb-run -a python -m pytest -q tests` (Python 3.13 venv, PySide6, no tkinter) at 7257a97: **2 failed, 1490 passed, 7 skipped, 7 errors** — all baseline (test_audit_tiles undecodable tile, test_hwlab doctor hwbench, test_shell ×7 no tkinter). New: tests/test_n_op1_operator.py 12 passed.

pyflakes on changed files: clean.
