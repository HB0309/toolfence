# ToolFence — Setup Guide

> Platform: Windows · Shell: PowerShell · Python 3.12 required.

---

## 1. Prerequisites

| Tool | Minimum version | Check |
|---|---|---|
| Python | 3.12 | `python --version` |
| Git | any recent | `git --version` |

Optional: Playwright (for dashboard end-to-end tests only — see §5).

---

## 2. Clone and create a virtual environment

```powershell
git clone <repo-url> Toolfence
cd Toolfence

python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

> The `.venv/` directory is git-ignored. Re-run the activate line in every new terminal.

---

## 3. Install the package (editable) with dev dependencies

```powershell
pip install -e ".[dev]"
```

This installs `toolfence` in editable mode plus `pytest`, `pydantic>=2`, and `jsonschema`.

Verify the entry point resolves:

```powershell
toolfence --help
```

Expected output:

```
usage: toolfence [-h] <command> ...

ToolFence — tool-surface auditing and injection-resilience evaluation for MCP agents.

...
```

---

## 4. Run the test suite

```powershell
pytest --collect-only   # confirm collection (no test execution)
pytest                  # run all tests
```

Tests that require a live Galaxium or nanobot instance are skipped automatically
when those targets are not present. Tests that require Playwright are skipped when
`playwright` is not installed.

---

## 5. Fetch target repos (optional — needed for integration tests)

```powershell
.\scripts\setup.ps1
```

This fetches Galaxium and nanobot at their pinned commits into `targets/galaxium/`
and `targets/nanobot/` (both git-ignored) and applies all patch files from
`targets/galaxium-patches/` in numbered order.

---

## 6. Playwright (optional — dashboard end-to-end tests only)

```powershell
pip install -e ".[dev-playwright]"
playwright install chromium
```

---

## 7. Environment variables

Copy `.env.example` to `.env` (git-ignored) and fill in the values:

```powershell
Copy-Item .env.example .env
```

| Variable | Used by | Notes |
|---|---|---|
| `OPENROUTER_API_KEY` | `scripts/run_spike.py`, live eval runs | Not needed for CI/tests |

`.env` is never committed. No secret must appear outside `.env.example` (which contains
only placeholder values).

---

## 8. Common issues

| Symptom | Fix |
|---|---|
| `toolfence` not found after install | Activate the venv: `.\.venv\Scripts\Activate.ps1` |
| `pytest: command not found` | Same as above |
| `ModuleNotFoundError: toolfence` | Run `pip install -e ".[dev]"` inside the venv |
