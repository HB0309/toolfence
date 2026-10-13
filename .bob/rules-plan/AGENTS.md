# AGENTS.md — Plan mode (architecture / design)

This file provides guidance to agents when working with code in this repository.

## Track C ownership

Track C owns: `toolfence/guard/` (all files), `toolfence/cli/` (all files), `.bob/modes/auditor.yaml`, `.bob/skills/toolfence/SKILL.md`, `.github/workflows/toolfence-ci.yml`, `docs/deploy.md`.

Track A already placed `guard/datamark.py` here — Track C owns it from now on.

## Guard/Integration boundary (architectural constraint)

`guard/` contains **pure Python logic with zero nanobot imports**. `integration/` (Track B) contains all nanobot-touching code. The interface between them is `GuardedProxy` (C-2) and `HeldCallEvent` (in `contracts/guard.py`).

Any change that adds a nanobot import to `guard/` violates the architecture. Any change to `guard/proxy.py` or `guard/decision.py` needs sign-off from Track B.

## Pending Track A tasks that Track C depends on

- **A-5 (EvaluationRunner)** — `toolfence/engine/runner.py` does not yet exist. C-4 CLI needs it for `toolfence run`. Plan C-4 to start after A-5 lands, or stub the dependency.
- **A-6 (findings report extension)** — extends `engine/report.py` and adds `fixtures/findings.json`. C-4 CLI calls `render_report`; this is safe to implement before A-6 since A-6 only extends the existing report, it does not change the interface.

## Pending Track B tasks that affect Track C

- **B-3 (nanobot Guard wiring)** — uses `GuardedProxy` from C-2. B-3 can start with `ProxyStub` and upgrade when C-2 lands. C-2 must ship before B-3's final gate test.
- **B-4b (channel adapter)** — consumes `HeldCallEvent` (from contracts, already done) and `build_card_message` from `guard/card.py` (C-2). No blocker until B-4b needs the real card message.
- **B-5 (baseline surface.json)** — commits `results/surface.json`. C-4 CLI `toolfence scan` writes a draft; C-5 CI check reads the committed file. B-5 must land before C-5 integration tests can run against the real surface.

## Key architectural decisions already locked

- `GuardedProxy` has **two boolean switches** (`guard_on`, `datamark_on`) — always present, switches select behaviour. There is no separate no-guard code path.
- **Session taint never clears** within a session (GRD-5). If this becomes a normal-task problem, the taint window can be narrowed to turn-level, but that requires team sign-off (Risk R-7).
- **Reads always pass Guard** regardless of taint or provenance (GRD-12). The proxy must not hold read-class calls under any condition.
- **Irreversible actions always hold** regardless of session taint or argument provenance (GRD-7 rule 1). No override path.
- **Grant validation is source-checked** — a confirm grant appearing as a tool-result value is rejected. Only `source == "user"` grants are accepted (GRD-9).
- **MCP reconnect silently replaces proxies** — Track B's installer handles re-wrap. Track C's proxy must not assume it persists forever.

## Dashboard constraints (C-6)

- Pure `stdlib http.server` — no Flask, no FastAPI.
- Serves pre-committed JSON from `results/` — no model calls, no API keys, no env var reads.
- `inconclusive` verdicts must appear in their own column in the grid — never folded.
- Replay button steps through stored `TrialRecord` objects — no live execution.
- Playwright test is optional (`pytest.importorskip("playwright")`); skips gracefully offline.

## IBM Cloud deploy constraints (C-7)

- No `OPENROUTER_API_KEY` or any secret set in the Code Engine application.
- Deployment is repeatable from a single `ibmcloud ce` command documented in `docs/deploy.md`.
- Smoke test (`tests/test_deploy_smoke.py`) must pass or skip cleanly with `--skip-network`.
