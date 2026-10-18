# Live runs update the whole dashboard

## Fixed decisions
- The live panel gets a select `#live-probe`: Your prompt / Attack: cancel-user-input /
  Attack: cancel-tool-result / Attack: taint-flow-tool-result.
- A probe runs through the existing EvaluationRunner for one probe x one defense, which gives a
  real attack TrialRecord with a verdict. Free-form gives a normal TrialRecord (task_label "live",
  task_success None).
- Every live record is saved to results/live/<unique id>.json (git-ignored). The existing
  /api/runs and /api/results already serve it.
- During a run, tool calls stream into the panel through the existing 1 s /api/live/pending poll.
  After a run, the page calls the existing loadData() and switches the Run filter to "live".
- "live" is excluded from the default view, so headline numbers never change.

## L-6a  Adapter + factory: fix holds, stream tool events
Files: toolfence/integration/nanobot_adapter.py, toolfence/integration/live_factory.py,
tests/test_nanobot_adapter.py
- In _CaptureHook.after_execute_tool, import _DECLINE_SENTINEL next to _HOLD_SENTINEL and set:
  guard_decision = "hold" if result_str in (_HOLD_SENTINEL, _DECLINE_SENTINEL) else "pass"
  (A call the user allowed stays "pass" because it really ran.)
- NanobotAdapter.__init__: add `on_tool_event: Callable[[dict], None] | None = None` and store it.
  - Pass it into _CaptureHook.__init__ (stored as self._on_event).
  - After each self.tool_events.append(...), in both after_execute_tool and
    on_execute_tool_error: if self._on_event, call
    self._on_event({"name": ev.name, "guard_decision": ev.guard_decision}) inside
    try/except Exception: pass.
- make_live_factory_from_profile(profile, run_id, *, api_key=None, on_held=None,
  await_decision=None, on_tool_event=None): pass all four straight through to NanobotAdapter.
  Defaults are None, so batch runs are unchanged.
- Tests:
  - A hook given _DECLINE_SENTINEL records "hold".
  - A hook given a normal string records "pass".
  - on_tool_event is called once per tool event.

## L-6b  Server: run probes, save records, expose progress
Files: toolfence/cli/dashboard/live.py, toolfence/cli/dashboard/server.py, .gitignore,
tests/test_dashboard_live.py
- WebGate: add held_count (int). on_held increments it. Add reset() that sets it to 0.
- LiveSession.__init__(self, results_dir: Path): keep self.results_dir and
  self.progress: list[dict] = []. make_server passes results_dir in.
- LiveSession.run(key, prompt, guard_on, defense, probe), where probe is "" or "0" / "1" / "2":
  1. Keep the busy lock and check_target_health. Then self.gate.reset() and
     self.progress.clear().
  2. profile = TargetProfile.model_validate(json.loads((REPO/"profiles/galaxium.json").read_text()))
     then profile = profile.model_copy(update={"nanobot_config": str(REPO/"config/nanobot.live.json"),
     "surface": str(REPO/"results/surface.json")})
  3. factory = make_live_factory_from_profile(profile, "live", api_key=key,
     on_held=self.gate.on_held, await_decision=self.gate.await_decision,
     on_tool_event=self.progress.append)
  4. dc = DefenseConfig(name=defense, guard_on=guard_on, datamark_on=(defense == "datamarking"))
  5. Probe run:
     - entry = profile.attack_probes[int(probe)]
     - Load its JSON exactly like cli/main.py:325-339: a str entry is a path; an object entry has
       .path and .task_prompt.
     - probe_dict = _apply_task_prompt(probe_dict, profile, override)  (import from cli/main.py)
     - surface = SurfaceFile.model_validate(json.loads((REPO/"results/surface.json").read_text()))
     - rec = EvaluationRunner([(probe_dict, None)], [], [dc], surface_map=surface,
       adapter_factory=factory).run_attack("live")[0]
  6. Free-form:
     - trace = factory(dc, "normal", prompt).run_turn(prompt, defense)
     - rec = TrialRecord(trial_id="x", run_id="live", kind="normal", channel=None,
       defense=defense, guard_on=guard_on, probe_id=None, canary=None, verdict=None,
       task_success=None, trace=trace, canary_in_args=False, cards_shown=0, task_label="live")
  7. Both paths:
     - rec = rec.model_copy(update={"trial_id": "live-" + utcnow "%Y%m%d-%H%M%S" + "-" +
       uuid4().hex[:4], "cards_shown": self.gate.held_count})
     - (self.results_dir / "live").mkdir(parents=True, exist_ok=True)
     - Write rec.model_dump_json(indent=2) to results_dir/live/<trial_id>.json
     - return {"trace": rec.trace.model_dump(), "record": rec.model_dump()}
- server.py:
  - /api/live/run reads probe (default ""). Return 400 unless probe is in {"", "0", "1", "2"}.
    The prompt is required only when probe == "".
  - Respond with the dict returned by run() as is.
  - GET /api/live/pending returns {"pending": gate.pending(), "progress": live.progress}.
- .gitignore: add the lines `results/live/` and `holds.db`. Run `git rm --cached holds.db`.
- Tests (monkeypatch make_live_factory_from_profile / EvaluationRunner, no network):
  - Free-form run writes one JSON in tmp/live/ that passes TrialRecord.model_validate.
  - probe "9" -> 400.
  - pending includes "progress".

## L-6c  UI: probe select, streaming, refresh all views
Files: toolfence/cli/dashboard/static/index.html, toolfence/cli/dashboard/static/live.js,
toolfence/cli/dashboard/static/app.js, tests/test_dashboard_static.py
- index.html: before #live-prompt add
  <select id="live-probe"> with options:
    value=""  "Your prompt"
    value="0" "Attack: cancel-user-input"
    value="1" "Attack: cancel-tool-result"
    value="2" "Attack: taint-flow-tool-result"
- live.js:
  - When #live-probe is not "", disable #live-prompt. Send needs only a tested key.
  - Include probe in the /api/live/run body.
  - In the existing pending poll, also set #live-out.textContent to
    "Running…\n" + (data.progress || []).map(p => p.name + " | " + p.guard_decision).join("\n")
  - After a 200 from run: render as now, then `await loadData(); setFilter('run', 'live');`
- app.js:
  - Line 33: const _EXCLUDED_RUNS = new Set(['full', 'narrowed', 'pg8-gate', 'live']);
  - _deriveApp: add `|| run === 'live'` to the galaxium condition.
- Test: index.html has id="live-probe"; live.js contains "loadData(" and "setFilter(".