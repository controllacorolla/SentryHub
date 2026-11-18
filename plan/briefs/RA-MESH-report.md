# RA-MESH report: cold audit of MESH (full page) and ASSISTANT (local model)

Branch `fix/mesh-assistant` (PR #35) at `3da5f47`. Scope: `git diff origin/fix/ops-maps..origin/fix/mesh-assistant -- . ':!plan'`
(mesh.py new, system.py ASSISTANT rewrite, shell/pages import, 3 test files). Auditor only: no code changed.

Bar: Dalton's words. MESH = "Full: map, nodes, chat, radio". ASSISTANT = "Nah let's just use a local model please".

## Verdict: DO NOT MERGE (2 Medium)

Both Mediums are small fixes. Everything else holds: the TX gate is re-checked in the worker on every send,
nothing routes around txguard, the link worker connects TCP then serial, retries every 15 s, closes and
unsubscribes on stop, demo is static, and the assistant reaches only loopback through `netpolicy.urlopen`
(no API key, no cloud path). The 3 test files pass.

## Method

- Renders at 1280x720, xvfb + xcb, DARK / LIGHT / SUN, live (no radio, no meshtastic, no Ollama) and `--demo`:
  MESH MAP / NODES / CHAT / RADIO and ASSISTANT with a question asked (24 frames, all looked at).
- Probes (scratch, not committed): stubbed `pubsub` + `meshtastic` modules and a stubbed `socket.create_connection`
  (nothing left the box, no radio), a loopback fake Ollama with a 12 s first-token delay, and live-hub page probes.

## 1. MESH layout (18)

| Check | Result |
|---|---|
| MAP / NODES / CHAT / RADIO exist, subtab tiles | PASS: four light-purple subtab tiles under the MESH module tile, all three themes |
| Live, no meshtastic | PASS: "NO MESH LINK: the meshtastic Python package is missing, re-run the installer (pip install meshtastic)" on the map cover and both tables; RADIO hero "NO LINK" with the fix; SEND greyed with the reason |
| No daemon / no USB (stubbed meshtastic) | PASS: "no meshtasticd on 127.0.0.1:4403 and no USB node: start meshtasticd … or plug in a node" |
| Demo | PASS: 5 nodes, solid vs dashed lines by hops, SNR colours, BIKE 18 % in warn colour, DM shown "→ me", RADIO card says DEMO, no radio |
| Map places nodes with a position | PASS (Q9: 3 of 5 plotted) |
| Map says which nodes have none | **FAIL: M2** |
| Node table readable at 1280, 16 px floor | PASS on font (18 px). Low L6: DIST / BRG are off-screen behind a horizontal scroll bar |

## 2. MESH TX gate

| Check | Result |
|---|---|
| SEND goes through `mesh_dash.authorize_send` -> txguard | PASS: GUI greys SEND with the gate's reason (`_refresh_gate`, every 2 s and on every row), and `_drain_tx` calls `authorize_send(settings, iface)` again for every queued message at send time, with the node's own region |
| TX disarmed | PASS: "SEND is off: TX gate: TX kill switch is OFF, arm it (TX slot) to transmit"; Enter / primary action logs "✕ NOT SENT: …" |
| No link | PASS: SEND greyed "no mesh link"; a send queued while the link drops is refused (reason text poor: L5) |
| Empty message | PASS: ignored (stripped) |
| Over-long message | PARTIAL: `setMaxLength(200)` counts UTF-16 units, not bytes (L4) |
| DM target that vanished | **FAIL: M1** |
| Nothing routes around txguard / engagement | PASS: the only `sendText` is behind `authorize_send`; demo never calls a radio ("(demo, not transmitted)") |
| Logged to `mesh_dash.MSG_LOG` | PASS: received and sent texts are appended (jsonl) |

## 3. MESH link worker

| Check | Result |
|---|---|
| TCP (meshtasticd) then serial | PASS (Q1): TCP probe 127.0.0.1:4403 first; with it refused and `/dev/ttyACM0` present, SerialInterface on that port |
| Retry every 15 s, no busy loop | PASS (Q1/Q4): `_next_try = now + 15`; 4 cheap steps in 2 s, 1 connect attempt |
| Link lost | PASS: iface closed, "mesh link lost, reconnecting", retry after 2 s |
| `run()` closes iface + unsubscribes pubsub | PASS (Q3): joined in 0.00 s, iface closed, both topics unsubscribed |
| Nothing left on close | PASS (Q10): 0 MeshLinkWorker running after hub close |
| Demo static, no radio | PASS: one emission, then only demo-TX drain |
| Alerts not raised in demo | PASS (test + probe: no MESH alert in demo) |
| Alerts not duplicated | PARTIAL: low battery once per node; new-node alert repeats when a node drops out of the list and comes back (L3) |

## 4. ASSISTANT local model (17)

| Check | Result |
|---|---|
| Only localhost / 127.0.0.1 / ::1 contacted | PASS: `local_hosts` drops every non-local host from assistant.json. Tried userinfo / fragment / bracket / tab tricks against `is_local` (`http://127.0.0.1:11434@evil.example`, `http://localhost:@evil.example`, `http://[::1]:80@evil.example`, `http://127.0.0.1:11434\t@evil.example`, …): none reached a non-local host (urllib refuses them as bad ports). With a configured HTTP proxy, see L1 |
| `netpolicy.urlopen` with an honest purpose | PASS: `/api/chat` purpose "assistant (local model)"; `/api/tags` via `assistant.http_json` (purpose defaults to the module name "assistant") |
| Works with NET OFFLINE | PASS (test: loopback allowed and only 127.0.0.1 in the log). L1: blocked if an `http_proxy` is set |
| No API key, no cloud path | PASS: no anthropic / openai / api_key anywhere in the Qt app or assistant.py |
| Streaming `/api/chat`, model from `/api/tags` | PASS: ndjson streamed token by token, `best_model` over `/api/tags`, `num_thread` cap on local |
| STOP cancels | PARTIAL: works between tokens; does nothing until the first token arrives (L2) |
| An error never leaves ASK greyed | PASS: any exception -> `error` row -> ASK back (test + read); no model -> `no_model` -> ASK back |
| No Ollama -> install hint | PASS (rendered, 3 themes): "NO LOCAL MODEL: Ollama is not running on this device. Install it once (needs internet): curl -fsSL https://ollama.com/install.sh \| sh then: ollama pull llama3.2:3b"; no crash, no hang (1.5 s probe per host). Demo says "DEMO, no model is asked in demo mode" |

**What goes to the model (stays on 127.0.0.1):** system prompt = `CHAT_SYSTEM` + local time + `live_summary`:
contact counts by kind; the texts of up to 5 unacknowledged alerts (free text from any module, so it can carry
a MESH DM's text, a lifecycle notice, or whatever an active module put in an alert); decode counts by source
(last 10 min); whether HOME is set (not its coordinates); the NET mode. Plus the last 8 turns of the conversation.
No engagement scope, opprofile identity or coordinates are added explicitly. The `live_context: False` setting in
assistant.json is not honoured by the Qt worker (L9).

## 5. Lifecycle and scope

| Check | Result |
|---|---|
| MeshLinkWorker stopped on close | PASS (Q3, Q10) |
| AskWorker stopped on close | PASS when idle or streaming. L2: while waiting for a first token it does not join in `MoreApp.stop`'s 3 s wait and runs on (11 s in the probe, up to the 180 s read timeout) with no park notice |
| UI-only elsewhere | PASS: pages.py docstring, shell import moved, old SYSTEM mesh stub removed (no stale reference to `MeshWorker` / `system.MeshApp`); pyflakes clean on all changed files |

## 6. Tests (one file per process, venv, xvfb + offscreen)

| File | Result |
|---|---|
| tests/test_mesh_assistant.py | 11 passed |
| tests/test_palisade_qt.py | 123 passed |
| tests/test_cl4_honest.py | 68 passed |

## New findings

### M1 (Medium): a DM silently becomes a broadcast when its target leaves the node list
`MeshPage._nodes_in` rebuilds the TO combo on every node list; if the chosen node is gone, `findData` returns -1
and `setCurrentIndex(max(0, i))` falls back to "everyone · primary channel" with no notice. The next SEND keys the
radio to the whole mesh with text the operator meant for one node. Node lists shrink on a reconnect (fresh node DB
from the device, evictions) and whenever `_nodes()` hits an exception (returns `{}`, which drops every DM target).
PoC (live hub, probe Q5):
```
pick "DM Trail bike node" -> nodes row without !c3d4e5f6 -> combo: "everyone · primary channel" ^all
_send("private: meet at the trailhead") -> worker.send(text, "^all")
```
Fix: keep the chosen target (mark it "(not heard now)") or refuse the send with a reason; never fall back silently.
Regression test: the PoC.

### M2 (Medium): the MESH map never says which nodes have no position, and goes blank with no reason
`_draw_map` skips any node without a position and, when this node has no position and HOME is not set (`me` is
None), plots nothing at all. Nothing on the map says why. Brief item 1 asks for exactly this honest state.
PoC (probes Q8 / Q9, renders `q8_nopos.png`, `q9_partpos.png`):
```
linked, 4 other nodes with positions, own node without one, HOME unset -> map_points == 0, empty rings, no text
own position known, 2 of 5 nodes without one -> 3 plotted; no label, key or table mark says which 2 are missing
```
Fix: a line on the map ("no position for this node and HOME not set: set HOME in SYSTEM" / "2 nodes without a
position: GLDN, HMB"), or a position column / mark in the side table. Regression test for both cases.

### Lows (Dalton's call; none blocks)
- **L1**: with an `http_proxy` environment variable and no `no_proxy`, urllib sends the loopback request through
  the proxy. NET ONLINE: the `/api/tags` probe (and so the `/api/chat` question + live context) goes to the proxy
  host, while netpolicy logs "allowed 127.0.0.1" (PoC: fresh process, `http_proxy=http://proxy.example:3128`,
  connect -> `('proxy.example', 3128)`). NET OFFLINE / LAN: the request is blocked and the page says "Ollama is
  not running". Needs an operator-set remote proxy; fix is a proxy-less opener for loopback.
- **L2**: STOP and page close are only seen between streamed lines. With a slow first token (cold model on the
  CM5) STOP does nothing until it arrives (PoC: STOP at 1.0 s, `done` at 12.0 s), and closing the page leaves
  AskWorker running past the 3 s join (joined after 11 s; up to the 180 s read timeout), with no park notice.
- **L3**: the new-node alert repeats when a node drops out of the list and comes back (`_seen_nodes` is replaced,
  not unioned). PoC Q7: two "new mesh node heard: Trail bike node" alerts.
- **L4**: `setMaxLength(200)` counts UTF-16 units: 100 emoji = 400 UTF-8 bytes passes, exceeding a Meshtastic
  text packet; the send is refused at the radio ("send failed: …") after the input was cleared. Pasted text over
  200 is cut silently.
- **L5**: a send queued in the same step a link-lost arrives is refused with
  "send failed: 'NoneType' object has no attribute 'sendText'" (honest refusal, unreadable reason).
- **L6**: NODES table at 1280: DIST and BRG are off-screen behind a horizontal scroll bar.
- **L7**: demo MAP (NET OFFLINE): Stage 2's "NO SATELLITE IMAGERY … DOWNLOAD MAP" banner sits on the node
  cluster and hides the ME / BIKE / KAPA labels.
- **L8**: the notice toast reads "MESH · MESH: the meshtastic Python package is missing …" (doubled prefix).
- **L9**: assistant.json `live_context: False` is ignored by the Qt AskWorker; `live_summary`'s docstring says
  "nothing else", but free alert text from any module is included (local only).
- **L10**: `assistant.is_local` counts `0.0.0.0` as local but netpolicy OFFLINE blocks it, so such a host reads
  as "Ollama is not running".
- Note: one SUN demo render showed ALERTS 1; a re-run with MESH alone raised none, so it is not attributed to MESH.

## Merge call
DO NOT MERGE until M1 and M2 are fixed with regression tests and re-audited. Lows L1-L10 are Dalton's call.
