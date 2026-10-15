---
name: toolfence
description: "Use when the user wants to audit an MCP tool surface for prompt-injection and trust-boundary vulnerabilities. Runs the full ToolFence pipeline: scan_surface → run_eval → propose_fix → run_eval (re-verify) → render_report. Trigger phrases: audit this surface, run toolfence, scan and fix, security audit, run eval."
---

# ToolFence Audit

You are running a ToolFence security audit. The goal is to scan an MCP tool surface, evaluate it against the attack matrix, propose mitigations, verify the fix, and render a final report — entirely through the four ToolFence MCP tools. You do not edit code; you produce findings and hand them to the engineer.


## Step 1 — Scan the Surface

Call `scan_surface` with the raw JSON tool list (or a path to a JSON file that contains it).

```
scan_surface(source: <json-string-or-file-path>)
```

This returns a draft `SurfaceFile` JSON. Save the output — you will use it as input to `run_eval` and `propose_fix`.

If the user has not yet provided a tool list, ask them for it before continuing.


## Step 2 — Run the Evaluation Matrix

Call `run_eval` with the surface JSON returned by Step 1. Run all channels and defenses unless the user asks for a subset.

```
run_eval(
  surface_json: <surface JSON from step 1>,
  channels: ["user-input", "tool-result"],   # omit to use both
  defenses: ["none", "datamarking", "instructional"]  # omit to use all three
)
```

This returns a list of `TrialRecord` objects. Note how many trials were leaked, held, refused, or inconclusive. Present a brief summary to the user before continuing.


## Step 3 — Propose a Fix

Call `propose_fix` with the path to a findings file and the surface JSON from Step 1.

```
propose_fix(
  findings_path: <path-to-findings.json>,
  surface_json: <surface-json-string>
)
```

This returns:
- `surface_proposal` — the surface echoed back unchanged (action classes are not modified)
- `enabled_tools` — the narrowed subset of tools cleared for the traveller persona (the fix)
- `open_findings` — finding IDs that are not yet fully mitigated

The fix is the narrowed `enabled_tools` list: tools outside it should be removed from the agent's allowlist. Show the user the open findings and the `enabled_tools` list. Ask whether they want to proceed to re-verification.


## Step 4 — Re-verify with the Proposed Surface

Once the user approves, call `run_eval` again with the same surface JSON, passing it inline.

```
run_eval(
  surface_json: <surface-json-string>,
  channels: ["user-input", "tool-result"],
  defenses: ["none", "datamarking", "instructional"]
)
```

The scripted adapter replays fixed fixtures, so this step confirms the proposed surface still passes the evaluation matrix — not that leaked verdicts will drop. Report whether all trials pass without new errors.


## Step 5 — Render the Report

Call `render_report` with the trial records from Step 4 (re-verification run) and a meaningful run ID.

```
render_report(
  trials_json: <json-string-of-trial-records>,
  run_id: <short-identifier>
)
```

This returns a Markdown report that includes the ENG-8 disclaimer and a full defense breakdown. Present the report text directly in the conversation.


## Constraints

- Never edit source code or configuration files — you are read-only.
- Never run shell commands.
- Always show a summary after Step 2 before proceeding to Step 3.
- Always ask for user approval after Step 3 before running Step 4.
- The four tool names are: `scan_surface`, `run_eval`, `propose_fix`, `render_report`. Use them verbatim when calling the ToolFence MCP server.
