# RA-MESH — cold audit of MESH (full page) and ASSISTANT (local model), branch `fix/mesh-assistant` (PR #35)

**FRESH session, Opus.** Auditor only: a report, not fixes. Own worktree off
`origin/fix/mesh-assistant`. Read `CLAUDE.md`; items 17 and 18 of `plan/briefs/device-fix-plan.md`;
the "Device run 2" section of `plan/briefs/device-notes.md` (Dalton's words) — on `origin/docs/briefs`.
Dalton's decisions: MESH = "Full: map, nodes, chat, radio"; ASSISTANT = "Nah let's just use a local
model please" (local inference server on localhost, no API calls, no NET dependency, no engagement
data leaves the device).
Scope: `git diff origin/fix/ops-maps..origin/fix/mesh-assistant -- . ':!plan'` (Stages 1 and 2 are
audited separately).

The bar is Dalton's words. Render MESH and ASSISTANT at 1280x720 in DARK, LIGHT and SUN, live (no
radio, no Ollama: the honest empty / install states) and `--demo`, and look at them.

1. **MESH layout (18).** MAP / NODES / CHAT / RADIO sub-pages exist, use the subtab tiles, and each
   shows something real or an honest reason (no radio, meshtastic not installed, no position).
   Does the map place nodes with a position and say which have none? Node table columns readable at
   1280 (16 px floor)?
2. **MESH TX gate.** SEND goes through `mesh_dash.authorize_send` -> txguard on every send (re-checked
   in the worker at send time, not only when the button was enabled). Try to send with TX disarmed,
   with no link, with an empty or over-long message, to a DM target that vanished. Nothing routes
   around `txguard`/`engagement`. Messages logged to `mesh_dash.MSG_LOG`.
3. **MESH link worker.** `MeshLinkWorker`: connects TCP (meshtasticd) then serial; retries every 15 s;
   `run()` closes the interface and unsubscribes pubsub; nothing left running on close; no busy loop
   while disconnected; demo is static and never touches a radio. Alerts (new node, DM to me, battery
   < 20 %) not raised in demo, not duplicated.
4. **ASSISTANT local model (17).** Only localhost/127.0.0.1/::1 hosts are ever contacted (try to make
   it reach a non-local host via settings); goes through `netpolicy.urlopen` with an honest purpose;
   works with NET OFFLINE; no API key, no cloud path left anywhere. Streaming `/api/chat`, model pick
   from `/api/tags`, STOP cancels, an error never leaves ASK greyed. No Ollama -> an install hint, not
   a crash or a hang. What context is sent to the model (`live_summary`, `system_prompt`)? It stays
   on the device, but say what it includes.
5. Lifecycle (AskWorker, MeshLinkWorker stopped on close; no thread left) and UI-only elsewhere.
6. Run `tests/test_mesh_assistant.py`, `tests/test_palisade_qt.py`, `tests/test_cl4_honest.py`, one
   file per process (`QT_QPA_PLATFORM=offscreen xvfb-run -a python -m pytest -q --timeout=240
   --timeout-method=thread`). No full suite (the thread ran it).
7. Write `plan/briefs/RA-MESH-report.md` on `fix/mesh-assistant`: a table per item, new findings with
   severity and a PoC, then MERGE / DO NOT MERGE (only Medium or worse blocks; list Lows that are
   Dalton's call). Push (fetch + merge on reject, never force), remove the worktree.

Trailer: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` +
`Claude-Session: https://claude.ai/code/session_01DNwALRGvWXijhRVAnAZWYH`
