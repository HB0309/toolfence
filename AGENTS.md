# AGENTS.md

This file provides guidance to agents when working with code in this repository.

## Project identity

**ToolFence** — Python 3.12, pytest, Pydantic v2, no big frameworks, no AI in verdicts or Guard decisions, Windows PowerShell dev environment, no Docker.

## Commands

```powershell
# Install (editable + dev deps)
pip install -e ".[dev]"

# Run all tests
pytest

# Run a single test file
pytest tests/test_guard_core.py

# Run one test by name
pytest tests/test_guard_core.py::test_decision_irreversible_holds

# Collect without running
pytest --collect-only

# Dashboard E2E (optional — needs playwright installed separately)
pip install -e ".[dev-playwright]"
playwright install chromium
pytest tests/test_dashboard.py

# Skip network-dependent tests
pytest --skip-network
```

## Architecture — component boundaries (hard rules)

| Component | Must NEVER import |
|---|---|
| `toolfence/contracts/` | nanobot, any LLM client |
| `toolfence/engine/` | nanobot internals |
| `toolfence/guard/` | nanobot internals, LLM clients, `toolfence.engine` |
| `toolfence/integration/` | nothing blocked — this is where nanobot imports live |
| `toolfence/cli/` | nanobot internals |
| `toolfence/bob/` | nanobot internals |

**Guard boundary between Track B and Track C:** `guard/` is owned by Track C. `integration/` and `scripts/launch_*.py` are owned by Track B. Neither edits the other's directory. Changes to `guard/proxy.py` or `guard/decision.py` require approval from both tracks.

## Contracts — shared shapes, never redefined elsewhere

- `SurfaceEntry`/`SurfaceFile` — [`toolfence/contracts/surface.py`](toolfence/contracts/surface.py): five fields required; `name` pattern `^[a-z0-9_]+$`; `description_sha256` = 64 lowercase hex.
- `TraceEntry`/`Trace` — [`toolfence/contracts/trace.py`](toolfence/contracts/trace.py): `provenance` maps param name → `"user"|"first-party"|"untrusted"`; `guard_decision` is `"pass"|"hold"`.
- `TrialRecord` — [`toolfence/contracts/trial.py`](toolfence/contracts/trial.py): cross-field invariants enforced by `model_validator`; `verdict=="skipped"` requires `skip_reason` and `trace==None`.
- `HeldCallEvent`, `ProxyStub` — [`toolfence/contracts/guard.py`](toolfence/contracts/guard.py).
- JSON Schemas in `toolfence/contracts/schemas/` are **generated** by `scripts/generate_schemas.py` — never hand-edit them. The `test_committed_schema_is_fresh` test enforces this.

## What Track A has completed (already in codebase)

- **S-1–S-4 (shared base):** pyproject, all contract models + schemas, 10 converted spike fixtures, `ScriptedAdapter`, `adapter_contract.py`.
- **A-1:** `SurfaceScanner` (scan_json/openapi/mcp), `suggest_action_class`, `get_action_class`, `check_description_drift`, `_sanitise_name`.
- **A-2:** `generate_canary`, `ProbeBuilder`, `validate_probe_file`; probe templates in `toolfence/engine/probes/`; rule 6 (probe_id required) already added.
- **A-3:** `datamark_result`/`is_datamarked` in `toolfence/guard/datamark.py` (Track A wrote this under `guard/`; Track C owns it from here).
- **A-4:** `assign_verdict`, `canary_in_args` (public helper), `aggregate`, `render_report`, `ResultSummary` (with `timestamp` field and defense legend) — fully complete, all tests green.
- **A-5:** `EvaluationRunner` in `toolfence/engine/runner.py` — drives the full channel × defense matrix (12 attack + 6 normal = 18 records); optional `adapter_factory` parameter applies to both attack and normal trials (when set, it is called once per trial for all trial kinds).
- **Normal-task success rule:** `evaluate_normal_trial` in `toolfence/engine/normal_success.py` — pure-Python, no LLM; success = status ok and at least one goal-tool call that passed Guard (`guard_decision=="pass"`), had no error, and whose result is not an error payload (`"Error calling…"` prefix or JSON with a top-level `"error"` key).
- **B-4b DecisionGate:** `DecisionGate` in `toolfence/integration/channel_adapter.py` — held calls wait for a Telegram inline-keyboard button tap (120 s timeout); `store_pending` is called only inside `DecisionGate.await_decision`; `GuardedProxy` awaits via `await_decision`.
- **B-6 Bob MCP server:** `toolfence/bob/mcp_server.py` — four tools (`scan_surface`, `run_eval`, `propose_fix`, `render_report`) exposed to Bob over stdio.
- **Auditor mode and skill:** `.bob/custom_modes.yaml` (slug `auditor`) and `.bob/skills/toolfence/SKILL.md` — read-only audit pipeline, cannot edit code or run shell commands.

## Non-obvious project-specific patterns

- **A tool absent from `surface.json` defaults to `"state-changing"`** — the fail-closed BASE-2 rule; `get_action_class` implements this.
- **`report.py` re-exports `DISCLAIMER`** from `scoring.py` — import from either; the canonical string lives in `scoring.DISCLAIMER`.
- **Spike traces in `docs/notes/spike-traces/`** lack `provenance`, `guard_decision`, and `status` fields — they are pre-schema. Converted versions live in `fixtures/spike_converted/` and carry those fields with safe defaults.
- **`ScriptedAdapter` ignores `prompt` and `defense` arguments entirely** — the fixture encodes the outcome.
- **Datamarking tag strings are copied literals from nanobot** — do not import from nanobot; use the constants in `guard/datamark.py`.
- **`EvaluationRunner` constructs one `GuardedProxy` per trial** using two boolean switches (`guard_on`, `datamark_on`) — `guard_on=False` means the proxy is present but transparent; no separate bypass path.
- **Tests are flat under `tests/`** — one directory, no subdirectories. Pytest `testpaths = ["tests"]` in pyproject.
- **No `.env` is committed** — copy `.env.example` to `.env`; `OPENROUTER_API_KEY` is the only required secret and only needed for live eval runs.
- **`targets/galaxium/` and `targets/nanobot/` are git-ignored** — fetched by `scripts/setup.ps1`; our changes to them live only as `.patch` files in `targets/galaxium-patches/`.
- **nanobot config is JSON, not YAML**; model and provider are under `agents.defaults`, not `providers.openrouter` (the latter is ignored for model selection).
- **nanobot WebUI silently drops `OutboundMessage.buttons`** — confirmed in nanobot-map. Use Telegram for the live Guard confirm card.
- **Demo identity:** `config/nanobot.gateway.json` passes `X-Traveler-Id: "1"` — the gateway agent is traveller 1 (Alice).
- **Demo irreversible action is `cancel_booking`:** `confirm_hold` is not in `enabledTools`; the only irreversible tool the agent can call is `mcp_galaxium_cancel_booking_endpoint_cancel_booking_id_post` (action_class `"irreversible"` in the surface fixture).
