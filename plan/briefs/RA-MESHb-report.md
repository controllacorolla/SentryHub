# RA-MESHb report: targeted cold re-audit of the RA-MESH fixes (PR #35)

Branch `fix/mesh-assistant` at `e8b7a2a`. Scope: `git diff d92f8bc..origin/fix/mesh-assistant -- palisade_qt/mesh.py
palisade_qt/system.py tests/test_mesh_assistant.py` (fix commit `e98876d`). Auditor only: no code changed.

## Verdict: MERGE

M1 and M2 are fixed with regression tests and hold under probes. No new Medium. L2 is only partly fixed (N2, Low):
STOP / close work when the server has sent its headers, but real Ollama sends no headers until the first token, and
that wait is not broken. Lows are listed below for Dalton.

## Method

- Tests, one file per process (venv, xvfb + offscreen, `--timeout=240 --timeout-method=thread`):
  `tests/test_mesh_assistant.py` **16 passed**, `tests/test_palisade_qt.py` **123 passed**. pyflakes clean on the 3 files.
- Probes (scratch, not committed): the real `MeshLinkWorker` with the test file's `FakeIface` wired to a live
  `MeshPage` (node drop, 5 repeated lists, a node list read that raises, link lost + reconnect to a fresh node DB,
  send, re-pick, node returns). `AskWorker` run as a real thread against a loopback fake Ollama in two shapes:
  headers then 8 s delay ("body"), and 8 s delay before headers ("head", the shape of real Ollama on a cold model).
  The full live hub closed while an answer was pending, in both shapes.
- Renders at 1280x720, xvfb + xcb, DARK and SUN, live hub (no radio, no meshtastic; rows injected): MAP with 2 of 4
  nodes unplaced, MAP with no reference position, MAP with no node position at all, NODES; demo MAP and NODES.
  All looked at. No radio, no internet.

## Findings table

| ID | Was | Now | Evidence |
|---|---|---|---|
| **M1** DM falls back to everyone | Medium | **FIXED** | Probe: pick "DM Trail bike node", node drops -> stays selected as "DM !c3d4e5f6 (not in the node list now)"; 5 more lists -> still exactly 1 marked entry (combo is cleared and rebuilt each list, so none pile up); a list read that raises (`{}`) -> kept; link lost -> kept; reconnect to a fresh DB without it -> kept; SEND -> `sendText(..., "!c3d4e5f6")`, never `^all`. Pick another DM or "everyone" -> the marked entry is gone at the next list. Node returns -> plain "DM …" again, no mark. Test `test_ra_mesh_m1_…`. Label nit: N1 |
| **M2** map silent about unplaced nodes | Medium | **FIXED** | Renders: "3 node(s) on the map · no position reported: BIKE, HMB" (warn colour) beside the map; with own node unplaced and HOME unset the map shows the **NO REFERENCE POSITION** cover ("this radio reports no position and HOME is not set — set HOME in SYSTEM › SETTINGS") plus the side line; the cover clears when a position returns (probe). Readable at 1280x720 in DARK and SUN. Test `test_ra_mesh_m2_…`. Edge: N3 |
| L1 http_proxy | Low | not changed (as stated) | — |
| **L2** STOP / close before first token | Low | **PARTLY FIXED** (N2) | "body" shape: STOP -> `done " [stopped]"` in 0.0 s; a later ask answers normally; close joins in 0.0 s; nothing raised. "head" shape: STOP takes 7 s, close exceeds the 3 s join (hub close blocks 3.1 s, worker runs to 7.2 s). Nothing raised in either; a later ask works in both |
| **L3** new-node alert repeats | Low | FIXED | `_ever_seen` unioned; test drops and re-adds a node -> 1 alert |
| **L4** UTF-16 max length | Low | FIXED | UTF-8 byte check at SEND (200 B), text kept in the box, reason in the log ("too long: 400 bytes"). Residual: `setMaxLength(1000)` still cuts a >1000-char paste silently (cosmetic) |
| **L5** unreadable reason as link drops | Low | FIXED | `_iface is None` -> "no mesh link (it dropped): not sent"; the TX gate is still called for every message that reaches the radio |
| **L6** DIST/BRG off-screen | Low | FIXED | NODES render: all 8 columns visible at 1280, no scroll bar |
| L7 banner over node cluster | Low | GONE | Demo MAP render: Stage 2's strip is now the small "NO IMAGERY · NET OFFLINE ×" chip top-right; ME / BIKE / KAPA / HMB / GLDN labels all visible (the chip sits on the 15 km ring label; Stage 2's area, not MESH) |
| **L8** doubled "MESH · MESH" | Low | FIXED | chip text is now "link: …", so the notice reads "MESH · link: …" (code read) |
| **L9** live_context off ignored | Low | FIXED | `_live_context()` returns "" when assistant.json `live_context` is false (test). `live_summary` docstring ("nothing else") unchanged |
| **L10** 0.0.0.0 | Low | FIXED | `local_hosts` rewrites 0.0.0.0 to 127.0.0.1, so NET OFFLINE allows it (test) |

UI-only: yes (mesh.py / system.py page and worker code only; no decoding or radio behaviour change). TX gate: still
re-checked in `_drain_tx` at send time via `mesh_dash.authorize_send` for every queued message; the new L5 branch only
refuses. Lifecycle: no new threads; MeshLinkWorker / AskWorker stop paths unchanged except the new socket abort.

## New findings

### N2 (Low): STOP / close still wait for real Ollama's first token (L2 fixed only for a server that sends headers early)
`AskWorker._abort` shuts the socket under `self._resp`, which exists only after `urlopen` returns, i.e. after the
response headers arrive. Ollama's `/api/chat` loads the model (`scheduleRunner`) and starts streaming through gin's
`c.Stream`, which writes headers with the first chunk, so on a cold model (load + prefill on the CM5) `urlopen` itself
blocks and `_resp` is None: STOP does nothing and page close exceeds `MoreApp.stop`'s 3 s join. The regression test's
fake sends headers first, so it does not cover this shape.
PoC (scratch probe, loopback server that sleeps 8 s before `send_response`):
```
head: STOP at 1.0 s -> done " [stopped]" at 7.0 s
head: hub.close() returns after 3.1 s, AskWorker still running, finishes at 7.2 s (no exception)
body (headers first): STOP -> 0.0 s, close joins in 0.0 s
```
Fix idea: keep the socket from the connection (an `HTTPConnection` subclass that records `self.sock` in `connect()`,
or `http.client` directly) so `_abort` can shut it before headers; add the "head" shape to the test.

### N1 (Low): the kept DM target loses its name
`_nodes_in` sets `self._nodes = nodes` before building the marked entry, so `self._name(cur)` finds no node and the
combo reads "DM !c3d4e5f6 (not in the node list now)" instead of "DM Trail bike node (…)". Safe (the send still goes
to that node only) but the operator may not recognise the id. Fix: name it from the previous node list.

### N3 (Low): no node reports a position and there is no reference -> the line does not say the reference is missing
Own node without position, HOME unset, and no other node with one: no cover, line reads "0 node(s) on the map · no
position reported: KAPA, GLDN, BIKE, HMB" (render `sun_map_nobody`). Honest about the others, silent that this node /
HOME have no position either. Cosmetic.

### N4 (Low, pre-existing): a stopped answer is not marked in the log
`_on_ask` ignores the `done` row's text, so " [stopped]" never shows: after STOP before the first token the log shows
"> question" and nothing under it. The history keeps `assistant: " [stopped]"` when the read ends by EOF (socket shut)
but pops the question when it ends by exception; harmless, inconsistent.

## Lows for Dalton (none blocks)
N1, N2, N3, N4; L1 (unchanged); L4 residual (>1000-char paste cut silently); L9 docstring.

## Merge call
**MERGE** (MESH/ASSISTANT scope). M1 and M2 fixed with regression tests; no Medium or worse open.
