# AGENTS.md — Ask mode (documentation / questions)

This file provides guidance to agents when working with code in this repository.

## Where to find things

- **Requirements (what, not how):** `docs/REQUIREMENTS.md` — IDs like BASE-n, ENG-n, GRD-n, CLI-n, BOB-n, PG-n.
- **Full design and task list:** `docs/IMPLEMENTATION_PLAN.md` — section 3 has every task with files, done conditions, and status.
- **nanobot internals (how hooks, registry, reconnect, buttons work):** `docs/notes/nanobot-map.md`.
- **Galaxium routes, MCP exposure, ownership gaps:** `docs/notes/galaxium-map.md`.
- **Live spike results (10 clean runs, findings):** `docs/notes/spike-results.md`.
- **Trace fixture files:** `docs/notes/spike-traces/run-01.json` … `run-10.json` (pre-schema) and `fixtures/spike_converted/run-01.json` … `run-10.json` (evaluation format).

## Counterintuitive facts

- The nanobot **model** must be set under `agents.defaults.model`, not under `providers.openrouter`. Setting it under `providers` is silently ignored and nanobot falls back to claude-opus.
- nanobot **WebUI drops `buttons`** silently — confirmed in nanobot channel source. The Telegram channel is the only one that renders them and feeds button presses back as user messages.
- **`targets/galaxium/` and `targets/nanobot/`** do not exist in the repo — they are fetched on demand by `scripts/setup.ps1`. Code under them is referenced by path in notes but not browsable without running setup.
- The **datamarking tags** (`_NANOBOT_TAG`, `_NANOBOT_END`) in `guard/datamark.py` are **copied literals** from nanobot source, not imports — this is intentional to keep `guard/` free of nanobot dependencies.
- Track A implemented `guard/datamark.py` (task A-3) even though `guard/` is a Track C directory. Track C now owns and maintains it.
- **`ProxyStub`** in `contracts/guard.py` is a temporary stand-in used by Track B before `GuardedProxy` (C-2) is implemented. It has no Guard logic.
