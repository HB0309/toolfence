# Read docs/IDEA.md, docs/REQUIREMENTS.md and the notes in docs/notes/. Now write the implementation plan in docs/IMPLEMENTATION_PLAN.md. Don't write any code yet.

Cover:
1. Repo layout and the main components.
2. The 4 shared contracts with their actual fields: surface.json, Trace + adapter interface, Guard decision interface + held-call event, results format.
3. Tasks. Shared base first (skeleton, contracts, fixtures from the spike traces, scripted adapter, setup doc, CI). Then tasks per track: A engine, B targets + Bob, C Guard + product. Each task lists its requirement IDs, files touched, the test, and when it's done. Keep each task small enough for one Bob session, about 3 files.
4. Test plan per piece.
5. Risks and the fallback for each.

Rules: Python 3.12, pytest, Pydantic, no big frameworks, no AI in verdicts or Guard, Windows, no Docker. Stick to the B/C Guard boundary in IDEA.md §8. No dates or timeline, we set our own pace.

If anything is unclear, ask me first (max 5 questions) and wait.

---

**Status:** active  **Date:** 2026-10-10

---

### 👤 User

Read docs/IDEA.md, docs/REQUIREMENTS.md and the notes in docs/notes/. Now write the implementation plan in docs/IMPLEMENTATION_PLAN.md. Don't write any code yet.

Cover:
1. Repo layout and the main components.
2. The 4 shared contracts with their actual fields: surface.json, Trace + adapter interface, Guard decision interface + held-call event, results format.
3. Tasks. Shared base first (skeleton, contracts, fixtures from the spike traces, scripted adapter, setup doc, CI). Then tasks per track: A engine, B targets + Bob, C Guard + product. Each task lists its requirement IDs, files touched, the test, and when it's done. Keep each task small enough for one Bob session, about 3 files.
4. Test plan per piece.
5. Risks and the fallback for each.

Rules: Python 3.12, pytest, Pydantic, no big frameworks, no AI in verdicts or Guard, Windows, no Docker. Stick to the B/C Guard boundary in IDEA.md §8. No dates or timeline, we set our own pace.

If anything is unclear, ask me first (max 5 questions) and wait.

---

### 🤖 Assistant

> 🔧 called: use_skill



> 🔧 **use_skill** — create-plan

### 🤖 Assistant

> 🔧 called: read_file, read_file, list_files

Let me read all the source documents first.

> 🔧 **list_files** — docs/notes

> 🔧 **read_file** — docs/REQUIREMENTS.md

> 🔧 **read_file** — docs/IDEA.md

### 🤖 Assistant

> 🔧 called: read_file, read_file, read_file, list_files



> 🔧 **list_files** — docs/notes/spike-traces

> 🔧 **read_file** — docs/notes/spike-results.md

> 🔧 **read_file** — docs/notes/nanobot-map.md

> 🔧 **read_file** — docs/notes/galaxium-map.md

### 🤖 Assistant

> 🔧 called: read_file, list_files

Let me read one of the spike traces to understand the exact JSON shape:

> 🔧 **list_files** — .

> 🔧 **read_file** — docs/notes/spike-traces/run-05.json

### 🤖 Assistant

> 🔧 called: list_files, list_files, list_files



> 🔧 **list_files** — config

> 🔧 **list_files** — scripts

> 🔧 **list_files** — targets

### 🤖 Assistant

> 🔧 called: list_files, read_file



> 🔧 **list_files** — targets/galaxium-patches

> 🔧 **read_file** — config/nanobot.spike.json

### 🤖 Assistant

> 🔧 called: write_file

I now have a thorough picture of the entire codebase, requirements, and notes. Let me write the implementation plan.

> 🔧 **write_file** — docs/IMPLEMENTATION_PLAN.md

### 🤖 Assistant

The plan is written. Here's a summary of what's in it and the key decisions I made — please read through [`docs/IMPLEMENTATION_PLAN.md`](docs/IMPLEMENTATION_PLAN.md) and tell me what needs changing.

---

## What the plan covers

### §1 — Repo layout
Fourteen top-level directories. The four track-owned packages (`engine/`, `guard/`, `integration/`, `cli/`) are clearly separated. `guard/` has zero nanobot imports; `integration/` is the only package that imports both nanobot internals and `guard/`. A boundary table makes the ownership explicit.

### §2 — Four contracts (exact fields)

| Contract | Key design choices |
|---|---|
| **`surface.json`** | `name`, `action_class` (3 values), `trust_label` (2 values), `description_sha256`. JSON Schema in `engine/surface_schema.json`. |
| **Trace + adapter** | Spike trace fields (`name`, `params`, `result`, `error`, `duration_ms`) are the canonical base. Evaluation traces add `provenance`, `guard_decision` per call and a top-level `verdict`. Converted spike fixtures use safe defaults. `AgentAdapter` is a one-method Protocol. |
| **Guard decision + HeldCallEvent** | `GuardDecision.decide(tool_name, action_class, arguments, session_tainted, provenance)` → `"pass"` or `"hold"`. `HeldCallEvent` carries `reason`, `arguments_hash`, `untrusted_read_count`, and `untrusted_arg_name` so the card message can be built from it without any further lookups. |
| **Trial records** | 11 fields per trial including `cards_shown`. Five-value `verdict` enum. Separate `run_id` and `trial_id`. |

### §3 — Tasks (15 tasks across shared base, A, B, C)

Tasks are ordered shared-base first (S-1 through S-4), then by dependency. Each lists req IDs, ≤3 files, one test, and a done condition.

```
S-1  Skeleton + pyproject
S-2  Contracts + JSON Schemas
S-3  Spike-trace fixtures
S-4  Scripted adapter
A-1  Surface scanner
A-2  Canary + probe builder
A-3  Verdict + scoring + report
A-4  Evaluation runner
C-1  Guard core (decision, provenance, taint)
C-2  GuardedProxy + HeldCallEvent
C-3  Guard confirm flow
B-1  Galaxium patches
B-2  Setup script + nanobot config
B-3  nanobot Guard wiring
B-4  Datamarker + channel adapter
B-5  Baseline surface.json + nanobot patch
C-4  CLI subcommands
C-5  CI checks + GitHub Action
C-6  Dashboard
B-6  Bob MCP server + Auditor mode
A-5  Findings report + PG-8 integration test
C-7  IBM Cloud deploy
P-1  Full evaluation run + results commit
```

### §4 — Test plan per piece
Organised by level (unit / integration / schema / E2E) per component.

### §5 — 10 risks with fallbacks
Covers model gate failure, OpenRouter outage, reconnect timing, Telegram unavailability, Cloud deploy, Guard over-firing, and more.

---

## Targeted questions for your review

1. **HeldCallEvent `arguments_hash`** — I used SHA-256 of the canonical JSON of arguments (same as the grant-matching hash in GRD-9). Does the team want a shorter hash or a different canonical form?

2. **Session-level vs turn-level taint (GRD-5)** — The requirement says taint is session-level and never clears. R-7 flags that this may cause Guard to fire on all state-changing calls after the first review read. Is that acceptable, or should we discuss a turn-level variant before locking this in?

3. **`integration/startup_patch.py`** — I modelled this as a Python file that the nanobot patch applies to the three startup call sites. Should this be committed as a patch file in `targets/nanobot-patches/`, or is a thin Python shim imported from a startup wrapper preferred?

4. **P-1 is the last task** (full live run) and sits outside all tracks. Should it be gated — i.e., all S/A/B/C tasks must be green before P-1 can start?

---

### 👤 User

Checked the plan. Good structure, but these need fixing:

Must fix:
1. No nanobot patch. run_spike.py already starts nanobot from our code, so install Guard there in our own launcher (and a gateway launcher for Telegram). enabled_tools is just config.
2. Add a task for the real NanobotAdapter (build it from run_spike.py). Say how defenses are applied: datamarking through the proxy, instructional through a fresh workspace AGENTS.md, fresh session per trial.
3. The adapter should return a full Trace, not just tool calls: final reply, status (ok/error/timeout/max_iterations), tokens incl reasoning, model, host, session key, timestamp.
4. Guard needs every user message (for "user" provenance and grants). Wire that up, and connect a Telegram "Allow" press to the pending grant.
5. Ownership fix needs a way to know who the traveller is. Use a fixed X-Traveler-Id header in nanobot's MCP config, so the model can't change it.
6. Use one toolfence/ package with toolfence/contracts/ for the shared shapes, and keep all tests in tests/. Top-level cli/ or engine/ folders will clash.

Smaller:
- Datamarking lives in one place and must work with Guard off too (it's a defense).
- Add dependencies per task. B-3 needs C-2, so give B a stub proxy to start.
- Split B-1 (reviews / ownership) and B-6 (MCP server / mode + skill).
- R-10 is wrong: Java is needed for live runs.
- S-3: only validate the converted traces, and mark spike runs as normal-task success, not "refused".
- CI also runs the full pytest suite. surface.json goes in config/. Add Playwright
  as an optional dev dependency for the dashboard test.

Update IMPLEMENTATION_PLAN.md.

---

### 🤖 Assistant

> 🔧 called: read_file



> 🔧 **read_file** — docs/IMPLEMENTATION_PLAN.md

### 🤖 Assistant

> 🔧 called: read_file, read_file



> 🔧 **read_file** — docs/IMPLEMENTATION_PLAN.md

> 🔧 **read_file** — docs/IMPLEMENTATION_PLAN.md

### 🤖 Assistant

> 🔧 called: read_file, read_file



> 🔧 **read_file** — docs/IMPLEMENTATION_PLAN.md

> 🔧 **read_file** — docs/IMPLEMENTATION_PLAN.md

### 🤖 Assistant

> 🔧 called: read_file

Now I have the full picture. Let me also check `scripts/run_spike.py` to understand the existing launcher before rewriting:

> 🔧 **read_file** — scripts/run_spike.py

### 🤖 Assistant

> 🔧 called: write_file

Now I have everything I need. Let me rewrite the plan:

> 🔧 **write_file** — docs/IMPLEMENTATION_PLAN.md

### 🤖 Assistant

The plan has been fully rewritten. Here's a summary of every change made:

---

## What changed and why

### §1 — Repo layout
- **Single `toolfence/` package** with all sub-modules inside it. No more top-level `engine/`, `guard/`, etc. that would clash with other names.
- **`toolfence/contracts/`** replaces the split `engine/models.py` + `guard/models.py` — one canonical home for all shared shapes.
- **`tests/`** is now a single flat directory (not per-sub-package), as you asked.
- **No `nanobot-patches/`** for wiring — `targets/nanobot-patches/` is empty. Guard is wired in `scripts/launch_nanobot.py` and `scripts/launch_gateway.py`.
- **`enabled_tools` is config** in `config/nanobot.eval.json`, not a patch.
- **`results/surface.json`** (not `config/surface.json`) — surface map stays with results. CI reads it from there.
- **`toolfence/engine/datamark.py`** — datamarking lives in the engine, shared by both Guard-on and Guard-off paths.
- **Playwright** added as optional `dev-playwright` extra in `pyproject.toml`.

### §2 — Contracts
- **Trace** now includes `status`, `final_reply`, `model`, `host`, `session_key`, `timestamp`, and `usage.reasoning_tokens`. `adapter.run_turn()` returns a full `Trace`, not `list[ToolCallEntry]`.
- **Spike converted verdicts** changed from `"refused"` to `"normal_task_success"` — those were passing booking runs.
- **Defenses section added** explaining exactly how `none`/`datamarking`/`instructional` are applied by `NanobotAdapter` (fresh workspace, `AGENTS.md` written/deleted, fresh `session_key` per trial).
- **User-message feed** is now explicit: launchers register a `MessageBus` listener feeding `provenance_store.record_user_message` and `confirm_grant.check_inbound` before each turn. Telegram "Allow" works the same way.
- **Trial records** now embed the full `Trace` document (not just `tool_calls`).
- **`inconclusive`** is keyed off `trace.status` being `"error"/"timeout"/"max_iterations"` — deterministic, not a string search.

### §3 — Tasks
- **`A-3` is now Datamarking defense** (new task); old A-3 verdict/scoring shifted to A-4; old A-4 runner shifted to A-5.
- **`B-1` split** into B-1a (reviews patch) and B-1b (ownership patch). Ownership patch now uses `X-Traveler-Id` header in nanobot's MCP config — the model cannot supply or change the traveller ID.
- **`B-3`** updated: no startup-patch file; wiring is in `scripts/launch_nanobot.py`. B-3 depends on C-2 but can start with a stub proxy from S-2 contracts.
- **`B-4` is now NanobotAdapter** (built from `run_spike.py`'s `_run()`, returns full `Trace`).
- **`B-4b`** is the channel adapter + `launch_gateway.py`.
- **B-6 split** into B-6a (MCP server) and B-6b (Auditor mode + skill).
- **`A-6`** is the findings report (was A-5).
- **Dependencies added** to every task.
- **CI Action** now runs full `pytest tests/` as its first step before the surface-diff checks.
- **Dashboard test** uses `pytest.importorskip("playwright")` — skips gracefully if Playwright absent.

### §5 — Risks
- **R-8** replaces old R-8: `X-Traveler-Id` header forwarding by `fastapi_mcp` — may need verification.
- **R-9 and R-10** updated: R-9 is surface.json drift; R-10 clarifies Java is needed for live evaluation runs (not just demo), replacing the incorrect "Java optional" claim.

---

### 👤 User

Almost done. Four small fixes:
1. Move datamark into guard/ and give the proxy two switches: guard on/off and datamark on/off. Then all 6 defense conditions use the same wrapper, and Guard doesn't import engine.
2. Move NanobotAdapter to integration/. It imports nanobot and it's track B's.
3. The installer should wrap every tool, not just mcp_* (read_file too, for file labels).
4. Add a small proxy interface/stub to S-2 so B-3 can start before C-2 is done.

---

### 🤖 Assistant

> 🔧 called: read_file



> 🔧 **read_file** — docs/IMPLEMENTATION_PLAN.md

### 🤖 Assistant

> 🔧 called: apply_diff

Four targeted edits. Let me make them all in one pass:

> 🔧 **apply_diff** — docs/IMPLEMENTATION_PLAN.md

### 🤖 Assistant

> 🔧 called: read_file

Now update the boundaries table, the §2.2 adapter section, and the §2.3 datamark/proxy description:

> 🔧 **read_file** — docs/IMPLEMENTATION_PLAN.md

### 🤖 Assistant

> 🔧 called: read_file



> 🔧 **read_file** — docs/IMPLEMENTATION_PLAN.md

### 🤖 Assistant

> 🔧 called: read_file



> 🔧 **read_file** — docs/IMPLEMENTATION_PLAN.md

### 🤖 Assistant

> 🔧 called: read_file



> 🔧 **read_file** — docs/IMPLEMENTATION_PLAN.md

### 🤖 Assistant

> 🔧 called: read_file



> 🔧 **read_file** — docs/IMPLEMENTATION_PLAN.md

### 🤖 Assistant

> 🔧 called: apply_diff

Now I have the full picture. Let me make all four fixes in one surgical pass:

> 🔧 **apply_diff** — docs/IMPLEMENTATION_PLAN.md

### 🤖 Assistant

> 🔧 called: read_file

Now update the test plan tables to reflect the four changes (datamark in guard, NanobotAdapter in integration, all-tools installer, proxy switches):

> 🔧 **read_file** — docs/IMPLEMENTATION_PLAN.md

### 🤖 Assistant

> 🔧 called: read_file



> 🔧 **read_file** — docs/IMPLEMENTATION_PLAN.md

### 🤖 Assistant

> 🔧 called: apply_diff



> 🔧 **apply_diff** — <<<<<<< SEARCH
:start_line:861
-------
### Engine (Track A)

| Level | What | Where |
|---|---|---|
| Unit | Surface heuristics (GET→read, POST→state-changing, cancel/confirm/internal→irreversible) | `tests/test_surface.py` |
| Unit | Description hash change detection | `tests/test_surface.py` |
| Unit | Missing-tool default (state-changing) | `tests/test_surface.py` |
| Unit | Canary uniqueness; validator passes all probe files; rejects invalid | `tests/test_probe.py` |
| Unit | Datamark wraps; `is_datamarked` true; idempotent | `tests/test_datamark.py` |
| Unit | All five verdict branches; no LLM import; disclaimer present | `tests/test_verdict.py` |
| Integration | 2-channel × 6-defense matrix → 12 records | `tests/test_runner.py` |
| Integration | Normal-task + attack probe → both in report with counts and percentages | `tests/test_runner.py` |
| Integration | PG-8: canary in `create_quote` after reviews call → verdict `held` | `tests/test_findings.py` |
| Schema | 10 converted spike traces validate against trace schema; verdict `normal_task_success` | `tests/test_trace_fixtures.py` |
| Schema | All trial records from runner validate against trial schema | `tests/test_runner.py` |
| Contract | `NanobotAdapter` + `ScriptedAdapter` both pass `adapter_contract` | `tests/test_nanobot_adapter.py` |

### Guard (Track C)

| Level | What | Where |
|---|---|---|
| Unit | Four decision branches | `tests/test_guard_core.py` |
| Unit | Provenance: user / first-party / untrusted / untraced | `tests/test_guard_core.py` |
| Unit | Taint: fresh → tainted; never clears | `tests/test_guard_core.py` |
| Unit | File-label inheritance | `tests/test_guard_core.py` |
| Unit | Read-class always passes | `tests/test_guard_core.py` |
| Contract | No nanobot import, no LLM import in `guard/` | import check in `test_guard_core.py` |
| Unit | Hold: `tool.execute()` never called; result contains "paused" | `tests/test_proxy.py` |
| Unit | Card: three reason templates + buttons `[["Allow","Decline"]]` | `tests/test_proxy.py` |
| Unit | Datamark applied on untrusted pass-through | `tests/test_proxy.py` |
| Unit | Stub registry accepts `GuardedProxy` transparently | `tests/test_proxy.py` |
| Unit | Confirm: user grant → pass; wrong args → hold; tool-result grant → hold | `tests/test_confirm.py` |

### Integration / nanobot wiring (Track B)

| Level | What | Where |
|---|---|---|
| Unit | 3 stub tools → all 3 replaced by `GuardedProxy` | `tests/test_installer.py` |
| Unit | Reconnect → proxies re-applied | `tests/test_installer.py` |
| Unit | Bare wrapper injection → per-turn check raises | `tests/test_installer.py` |
| Unit | `spawn` and `exec` absent after install | `tests/test_installer.py` |
| Unit | Channel adapter → `OutboundMessage` with correct text and buttons | `tests/test_integration.py` |
| Unit | User-message listener → `confirm_grant.check_inbound` called with source `"user"` | `tests/test_integration.py` |
| Patch | Galaxium tests pass after all patches; reviews endpoint returns seeded rows | `tests/test_galaxium_patches.py` |
| Patch | Cancel with mismatched `X-Traveler-Id` header → 403 | `tests/test_galaxium_patches.py` |
| Patch | Bookings with mismatched header → 403 | `tests/test_galaxium_patches.py` |
| Startup | `dream.enabled: false` in config; `enabled_tools` narrows to 9 traveller tools | `tests/test_surface_baseline.py` |
| Contract | `NanobotAdapter` returns `Trace` with all required fields incl. `reasoning_tokens` | `tests/test_nanobot_adapter.py` |
=======
### Engine (Track A)

| Level | What | Where |
|---|---|---|
| Unit | Surface heuristics (GET→read, POST→state-changing, cancel/confirm/internal→irreversible) | `tests/test_surface.py` |
| Unit | Description hash change detection | `tests/test_surface.py` |
| Unit | Missing-tool default (state-changing) | `tests/test_surface.py` |
| Unit | Canary uniqueness; validator passes all probe files; rejects invalid | `tests/test_probe.py` |
| Unit | All five verdict branches; no LLM import; disclaimer present | `tests/test_verdict.py` |
| Integration | 2-channel × 6-defense matrix → 12 records (runner constructs proxy with correct switches per defense) | `tests/test_runner.py` |
| Integration | Normal-task + attack probe → both in report with counts and percentages | `tests/test_runner.py` |
| Integration | PG-8: canary in `create_quote` after reviews call → verdict `held` | `tests/test_findings.py` |
| Schema | 10 converted spike traces validate against trace schema; verdict `normal_task_success` | `tests/test_trace_fixtures.py` |
| Schema | All trial records from runner validate against trial schema | `tests/test_runner.py` |

### Guard (Track C)

| Level | What | Where |
|---|---|---|
| Unit | Four decision branches | `tests/test_guard_core.py` |
| Unit | Provenance: user / first-party / untrusted / untraced | `tests/test_guard_core.py` |
| Unit | Taint: fresh → tainted; never clears | `tests/test_guard_core.py` |
| Unit | File-label inheritance | `tests/test_guard_core.py` |
| Unit | Read-class always passes | `tests/test_guard_core.py` |
| Contract | No nanobot import, no LLM import in `guard/` (including `datamark.py`) | import check in `test_guard_core.py` and `test_datamark.py` |
| Unit | Datamark wraps; `is_datamarked` true; idempotent; no `engine/` import | `tests/test_datamark.py` |
| Unit | `guard_on=True`: hold blocks execution, result contains "paused" | `tests/test_proxy.py` |
| Unit | Card: three reason templates + buttons `[["Allow","Decline"]]` | `tests/test_proxy.py` |
| Unit | `datamark_on=True`: datamark applied on untrusted result | `tests/test_proxy.py` |
| Unit | `guard_on=False, datamark_on=False`: result passes through unchanged | `tests/test_proxy.py` |
| Unit | `guard_on=False, datamark_on=True`: datamark applied, no hold | `tests/test_proxy.py` |
| Unit | Stub registry accepts `GuardedProxy` transparently | `tests/test_proxy.py` |
| Unit | `ProxyStub` from contracts passes same interface checks | `tests/test_schemas.py` |
| Unit | Confirm: user grant → pass; wrong args → hold; tool-result grant → hold | `tests/test_confirm.py` |

### Integration / nanobot wiring (Track B)

| Level | What | Where |
|---|---|---|
| Unit | 3 MCP tools + 1 `read_file` tool → **all 4** replaced by `GuardedProxy` | `tests/test_installer.py` |
| Unit | Reconnect → proxies re-applied (all tools, not just mcp_*) | `tests/test_installer.py` |
| Unit | Bare wrapper injection → per-turn check raises | `tests/test_installer.py` |
| Unit | `spawn` and `exec` absent after install | `tests/test_installer.py` |
| Unit | `read_file` result recorded in provenance store after proxy executes | `tests/test_installer.py` |
| Unit | Channel adapter → `OutboundMessage` with correct text and buttons | `tests/test_integration.py` |
| Unit | User-message listener → `confirm_grant.check_inbound` called with source `"user"` | `tests/test_integration.py` |
| Contract | `NanobotAdapter` returns `Trace` with all required fields incl. `reasoning_tokens` | `tests/test_nanobot_adapter.py` |
| Contract | `NanobotAdapter` + `ScriptedAdapter` both pass `adapter_contract` | `tests/test_nanobot_adapter.py` |
| Patch | Galaxium tests pass after all patches; reviews endpoint returns seeded rows | `tests/test_galaxium_patches.py` |
| Patch | Cancel with mismatched `X-Traveler-Id` header → 403 | `tests/test_galaxium_patches.py` |
| Patch | Bookings with mismatched header → 403 | `tests/test_galaxium_patches.py` |
| Startup | `dream.enabled: false` in config; `enabled_tools` narrows to 9 traveller tools | `tests/test_surface_baseline.py` |
>>>>>>> REPLACE

### 🤖 Assistant

All four fixes are applied. Here's a precise summary of every change made:

---

## What changed and where

**Fix 1 — Datamark moves to `guard/`**

- [`§1 repo layout`](docs/IMPLEMENTATION_PLAN.md:37): `toolfence/engine/datamark.py` removed; `toolfence/guard/datamark.py` added with comment "shared by proxy and standalone use".
- [`§1 boundaries table`](docs/IMPLEMENTATION_PLAN.md:141): `engine/` no longer owns "datamarking defense"; `guard/` now owns "datamarking".
- [`Task A-3`](docs/IMPLEMENTATION_PLAN.md:479): retitled "Datamarking — guard", track changed to **C**, file path changed to `toolfence/guard/datamark.py`, done-condition adds "no `engine/` imports".
- [`Task C-2`](docs/IMPLEMENTATION_PLAN.md:555): proxy depends on `A-3` (the guard datamark), uses `datamark_result` from `guard/datamark.py` — no engine import path through the proxy.
- [`Task A-5`](docs/IMPLEMENTATION_PLAN.md:516): dependency on `A-3` removed (runner no longer touches datamark directly; the proxy handles it).
- Test plan: datamark row moved from Engine table to Guard table.

**Fix 2 — `NanobotAdapter` moves to `integration/`**

- [`§1 repo layout`](docs/IMPLEMENTATION_PLAN.md:29): `engine/nanobot_adapter.py` removed; `integration/nanobot_adapter.py` added.
- [`§1 boundaries table`](docs/IMPLEMENTATION_PLAN.md:143): `integration/` now listed as owning "NanobotAdapter".
- [`§2.2 adapter section`](docs/IMPLEMENTATION_PLAN.md:251): note updated — "`NanobotAdapter` lives in `toolfence/integration/nanobot_adapter.py` (Track B, imports nanobot)".
- [`Task B-4`](docs/IMPLEMENTATION_PLAN.md:656): retitled "NanobotAdapter — integration", file is `toolfence/integration/nanobot_adapter.py`.
- Test plan: `NanobotAdapter` contract rows moved from Engine table to Integration table.

**Fix 3 — Installer wraps every tool, not just `mcp_*`**

- [`Task B-3`](docs/IMPLEMENTATION_PLAN.md:643): intent updated — "wraps **every** tool in the registry — not just `mcp_*` — so that `read_file` and other built-in tools are captured for file-label provenance"; added GRD-6 to req IDs; `installer.py` description changed from "iterates `mcp_{server}_*` entries" to "iterates **all** `registry._tools` entries"; test updated to "3 MCP tools + 1 `read_file` tool → all 4 replaced"; added 5th test case: "`read_file` result recorded in provenance store".
- Test plan Integration table: installer row now says "**all 4** replaced", reconnect note says "all tools, not just mcp_*", new row for `read_file` provenance recording.

**Fix 4 — `ProxyStub` in S-2 contracts, B-3 can start immediately**

- [`Task S-2 files`](docs/IMPLEMENTATION_PLAN.md:398): `contracts/guard.py` now also defines `ProxyStub` — "a minimal pass-through proxy class (`name`, `execute`) that satisfies the `GuardedProxy` interface with no-op Guard logic; used by B-3 before C-2 is done".
- [`Task B-3 depends-on`](docs/IMPLEMENTATION_PLAN.md:635): changed from "C-2" to "S-2 (proxy stub), C-2 (real `GuardedProxy`; B-3 can start against the stub and upgrade when C-2 lands)".
- Test plan Guard table: new row "`ProxyStub` from contracts passes same interface checks → `tests/test_schemas.py`".