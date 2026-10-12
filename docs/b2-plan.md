# B-2 Plan — Setup script and nanobot config

## Overview

B-2 creates the three artefacts that all later Track-B tasks depend on:

1. `scripts/setup.ps1` — fetches both target repos at their pinned commits and applies patches
2. `config/nanobot.eval.json` — locked-down eval config (9 traveller tools, `X-Traveler-Id` header)
3. `config/nanobot.gateway.json` — same as eval plus the real Telegram channel config
4. `.env.example` — adds `TELEGRAM_BOT_TOKEN` and `TELEGRAM_USER_ID` placeholders
5. `docs/setup.md` — adds Telegram bot setup instructions to the existing §7 env-vars section
6. `tests/test_setup.py` — verifies the script runs and leaves both target dirs in a good state

`docs/setup.md` already has a §5 stub that mentions `setup.ps1`; it needs no structural changes —
only a Telegram subsection added to §7 (env vars).

**Req IDs:** PG-2, GRD-13

---

## Sub-task 1 — `scripts/setup.ps1`

**Status:** [ ] pending

**Intent**

Write the PowerShell fetch-and-patch script. It must:
- Clone `galaxium` (`https://github.com/IBM/galaxium-travels.git`) into `targets/galaxium/`, checkout full hash `6163380cdb4ba50caee0b82c66afc4700d90546a`
- Clone `nanobot` (`https://github.com/HKUDS/nanobot.git`) into `targets/nanobot/`, checkout full hash `948ce3824653d55b18ff1c618613fb642679bab7`
- If a target directory already exists, verify `git rev-parse HEAD` matches the pinned hash — fail loudly if it doesn't (wrong commit)
- Apply every `*.patch` under `targets/galaxium-patches/` in lexicographic order; for each patch, run `git apply --check --reverse` first and skip the patch if it's already in (idempotent re-runs)
- Check that `targets/nanobot-patches/` exists before attempting the loop; skip the loop entirely if the directory is absent
- Apply every `*.patch` under `targets/nanobot-patches/` with the same check-reverse guard
- Print a `[PASS]` / `[FAIL]` line after each step
- Set `Set-StrictMode -Version Latest` and `$ErrorActionPreference = "Stop"` (matches `spike.ps1` style)

**Expected Outcomes**

- Running `.\scripts\setup.ps1` from a clean state leaves `targets/galaxium/` and
  `targets/nanobot/` checked out at the correct pinned commits with patches applied.
- Re-running when directories already exist at the correct commit skips clone and skips already-applied patches.
- If a directory exists at the wrong commit, the script fails with a clear `[FAIL]` message.
- Each step prints `[PASS]` or `[FAIL <error>]`.

**Todo List**

- [ ] Create `scripts/setup.ps1`
- [ ] Add strict-mode and error-action-preference header
- [ ] Write `Invoke-Step` helper that runs a script-block, prints `[PASS]` / `[FAIL]`, and propagates failure
- [ ] Clone-or-verify block for `targets/galaxium`: if absent, clone + checkout full hash; if present, verify HEAD matches hash and fail if not
- [ ] Clone-or-verify block for `targets/nanobot`: same pattern with its full hash
- [ ] Patch loop for `targets/galaxium-patches/`: sorted `*.patch` files; per patch: `git apply --check --reverse` → skip if already applied; else `git apply`
- [ ] Patch loop for `targets/nanobot-patches/`: check directory exists first; same per-patch guard
- [ ] Print final summary line

**Relevant Context**

- `scripts/spike.ps1` — existing reference for PowerShell style, `Write-Host` coloring
- `targets/galaxium-patches/0001-typed-quote-request.patch` — standard `git diff` format; applied with `git apply` run inside the target dir
- Galaxium repo: `https://github.com/IBM/galaxium-travels.git` · pinned hash: `6163380cdb4ba50caee0b82c66afc4700d90546a`
- nanobot repo: `https://github.com/HKUDS/nanobot.git` · pinned hash: `948ce3824653d55b18ff1c618613fb642679bab7`
- `targets/galaxium/` and `targets/nanobot/` are already in `.gitignore`
- `targets/nanobot-patches/` does not exist yet — the loop must guard against a missing directory

---

## Sub-task 2 — `config/nanobot.eval.json`

**Status:** [ ] pending

**Intent**

Create the eval-run nanobot config. It extends `nanobot.spike.json` with:
- `tools.mcpServers.galaxium.enabledTools` — the 9 traveller-task wrapped tool names (PG-6); camelCase to match `mcpServers`
- `tools.mcpServers.galaxium.headers` — `{"X-Traveler-Id": "1"}` (GRD-13)
- No `channels` block (eval runs headless)

The 9 tools in `enabledTools` (exact wrapped names — nanobot squeezes `__` down to `_`, so no double underscores):

```
mcp_galaxium_get_flights_flights_get
mcp_galaxium_get_user_endpoint_user_get
mcp_galaxium_get_flight_reviews_flights_flight_id_reviews_get
mcp_galaxium_create_quote_quotes_post
mcp_galaxium_create_hold_quotes_quote_id_holds_post
mcp_galaxium_get_hold_holds_hold_id_get
mcp_galaxium_release_hold_holds_hold_id_release_post
mcp_galaxium_get_user_bookings_bookings_user_id_get
mcp_galaxium_cancel_booking_endpoint_cancel_booking_id_post
```

Note: `get_flight_reviews` is added by B-1a patch; its function must be named `get_flight_reviews` so
the wrapped name matches. nanobot warns on unmatched entries but does not fail, so including it now
is safe. B-5 will verify all 9 against the live tool list (noted in `docs/setup.md`).

**Expected Outcomes**

- `config/nanobot.eval.json` is valid JSON.
- All fields from `nanobot.spike.json` are preserved.
- `enabledTools` array (camelCase) contains exactly the 9 names above.
- `headers` object is present with `"X-Traveler-Id": "1"`.
- No `channels` block.

**Todo List**

- [ ] Create `config/nanobot.eval.json`
- [ ] Copy all fields verbatim from `config/nanobot.spike.json`
- [ ] Add `enabledTools` array (camelCase) inside `tools.mcpServers.galaxium`
- [ ] Add `headers` object inside `tools.mcpServers.galaxium`
- [ ] Verify JSON is valid (no trailing commas, no comments)

**Relevant Context**

- `config/nanobot.spike.json` — base to copy from
- REQUIREMENTS §PG-6 — canonical short names; `get_flight_reviews` is the B-1a function name constraint
- REQUIREMENTS §GRD-13 — sub-agents disabled by not registering `spawn`; no extra field needed here
- `docs/notes/nanobot-map.md` §3 — `enabledTools` filter (camelCase in nanobot source)

---

## Sub-task 3 — `config/nanobot.gateway.json`

**Status:** [ ] pending

**Intent**

Create the gateway config. It is identical to `nanobot.eval.json` plus a `channels.telegram` block
using nanobot's real `TelegramConfig` shape (from `channels/telegram/runtime.py`):

```json
"channels": {
  "telegram": {
    "enabled": true,
    "token": "${TELEGRAM_BOT_TOKEN}",
    "allowFrom": ["${TELEGRAM_USER_ID}"],
    "inlineKeyboards": true
  }
}
```

nanobot performs `${VAR}` → env-var substitution at load time, so the placeholders are correct as-is.
No wildcard `"*"` in `allowFrom`.

**Expected Outcomes**

- `config/nanobot.gateway.json` is valid JSON.
- It contains every field from `nanobot.eval.json`.
- It adds a top-level `"channels"` key with the Telegram block above.

**Todo List**

- [ ] Create `config/nanobot.gateway.json`
- [ ] Copy all content from `config/nanobot.eval.json`
- [ ] Add `"channels"` top-level key with the Telegram block
- [ ] Verify JSON is valid

**Relevant Context**

- `config/nanobot.eval.json` — base (built in sub-task 2)
- nanobot source `channels/telegram/runtime.py` — `TelegramConfig` field names confirmed: `enabled`, `token`, `allowFrom`, `inlineKeyboards`

---

## Sub-task 4 — `.env.example` and `docs/setup.md` Telegram section

**Status:** [ ] pending

**Intent**

`.env.example` does not exist yet. Create it with all required environment variable placeholders,
including the two new Telegram variables.

Update `docs/setup.md` §7 (Environment variables) to explain how to obtain both Telegram values:
- `TELEGRAM_BOT_TOKEN` — from `@BotFather` on Telegram (create a bot, copy the token)
- `TELEGRAM_USER_ID` — from `@userinfobot` on Telegram (forward any message, bot replies with your numeric ID)

The existing `OPENROUTER_API_KEY` row in the §7 table stays unchanged.

**Expected Outcomes**

- `.env.example` exists with `OPENROUTER_API_KEY=`, `TELEGRAM_BOT_TOKEN=`, `TELEGRAM_USER_ID=` (empty values, no secrets).
- `docs/setup.md` §7 table lists all three variables.
- A new sub-section under §7 explains how to get the Telegram values (2–3 sentences each).
- `docs/setup.md` §8 common issues gains a row for the Telegram token if needed.

**Todo List**

- [ ] Create `.env.example` with `OPENROUTER_API_KEY=`, `TELEGRAM_BOT_TOKEN=`, `TELEGRAM_USER_ID=`
- [ ] Update `docs/setup.md` §7 table to add `TELEGRAM_BOT_TOKEN` and `TELEGRAM_USER_ID` rows
- [ ] Add Telegram bot-setup instructions paragraph after the §7 table
- [ ] Verify `docs/setup.md` still reads correctly from top to bottom

**Relevant Context**

- `docs/setup.md` lines 92–106 — existing §7 and §8
- `docs/setup.md` line 102 — existing `OPENROUTER_API_KEY` row
- nanobot gateway config substitutes `${TELEGRAM_BOT_TOKEN}` and `${TELEGRAM_USER_ID}` at load time

---

## Sub-task 5 — `tests/test_setup.py`

**Status:** [ ] pending

**Intent**

Write the pytest test module that validates the setup script. It must be skippable when network
access is unavailable or undesired (via `--skip-network` pytest option, consistent with the pattern
named in the plan spec).

Tests:
1. **`test_targets_exist`** — runs `setup.ps1`, then asserts `targets/galaxium/` and `targets/nanobot/` exist
2. **`test_galaxium_patch_applied`** — after setup, asserts `targets/galaxium/booking_system_backend/server.py`
   contains the string `"reviews"` (the reviews route added by patch 0002); or if B-1a is not yet done,
   asserts patch 0001 was applied by checking `from schemas import` includes `QuoteRequest`
3. Both tests are skipped when `--skip-network` is passed

The test file must register the `--skip-network` option via `conftest.py` (or inline if `conftest.py` already handles it).

**Expected Outcomes**

- `pytest tests/test_setup.py` passes when network is available and `setup.ps1` succeeds.
- `pytest tests/test_setup.py --skip-network` skips both tests cleanly (0 failures, 2 skipped).
- No import errors or collection failures.

**Todo List**

- [ ] Check `tests/conftest.py` — add `--skip-network` option if not already there
- [ ] Create `tests/test_setup.py`
- [ ] Add `skip_if_no_network` fixture/marker based on `--skip-network` flag
- [ ] Write `test_targets_exist`: subprocess `setup.ps1`, assert both target dirs exist
- [ ] Write `test_galaxium_patch_applied`: read `server.py` post-setup, assert QuoteRequest import present
- [ ] Ensure test is not collected/run in CI unless explicitly opted in (skip by default unless targets already present)

**Relevant Context**

- `tests/conftest.py` — currently empty; `--skip-network` must be added here
- `scripts/setup.ps1` — the script under test
- `targets/galaxium-patches/0001-typed-quote-request.patch` — patch 0001 adds `QuoteRequest` import to `server.py`
- Assertion for reviews route should be conditioned on patch 0002 existing in `targets/galaxium-patches/`

---

## Implementation Order

```
sub-task 1 (setup.ps1)
    ↓
sub-task 2 (nanobot.eval.json)
    ↓
sub-task 3 (nanobot.gateway.json)   ← depends on eval config content
    ↓
sub-task 4 (.env.example + setup.md)
    ↓
sub-task 5 (test_setup.py)          ← depends on setup.ps1 existing
```

Sub-tasks 2–4 are independent of each other but all depend on sub-task 1 for
correctness of the overall B-2 deliverable.
