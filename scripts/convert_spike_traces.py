"""One-time script: convert spike-trace JSON files into TrialRecord fixtures.

Run once from the repo root:
    python scripts/convert_spike_traces.py

Output: fixtures/spike_converted/run-01.json … run-10.json

The original spike files in docs/notes/spike-traces/ are never modified.
"""

from __future__ import annotations

import json
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
SPIKE_DIR = REPO_ROOT / "docs" / "notes" / "spike-traces"
OUT_DIR = REPO_ROOT / "fixtures" / "spike_converted"

# Metadata not captured per-call in the spike files, known from spike-results.md.
MODEL = "ibm-granite/granite-4.2-8b"
TIMESTAMP_FALLBACK = "2026-10-10T06:00:00Z"


def _timestamp_from_quote(tool_calls: list[dict]) -> str:
    """Extract createdAt from the create_quote call's result JSON.

    The quote result is a JSON string embedded inside the tool_calls entry.
    Returns the createdAt value truncated to second precision with a Z suffix,
    e.g. "2026-10-10T06:01:18Z".  Falls back to TIMESTAMP_FALLBACK if the
    field cannot be found.
    """
    for call in tool_calls:
        if "create_quote" in call["name"] and call["result"]:
            try:
                quote = json.loads(call["result"])
                raw = quote["createdAt"]          # e.g. "2026-10-10T06:01:18.780095900Z"
                # Truncate to seconds: keep everything up to the first dot/Z.
                base = raw.split(".")[0]          # "2026-10-10T06:01:18"
                return base + "Z"
            except (json.JSONDecodeError, KeyError):
                pass
    return TIMESTAMP_FALLBACK


def convert(spike: dict, run_num: int) -> dict:
    """Convert one spike-trace dict to a TrialRecord dict."""
    run_id = str(spike["run_id"])
    host = spike["host"]
    timestamp = _timestamp_from_quote(spike["tool_calls"])

    # Build the upgraded tool_calls list: add provenance and guard_decision.
    tool_calls = []
    for call in spike["tool_calls"]:
        tool_calls.append({
            "name":           call["name"],
            "params":         call["params"],
            "result":         call["result"],
            "error":          call["error"],
            "duration_ms":    call["duration_ms"],
            "provenance":     {},
            "guard_decision": "pass",
        })

    # Assemble Trace object.
    raw_usage = spike["usage"]
    trace = {
        "run_id":      run_id,
        "session_key": f"spike:alice:run-{run_num:02d}",
        "model":       MODEL,
        "host":        host,
        "timestamp":   timestamp,
        "status":      "ok",
        "final_reply": spike["response"],
        "tool_calls":  tool_calls,
        "usage": {
            "input_tokens":     raw_usage["input_tokens"],
            "output_tokens":    raw_usage["output_tokens"],
            "reasoning_tokens": 0,
            "total_tokens":     raw_usage["total_tokens"],
            "generation_ms":    raw_usage["generation_ms"],
        },
    }

    # Assemble TrialRecord object.
    return {
        "trial_id":       f"spike-run-{run_num:02d}",
        "run_id":         run_id,
        "kind":           "normal",
        "channel":        None,
        "defense":        "none",
        "guard_on":       False,
        "probe_id":       None,
        "canary":         None,
        "verdict":        None,
        "task_success":   True,
        "trace":          trace,
        "canary_in_args": False,
        "cards_shown":    0,
        "skip_reason":    None,
    }


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for run_num in range(1, 11):
        src = SPIKE_DIR / f"run-{run_num:02d}.json"
        spike = json.loads(src.read_text(encoding="utf-8"))
        record = convert(spike, run_num)
        dst = OUT_DIR / f"run-{run_num:02d}.json"
        dst.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        print(f"  wrote {dst.relative_to(REPO_ROOT)}")
    print("Done.")


if __name__ == "__main__":
    main()
