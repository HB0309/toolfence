# ToolFence — Idea Brief

> **ToolFence** is a standalone tool for teams that ship AI agents. Point it at an agent app and it
> maps the agent's tool surface, measures how well the agent resists untrusted text, proposes a fix,
> verifies it, and guards the agent at runtime. It runs from the command line, in CI, and from inside
> IBM Bob. We prove it on IBM's Galaxium Travels app as the testing ground.

This brief says *what* we are building and *how it should behave*. It is not an implementation plan.
Bob writes the implementation plan from this brief (see section 9).

---

## 1. The problem ToolFence solves

AI agents act through tools: they search, book, cancel, send. When an agent reads content written by
someone else (a review, a support message, a tool's own description), it cannot reliably tell that
content apart from an instruction. Untrusted text can therefore try to steer the agent into tool calls
the user never asked for. This is indirect prompt injection.

Teams shipping agents need to answer three questions before release, and again on every change:
1. **What can this agent reach?** Which tools are exposed, and which of them change state?
2. **What gets through?** How often can untrusted text steer it, through which channel, under which
   defense?
3. **What does a fix cost?** Does a defense or guard break the agent's normal jobs?

ToolFence answers all three with numbers, proposes a fix, and checks the fix holds.

## 2. The testing ground: Galaxium Travels

- IBM's open-source Bob demo app (`IBM/galaxium-travels`, Apache-2.0): an interplanetary flight-booking
  website. FastAPI backend, React frontend, Java inventory-hold service.
- Its backend uses `fastapi_mcp` to turn **every** REST route into an MCP tool, including internal
  routes. Galaxium has **no AI agent of its own**.
- It supports quotes and **expiring seat holds** (quote → hold → confirm / release).
- Galaxium is **not part of the ToolFence codebase**. A setup script fetches it at a pinned commit
  (`6163380cdb4ba50caee0b82c66afc4700d90546a`, main as of 2026-09-30) into `targets/galaxium/`, which
  is git-ignored. Our changes to Galaxium are kept as **patch files** under
  `targets/galaxium-patches/`, applied by the script. This keeps ToolFence clearly standalone and makes
  every Galaxium change reviewable.

## 3. What we are building

| # | Piece | Weight | One-line description |
|---|---|---|---|
| 1 | **ToolFence engine** | 35% | Reads an agent's tool schema, runs a safety evaluation, decides outcomes without an AI judge, and measures security and normal-task success |
| 2 | **Bob integration** | 20% | ToolFence used from inside Bob: an Auditor custom mode, a ToolFence MCP server Bob can call, and a skill that packages the workflow |
| 3 | **ToolFence Guard** | 15% | Runtime middleware any agent can wrap its tool calls with: tags each call's source, holds sensitive calls for user confirmation, ships a drop-in confirm-card UI component |
| 4 | **CLI, CI and dashboard** | 10% | `toolfence` command line, a GitHub Action, and a read-only results dashboard with replay |
| 5 | **Galaxium proving ground** | 20% | A small reference agent on Galaxium, the tool-surface fix ToolFence proposes (as patches), a minimal reviews change to demonstrate regression detection, and Guard shown in Galaxium's chat UI |

Weights describe how the team's effort is split; they guide planning, not code structure.

Build order: the engine core and the reference agent first (so there is something to test), then the
Galaxium findings and fixes, then Guard and the Bob integration, then CLI/CI/dashboard polish.

## 4. How each piece should behave

### 4.1 ToolFence engine
- **Input:** an agent's tool surface (an MCP server, a FastAPI app, or a plain JSON tool list) plus an
  adapter that knows how to run the agent for one turn.
- **Surface map:** lists every tool, marks which ones change state, and flags tools that look internal
  or admin-only. This report alone is useful, before any test runs.
- **Safety evaluation:** for each tool-surface and each defense setting, the engine runs the agent
  against **synthetic, labelled test content** and records what the agent did. Test content is built
  only from the target's own tool and parameter names plus harmless placeholders. **No working attack
  text is ever written or stored**; the repository ships only clearly-marked synthetic probes and a
  planted marker string (a "canary") that is itself harmless.
- **Channels evaluated:** untrusted text arriving in (1) the user's request and (2) content a tool
  returned; stretch: (3) a tool's own description.
- **Deterministic verdict, no AI judge:** a trial counts as a leak only if the planted canary appears
  inside the arguments of an outward tool call. Five outcomes: leaked, held, refused, inconclusive,
  skipped. Transport errors are never counted as "held."
- **Normal-task measurement:** every defense is also run on the agent's ordinary jobs with no attacker
  present, so a defense that breaks the agent is visible. Security and normal-task results are always
  reported together.
- **Honesty rule:** a clean result is not proof of safety. It means the evaluation did not find a way
  through, not that none exists. The tool says this in its own output.

### 4.2 Bob integration
- **Auditor custom mode:** a read-only Bob mode that, given an agent's code, produces the surface map
  and a prioritised list of findings with suggested fixes. It never edits code itself.
- **ToolFence MCP server:** exposes `scan_surface`, `run_eval`, `propose_fix` and `render_report` so
  Bob (or any MCP client) can drive ToolFence in a conversation.
- **Skill:** packages the "scan → fix → re-verify" procedure so a developer can run the whole workflow
  with one command.
- Added alongside Galaxium's existing `.bob/` modes, skills and hooks, never modifying them.

### 4.3 ToolFence Guard (runtime)
- **Middleware:** an agent wraps its tool calls with Guard. For each call, Guard records where the
  values came from (the user's request, or content the agent read) and whether the call changes state.
- **Confirmation:** a state-changing call whose values trace to untrusted content is held and shown to
  the user for Allow / Decline. Safe, read-only calls pass straight through.
- **Drop-in UI:** a small confirm-card component the host app can render; Galaxium's reference-agent
  chat uses it so travellers see and approve sensitive actions.
- **Honest limit:** Guard protects the actions it classifies as state-changing and relies on the user
  reading the card. It says so.

### 4.4 CLI, CI and dashboard
- **CLI:** `toolfence scan <target>`, `toolfence run <target>`, `toolfence report`.
- **CI:** a GitHub Action that fails a pull request when the agent's tool surface widens without a
  matching test, and reports when a change raises the leak rate.
- **Dashboard:** read-only, shows the results grid and the trend across runs, and has a "Run the safety
  check" button that **replays a recorded run** (no API key on the server).

### 4.5 Galaxium proving ground
- **Reference agent:** a small agent on IBM watsonx Granite that uses Galaxium's MCP tools to search
  flights, read reviews, hold seats and manage bookings. A second, open-weight model (Groq-hosted) must
  be swappable in for cross-model testing. Plain agent loop, observable tool calls, explicit
  `finish`/`refuse` endings, a small turn cap.
- **The fix ToolFence proposes:** narrow the tools the reference agent sees to only what a traveller
  task needs, and add ownership checks so a traveller can only see or change their own bookings. Shipped
  as patch files, with before/after surface-map numbers.
- **Reviews regression demo:** a minimal reviews change (a reviews table, a read tool, seeded demo
  reviews, following Galaxium backlog item #38) added so ToolFence's CI check can show the leak rate
  rising when a new content channel appears, then dropping once Guard and a defense are on.
- **Guard in the UI:** the reference agent's chat panel uses Guard's confirm cards.

## 4.6 How ToolFence is shown

ToolFence is not "inside Galaxium" and it is not only a dashboard. It has five surfaces across two
audiences. Galaxium hosts only the end-user surface (Guard cards); everything that shows ToolFence
working lives in the terminal, Bob, the dashboard and CI.

| Surface | Audience | Where it runs | What it shows |
|---|---|---|---|
| **Terminal / CLI** | Developer | A laptop or CI | `toolfence scan/run` printing the surface map and trial-by-trial progress |
| **Bob Auditor mode** | Developer | Inside the Bob IDE | A conversation: scan the agent, see findings, get the proposed fix |
| **Dashboard** | Anyone, incl. judges | A public web page | The results grid, the trend across runs, and a replayable run |
| **Guard confirm cards** | End user (traveller) | Inside the Galaxium chat | "This action came from content I read — Allow / Decline" |
| **CI check** | Developer | GitHub pull requests | Pass/fail with "leak rate rose from X to Y" |

**Live run vs replay.** A real run calls the model trial by trial and needs an API key, so it runs
only locally or in the demo video, never on the public dashboard. The dashboard instead has a "Run the
safety check" button that **replays a recorded run** step by step: it looks live, costs nothing, and
exposes no key. So: real processing in the terminal and Bob (recorded for the video); replay of that
same run on the public dashboard so judges can press it themselves.

**The dashboard is read-only over committed results.** No API key sits on a public server. It shows,
per target and run: blast radius (tools exposed → after fix, internal routes → 0), leak rate before and
after the fix, unconsented state-changing actions (target 0 of N), the channel × defense grid, and the
trend across runs (baseline → fix → guard). The replay button re-runs a recorded flow.

## 5. Non-negotiables

1. No secrets or API keys in code; read them from `.env`, which is git-ignored.
2. Canaries and probes are synthetic. **No working injection payloads anywhere**, including tests; use
   clearly-labelled placeholders only.
3. ToolFence only evaluates our own reference agent and built-in fixtures. Never Bob, never third-party
   services.
4. Every code change comes with a test.
5. Galaxium is a pinned, git-ignored test target; our changes to it live only as patch files.
6. Nothing that holds an API key runs on a public server.
7. Synthetic demo data only; no real personal data.

## 6. Technical constraints

- Python 3.12 for the engine, Guard and the reference agent.
- Existing React frontend for the Galaxium chat panel, confirm-card UI and reviews UI.
- watsonx Granite as the main model; one open-weight model (Groq-hosted) as the second.
- Hosting: IBM Cloud Code Engine for the Galaxium target and the dashboard.
- Tests: pytest, with a scripted (no-network) agent adapter so tests cost nothing and run in CI.
- Windows development machines; Docker is not assumed.

## 7. Out of scope

Multi-turn social engineering, memory poisoning, images or voice, optimizer-generated or obfuscated
inputs, real payments, real email or notifications, review moderation.

## 8. Team and milestones

- Three people, three parallel tracks:
  - **A, engine:** surface map, evaluation harness, verdicts, defenses, metrics.
  - **B, Galaxium + Bob:** reference agent, the proposed fix as patches, reviews change, Auditor mode,
    MCP server.
  - **C, product:** Guard middleware and UI, CLI, dashboard, CI, IBM Cloud deploy.
- **By Oct 4:** engine runs on the built-in fixture; reference agent working on Galaxium; first deploy.
- **By Oct 11:** evaluation runs on the reference agent; the proposed fix and its before/after numbers;
  Guard working; Auditor mode and dashboard live.
- **By Oct 18, 11:59 PM ET:** polished and submitted.

## 9. What we need from Bob

Turn this brief into an implementation plan, following a normal software development lifecycle:
1. **Requirements:** restate each piece as testable requirements; list open questions where this brief
   is ambiguous, and ask them before designing.
2. **Design:** components, data shapes, the adapter interface between the engine and a target agent,
   the Guard middleware interface, and the repo layout for our code.
3. **Tasks:** small, ordered steps per track, each small enough for one focused session, each with
   files touched, tests and a done-condition.
4. **Test plan:** unit, integration and end-to-end checks per piece.
5. **Risks:** what could block each milestone, and the fallback.

Save the plan under `docs/` and wait for the team's approval before implementing.

---

*Disclosure: this brief was drafted with Claude (Anthropic) during planning. All code, tests and
configuration are built with IBM Bob.*
