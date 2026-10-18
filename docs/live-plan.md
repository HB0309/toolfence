# Live mode for the ToolFence dashboard

## Goal
Testers run their own prompts against the real stack: their OpenRouter key, nanobot + Granite,
Galaxium, and Guard confirm cards answered in the page. It is reachable from a GitHub URL via
Codespaces. Minimal code, no visual work. NO .env and NO environment-variable key handling.

## Fixed decisions (do not re-decide)
1. A LIVE button in the filter bar toggles a live panel directly under the filter bar. Stored-results
   sections are untouched. No changes to the run select, URL state or filter logic.
2. The prompt box and Send stay disabled until "Test key" succeeds. The server also rejects an
   empty key (400). Editing the key re-locks the prompt.
3. The key lives only in a JS variable. It is sent in the request body of /api/live/key and
   /api/live/run, used for that request only, and set straight onto the in-memory nanobot config
   object. It is never stored, logged, written to disk, put in an env var or put in a config file.
   No localStorage.
4. Confirm = Allow / Decline buttons. Use Guard's existing in-turn await_decision callback
   (toolfence/guard/proxy.py:28-31; install_guard(..., await_decision=) in
   toolfence/integration/installer.py:72). Model: DecisionGate in
   toolfence/integration/channel_adapter.py:100, ported to threads.
5. Live endpoints exist only with `toolfence serve --live`. Plain `serve` is unchanged.
6. One live turn at a time per server (lock, 409 if busy). The Galaxium DB is restored after every
   turn with the existing _DbBackupAdapter (toolfence/integration/live_factory.py:132).
7. No result files are written. The trace comes back in the HTTP response and is shown as plain
   text.

## Facts (verified in code)
- nanobot resolves ${OPENROUTER_API_KEY} at load and raises if it is unset
  (targets/nanobot/nanobot/config/loader.py:196-215). So live mode uses its own config with no env
  reference and sets the key on the loaded object:
  runtime_config.providers.openrouter.api_key = key  (ProviderConfig.api_key, repr=False).
- Config load is at nanobot_adapter.py:660; make_provider(runtime_config) is at :680. The override
  goes between them.
- nanobot.eval.json uses providerRetryMode "persistent", so a bad key would retry for 120 s. The
  live config uses "standard".
- Galaxium quotes and holds proxy to the Java service (JAVA_SERVICE_URL, default localhost:8080).
  Run Java on 8082 and start the backend with JAVA_SERVICE_URL=http://localhost:8082. The dashboard
  stays on 8080.
- The key check is GET https://openrouter.ai/api/v1/key with "Authorization: Bearer <key>". It
  uses zero tokens: 200 = valid, 401 = rejected. The server makes this call, never the browser.
- tests/test_dashboard_static.py forbids external URLs in index.html. Do not link openrouter.ai or
  Codespaces from the page.

## L-1 Adapter: key + in-page decision hooks
Files: toolfence/integration/nanobot_adapter.py, config/nanobot.live.json (new),
tests/test_nanobot_adapter.py
- NanobotAdapter.__init__: add keyword args `api_key: str | None = None` and
  `await_decision: Callable[[HeldCallEvent], Awaitable[bool]] | None = None`. Store them as
  self._api_key and self._await_decision.
- Add a module-level helper:
      def _wrap_await(fn, confirm_grant):
          async def _inner(event):
              ok = await fn(event)
              if ok:
                  confirm_grant.store_pending(event.tool_name, event.arguments_hash)
              return ok
          return _inner
- In _async_run_turn, right after `runtime_config = _load_runtime_config(...)`: if
  getattr(self, "_api_key", None), set runtime_config.providers.openrouter.api_key =
  self._api_key. Never log it.
- In the install_guard(...) call, add:
  await_decision=_wrap_await(self._await_decision, confirm_grant) if getattr(self, "_await_decision", None) else None
- config/nanobot.live.json = exact copy of config/nanobot.eval.json with two changes:
  "apiKey": ""  and  "providerRetryMode": "standard".
- Tests:
  - _wrap_await with an approving fake calls store_pending once.
  - _wrap_await with a declining fake never calls it.
  - nanobot.live.json contains no "${" and its apiKey is "".

## L-2 Server: opt-in live endpoints
Files: toolfence/cli/dashboard/live.py (new), toolfence/cli/dashboard/server.py,
toolfence/cli/main.py, tests/test_dashboard_live.py (new)

live.py (stdlib + toolfence imports only):
- REPO = Path(__file__).resolve().parents[3]
- check_key(key) -> tuple[bool, str]: urllib GET https://openrouter.ai/api/v1/key with header
  Authorization: Bearer <key>, timeout 10.
  - 200 -> (True, "Key OK"), plus limit_remaining if present.
  - 401 -> (False, "Key rejected by OpenRouter").
  - Anything else -> (False, "<status or error>").
  - Never log or echo the key.
- class WebGate(timeout=120.0): threading.Lock, threading.Event `_ready`, `_event`
  (HeldCallEvent | None), `_answer` (bool | None).
  - on_held(event): store the event, clear _ready, set _answer = None.
  - async await_decision(event): got = await asyncio.to_thread(self._ready.wait, self._timeout).
    result = got and self._answer is True. Clear _event, return result.
  - pending(): None, or {"tool", "arguments", "reason", "text": build_card_message(event)[0]}
    (toolfence/guard/card.py).
  - decide(approved: bool) -> bool: False if nothing is pending. Otherwise set _answer, set
    _ready, return True.
- class LiveSession: gate = WebGate(), _busy = threading.Lock(); class Busy(Exception).
  - run(key, prompt, guard_on, defense) -> dict:
    1. If not _busy.acquire(blocking=False), raise Busy.
    2. check_target_health("http://localhost:8001/") from live_factory (RuntimeError -> 503).
    3. adapter = NanobotAdapter(config_path=str(REPO/"config/nanobot.live.json"),
       surface_path=str(REPO/"results/surface.json"), run_id="live", guard_on=guard_on,
       datamark_on=(defense == "datamarking"), channel=None, api_key=key,
       on_held=self.gate.on_held, await_decision=self.gate.await_decision)
    4. Wrap: _DbBackupAdapter(adapter, str(REPO/"targets/galaxium/booking_system_backend/booking.db")).
    5. Return .run_turn(prompt, defense).model_dump().
    6. Release _busy in finally.

server.py:
- Handler class attributes: live_enabled: bool = False, live = None.
- make_server(host, port, results_dir, live=False) sets them; it creates one LiveSession() when
  live is set.
- GET /api/live/status always returns {"enabled": <bool>}.
- Every other /api/live/* route returns 404 unless live_enabled.
- GET /api/live/pending -> {"pending": gate.pending()}.
- Add do_POST. Read Content-Length (over 10000 bytes -> 400) and json.loads the body
  (error -> 400).
  - POST /api/live/key {key}: empty after strip -> 400. Otherwise check_key ->
    {"ok": ..., "message": ...}.
  - POST /api/live/run {key, prompt, guard, defense}: 400 if the key or prompt is empty, the
    prompt is over 2000 characters, or defense is not one of none/datamarking/instructional.
    guard is a bool. Busy -> 409. Galaxium down -> 503 {"error": msg}. Otherwise 200
    {"trace": ...}.
  - POST /api/live/decide {approved: bool}: gate.decide(...). False -> 409.
- Update the module docstring: read-only unless --live.
- run_server(..., live=False) passes live through.

main.py:
- serve_p.add_argument("--live", action="store_true", help="Enable in-page live runs (tester
  supplies their own OpenRouter key; nothing is stored).")
- Pass args.live through _cmd_serve to run_server.

tests/test_dashboard_live.py (no network, no nanobot; in-thread make_server on port 0):
1. WebGate: on_held(e), then decide(True) from a thread -> await_decision returns True.
2. timeout=0.1 with no decide -> False.
3. decide with nothing pending -> False.
4. Without live: /api/live/status -> {"enabled": false}; POST /api/live/run -> 404.
5. With live: run with an empty key -> 400.
6. check_key monkeypatched -> /api/live/key returns its result.
7. LiveSession.run monkeypatched to return {"status": "ok"} -> /api/live/run gives 200 with
   "trace". The key string never appears in caplog.text.

## L-3 UI: LIVE button + panel
Files: toolfence/cli/dashboard/static/index.html, toolfence/cli/dashboard/static/live.js (new),
tests/test_dashboard_static.py

index.html:
- In the filter bar's right button group (next to f-reset / f-share), add:
  <button id="f-live" class="btn btn-sm btn-outline-danger">LIVE</button>
- Directly after the #filter-bar card, add
  <div id="live-panel" class="card mb-3 d-none"><div class="card-body"> containing:
  - <div id="live-off" class="text-muted">Live mode is off on this host. Open the Codespaces demo from the README.</div>
  - <input id="live-key" type="password" autocomplete="off" placeholder="OpenRouter API key">
    <button id="live-key-test">Test key</button> <span id="live-key-msg"></span>
  - <select id="live-guard"> with options true ("Guard on", selected) and false ("Guard off")
  - <select id="live-defense"> with options none, datamarking, instructional
  - <textarea id="live-prompt" rows="3" maxlength="2000" disabled></textarea>
    <button id="live-send" disabled>Send</button>
  - <div id="live-card" class="d-none"><span id="live-card-text"></span>
    <button id="live-allow">Allow</button> <button id="live-decline">Decline</button></div>
  - <pre id="live-out"></pre>
  - One muted line: "Your key stays in this page's memory and is sent only to this server, per
    request. It is never saved."
- Add <script src="static/live.js"></script> after explorer.js.

live.js (about 90 lines; plain JS; relative URLs only; textContent only, never innerHTML; no
localStorage):
- #f-live click toggles d-none on #live-panel.
- On load, fetch('api/live/status'). On failure or enabled false: show #live-off and keep every
  input disabled. Otherwise hide #live-off and enable #live-key and #live-key-test.
- Test key: POST api/live/key {key}.
  - ok -> liveKey = key, enable #live-prompt and #live-send, show the message.
  - not ok -> liveKey = null, keep them disabled, show the message.
  - Any input event on #live-key -> liveKey = null, disable prompt and Send.
- Send:
  1. Disable Send and set #live-out to "Running…".
  2. setInterval every 1000 ms: GET api/live/pending. If pending is non-null, show #live-card with
     pending.text and the tool name. Otherwise hide it.
  3. await POST api/live/run {key: liveKey, prompt, guard: guardValue === 'true', defense}.
  4. Clear the interval, hide the card, re-enable Send.
  5. Render into #live-out: status, final_reply, then one line per tool call:
     name | guard_decision | (error || result) cut to 300 characters.
  6. Non-200: show the HTTP status and the error body.
- Allow / Decline: POST api/live/decide {approved: true|false}, then hide the card.

tests/test_dashboard_static.py: add a test that index.html has ids f-live, live-panel, live-key,
live-prompt, live-send, live-allow, live-decline, and that static/live.js exists and contains no
"localStorage".

## L-4 Codespaces live demo
Files: .devcontainer/devcontainer.json (new), scripts/setup.sh (new), scripts/start_live.sh (new),
README.md (one section)

.devcontainer/devcontainer.json:
{
  "name": "ToolFence live demo",
  "image": "mcr.microsoft.com/devcontainers/python:1-3.12-bookworm",
  "features": { "ghcr.io/devcontainers/features/java:1": { "version": "17", "installMaven": "true" } },
  "postCreateCommand": "bash scripts/setup.sh",
  "postStartCommand": "bash scripts/start_live.sh",
  "forwardPorts": [8080],
  "portsAttributes": { "8080": { "label": "ToolFence dashboard", "onAutoForward": "openBrowser" } }
}

scripts/setup.sh (set -euo pipefail; bash port of scripts/setup.ps1, same pins):
1. If targets/galaxium is absent: git clone https://github.com/IBM/galaxium-travels.git
   targets/galaxium, then check out 6163380cdb4ba50caee0b82c66afc4700d90546a.
   If targets/nanobot is absent: git clone https://github.com/HKUDS/nanobot.git targets/nanobot,
   then check out 948ce3824653d55b18ff1c618613fb642679bab7.
2. For each targets/galaxium-patches/*.patch in sorted order: if
   `git -C targets/galaxium apply --check <patch>` succeeds, apply it. Otherwise print
   "[SKIP] <name>".
3. pip install -e ".[dev]" -e targets/nanobot -r targets/galaxium/booking_system_backend/requirements.txt
4. (cd targets/galaxium/booking_system_inventory_hold_service && mvn -q clean package -DskipTests)

scripts/start_live.sh:
  nohup java -Dserver.port=8082 -jar targets/galaxium/booking_system_inventory_hold_service/target/inventory-hold-service-1.0.0.jar > /tmp/java.log 2>&1 &
  (cd targets/galaxium/booking_system_backend && JAVA_SERVICE_URL=http://localhost:8082 nohup python server.py > /tmp/galaxium.log 2>&1 &)
  nohup toolfence serve --host 0.0.0.0 --port 8080 --live > /tmp/dashboard.log 2>&1 &
No OPENROUTER_API_KEY anywhere.

README section "Try it live":
- Badge: [![Open in GitHub Codespaces](https://github.com/codespaces/badge.svg)](https://codespaces.new/HB0309/toolfence?quickstart=1)
- Steps:
  1. Wait for the first build (about 5 min); the dashboard tab opens.
  2. Click LIVE, paste your own OpenRouter key, click Test key.
  3. Pick Guard on/off and a defense, send a prompt.
- Sample prompts:
  - "I'm Alice (alice@example.com). Search for the cheapest economy seat from Earth to Mars for
    traveller Alice and place a hold on it."
  - "Cancel booking 1." (triggers the irreversible confirm card)
- Note: general queries spend the tester's own tokens.

## L-5 (optional) GitHub Pages read-only mirror
Files: scripts/export_static.py (new), toolfence/cli/dashboard/static/app.js,
.github/workflows/pages.yml (new)
- export_static.py <out>:
  - Copy static/ to <out>/static and index.html to <out>/index.html.
  - Write <out>/data/runs.json from server._list_runs(results).
  - Write <out>/data/<run>.json per run, using server._load_records_with_names plus the same
    TrialRecord validation as _serve_results.
- app.js loadData: wrap _fetchJson('api/runs') in try/catch. On failure, switch to static mode and
  read data/runs.json and data/<run>.json.
- pages.yml: on push to main. Steps: checkout, setup-python 3.12, pip install -e .,
  python scripts/export_static.py _site, actions/upload-pages-artifact@v3,
  actions/deploy-pages@v4. Permissions: pages: write, id-token: write.
- One-time manual step: Settings -> Pages -> Source: GitHub Actions.