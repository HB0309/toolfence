# Surface Correctness Fixes — Plan

## Top-Level Overview

Three correctness bugs prevent `results/surface.json` (Track B's B-5 output) from ever matching
the names and hashes that nanobot registers at runtime.

| # | Bug | Root cause | Fix location |
|---|---|---|---|
| 1 | Three wrong tool names in `fixtures/surface_fixture.json` | Names were derived by stripping `{`/`}` from paths rather than using FastAPI `operationId` | `fixtures/surface_fixture.json` |
| 2 | `scan_openapi` ignores `operationId`; names never match nanobot | Name-building logic uses path segments, not `operationId` | `toolfence/engine/surface.py` — `scan_openapi` |
| 3 | `description_sha256` hashes one field, but nanobot concatenates summary + description + response info | `scan_openapi` reads `description or summary` rather than mirroring `fastapi_mcp`'s assembly | `toolfence/engine/surface.py` — `scan_openapi` docstring + description assembly |

The fixes are independent and can be implemented as three sequential sub-tasks.
No cross-boundary imports are introduced; the nanobot sanitise/truncate rule is copied verbatim.

---

## Sub-Task 1 — Fix the three wrong names and recompute all five hashes in `fixtures/surface_fixture.json`

### Intent
Replace the three stale path-derived names with the exact names nanobot registers.
The third entry also has a truncation issue: the raw name exceeds 64 chars, so nanobot
appends an 8-char SHA-1 suffix rather than the full name.

Because Sub-Task 2 also changes how `scan_openapi` builds the description string (Option B:
`summary + "\n\n" + description` instead of `description or summary`), all five
`description_sha256` values in the fixture must be recomputed to stay self-consistent with
the updated scan logic.

### Expected Outcomes
- `fixtures/surface_fixture.json` contains five entries that match what nanobot registers.
- All three corrected entries pass the `^[a-z0-9_]+$` pattern (they already do).
- All five `description_sha256` values are SHA-256 of `"{summary}\n\n{description}"` for
  each corresponding Galaxium endpoint.
- `tests/test_surface.py::test_surface_fixture_loads_as_pydantic_model` and
  `test_surface_fixture_validates_against_schema` still pass (name format unchanged).
- `test_a1_scan_json_all_action_classes_represented` still passes.

### Todo List
1. In `fixtures/surface_fixture.json`, update the `name` field of the three wrong entries:

   | Old name | New name |
   |---|---|
   | `mcp_galaxium_cancel_booking__booking_id__post` | `mcp_galaxium_cancel_booking_endpoint_cancel_booking_id_post` |
   | `mcp_galaxium_get_flight_reviews_flights__flight_id__reviews_get` | `mcp_galaxium_get_flight_reviews_flights_flight_id_reviews_get` |
   | `mcp_galaxium_create_booking_from_hold_internal_bookings_from_hold_post` | `mcp_galaxium_create_booking_from_hold_internal_bookings_d31ac16e` |

2. Recompute all five `description_sha256` values using the new concatenation rule.
   Run the following script against the live Galaxium OpenAPI spec (or a locally fetched
   `openapi.json`) — paste the output back into the fixture:

   ```python
   import hashlib, json, urllib.request

   # Fetch the spec (adjust URL/path as needed)
   spec = json.loads(urllib.request.urlopen("http://localhost:8000/openapi.json").read())

   for path, path_item in spec["paths"].items():
       for method, op in path_item.items():
           if method not in ("get","post","put","patch","delete"):
               continue
           summary = op.get("summary") or ""
           description = op.get("description") or ""
           if summary and description:
               text = f"{summary}\n\n{description}"
           elif summary:
               text = summary
           else:
               text = description
           sha = hashlib.sha256(text.encode()).hexdigest()
           print(f"{method.upper()} {path!r:45s}  {sha}")
   ```

   Match each printed line to the corresponding fixture entry by `route` and update
   `description_sha256` accordingly.

3. Leave `route`, `action_class`, and `trust_label` unchanged for all five entries.
4. Fix two existing test references that use old wrong fixture names (see C3):

   a. `tests/test_surface.py` line 123 — `test_known_tool_action_class_returned`:
      Change the lookup for the cancel tool from the old name to the corrected one:
      ```python
      # old
      assert get_action_class(surface, "mcp_galaxium_cancel_booking__booking_id__post") == "irreversible"
      # new
      assert get_action_class(surface, "mcp_galaxium_cancel_booking_endpoint_cancel_booking_id_post") == "irreversible"
      ```

   b. `tests/test_surface.py` line 314 — `test_scan_mcp_with_mock_server`:
      Update the inline mock data to use the corrected cancel tool name:
      ```python
      # old
      {"name": "mcp_galaxium_cancel_booking__booking_id__post", "description": "Cancel booking."},
      # new
      {"name": "mcp_galaxium_cancel_booking_endpoint_cancel_booking_id_post", "description": "Cancel booking."},
      ```
      Also update line 331's `next(...)` filter if it uses a hardcoded name (it uses
      `"cancel" in t.name` — no change needed there).

5. Run `pytest tests/test_surface.py` to verify no regressions.

### Relevant Context
- File: `fixtures/surface_fixture.json` lines 19, 26, 33
- File: `tests/test_surface.py` lines 123 and 314 — the two stale name references
- The `SurfaceEntry.name` field pattern is `^[a-z0-9_]+$` — all three new names satisfy this.

### Status
[ ] pending

---

## Sub-Task 2 — Add `_mcp_tool_name` helper and update `scan_openapi` to use `operationId`

### Intent
When an OpenAPI operation has an `operationId`, use it — together with a copied version of
nanobot's sanitise+truncate rule — to derive the tool name.  Fall back to the current
path-based approach only when `operationId` is absent, so non-fastapi_mcp specs still work.

### Expected Outcomes
- For an operation with `operationId: "cancel_booking_endpoint_cancel_booking_id_post"` and
  `server_name="galaxium"`, `scan_openapi` produces
  `mcp_galaxium_cancel_booking_endpoint_cancel_booking_id_post`.
- For a name that would exceed 64 chars after `mcp_{server_name}_` prefix, the helper
  truncates to 55 chars + `_` + 8-char SHA-1 digest (total ≤ 64).
- `scan_openapi` gains a `server_name: str = ""` keyword argument; existing callers that
  pass only `source` are unaffected.
- Existing `test_scan_openapi_from_file` still passes (test spec has no `operationId`, so
  path-based fallback runs; `"cancel"` keyword still detected via the route string).
- A new test `test_scan_openapi_uses_operation_id` (added in Sub-Task 4) will cover the
  `operationId` path.

### Todo List
1. Add two module-level constants near the top of `toolfence/engine/surface.py`
   (after `_EMPTY_SHA256`):
   ```python
   _MAX_MCP_TOOL_NAME = 64
   _HASH_LEN = 8
   ```
2. Add a module-level helper `_mcp_tool_name(server_name: str, operation_id: str) -> str`
   immediately after those constants.  Use the corrected implementation (see C1 in
   Corrections section — the brief's regex preserves hyphens/uppercase which would fail
   `_is_valid_name`):
   ```python
   _SANITIZE_RE = re.compile(r"[^a-z0-9_]+")  # lowercase; hyphens also replaced

   def _mcp_tool_name(server_name: str, operation_id: str) -> str:
       raw = _SANITIZE_RE.sub("_", f"mcp_{server_name}_{operation_id}".lower())
       if len(raw) <= _MAX_MCP_TOOL_NAME:
           return raw
       digest = hashlib.sha1(raw.encode()).hexdigest()[:_HASH_LEN]
       return f"{raw[:_MAX_MCP_TOOL_NAME - _HASH_LEN - 1]}_{digest}"
   ```
   No import from nanobot — this is a local copy of the rule.
3. Change the `scan_openapi` signature to accept `server_name: str = ""` as a keyword
   argument.
4. Inside the per-operation loop in `scan_openapi`, after the description block (which
   Sub-Task 3 already updated), read `operation_id = operation.get("operationId")`:
   - If `operation_id` is truthy: `tool_name = _mcp_tool_name(server_name, operation_id)`.
   - Otherwise: keep the existing path-based name-building block unchanged (lines 242–245).
5. Update the `scan_openapi` docstring "Notes" section to describe both the `operationId`
   path and the path-based fallback.
6. Run `pytest tests/test_surface.py` to verify no regressions.

### Relevant Context
- `toolfence/engine/surface.py` lines 207–252: `scan_openapi` method
- `toolfence/engine/surface.py` lines 46–49: location for new constants (after `_EMPTY_SHA256`)
- `_is_valid_name` at line 375 uses `^[a-z0-9_]+$` — the corrected helper always produces
  output that passes this check.
- `hashlib` is already imported at line 36; no new imports needed.
- `re` is already imported at line 38; `_SANITIZE_RE` is a new module-level compile.

### Status
[ ] pending

---

## Sub-Task 3 — Mirror `fastapi_mcp` description concatenation in `scan_openapi` and document the remaining gap

### Intent
`fastapi_mcp` builds the MCP tool description as:
```
"{summary}\n\n{description}\n\n### Responses:\n{response_schema}"
```
`scan_openapi` currently reads `description or summary` — a single field.  We can partially
close the gap by mirroring the `summary + "\n\n" + description` concatenation.  The
`response_info` (response-schema block) cannot be reconstructed without schema introspection;
that remaining gap is documented.

### Expected Outcomes
- `scan_openapi` builds the description string as:
  - `summary + "\n\n" + description` when both are present.
  - `summary` when only summary is present.
  - `description` when only description is present.
  - `""` when neither is present.
- The `description_sha256` now matches `fastapi_mcp`'s description up to the
  `response_info` suffix.
- `scan_openapi` docstring gains a `"Limitations"` note explaining that `response_info` is
  still not included and directing callers to `scan_mcp` / `scan_json` for bit-exact hashes.
- `tests/test_surface.py::test_scan_openapi_from_file` still passes (the test does not
  assert specific hash values).

### Todo List
1. In `scan_openapi`, replace the existing single-field description extraction:
   ```python
   # old
   description = (
       operation.get("description")
       or operation.get("summary")
       or ""
   )
   ```
   with the concatenation logic:
   ```python
   summary = operation.get("summary") or ""
   body = operation.get("description") or ""
   if summary and body:
       description = f"{summary}\n\n{body}"
   elif summary:
       description = summary
   else:
       description = body
   ```
2. In the `scan_openapi` docstring, add a `"Limitations"` section (after the updated
   `"Notes"`) that explains:
   - `fastapi_mcp` appends a `### Responses:` block derived from response schemas; this
     cannot be reconstructed from the OpenAPI spec alone.
   - The `description_sha256` values produced by `scan_openapi` will therefore still differ
     from what nanobot reports for `fastapi_mcp`-backed servers by the `response_info` suffix.
   - For bit-exact hashes, use `scan_mcp(url)` against a live server, or `scan_json` with a
     captured MCP tool list.
3. Run `pytest tests/test_surface.py` to confirm nothing regressed.

### Relevant Context
- `toolfence/engine/surface.py` lines 236–240: current description extraction (the lines to replace)
- `fastapi_mcp` assembly (from task brief): `summary → "\n\n" + description → response_info`
- The fixture `description_sha256` values are recomputed in Sub-Task 1 to use the same
  `summary + "\n\n" + description` rule, so they stay consistent with the updated scanner.

### Status
[ ] pending

---

## Sub-Task 4 — Add/update tests to cover the new `operationId` behaviour

### Intent
The existing `test_scan_openapi_from_file` test has no `operationId` in its spec, so it
exercises only the fallback path. A new test is needed to assert that `scan_openapi` uses
`operationId` when present and applies truncation correctly.

### Expected Outcomes
- `test_scan_openapi_uses_operation_id` passes: given a spec with an `operationId`, the
  resulting tool name matches the output of `_mcp_tool_name`.
- `test_scan_openapi_truncates_long_operation_id` passes: given an operation whose
  `mcp_{server}_{operationId}` exceeds 64 chars, the name is truncated with SHA-1 suffix.
- All existing tests continue to pass.

### Todo List
1. In `tests/test_surface.py`, import `_mcp_tool_name` from `toolfence.engine.surface`
   (it will be module-level after Sub-Task 2).
2. Add `test_scan_openapi_uses_operation_id`: build a minimal spec with one operation that
   carries `operationId: "cancel_booking_endpoint_cancel_booking_id_post"`, call
   `scan_openapi(tmp, server_name="galaxium")`, assert the tool name equals
   `"mcp_galaxium_cancel_booking_endpoint_cancel_booking_id_post"`.
3. Add `test_scan_openapi_truncates_long_operation_id`: build a spec with an `operationId`
   that produces a raw name > 64 chars, call `scan_openapi`, assert the resulting name
   is ≤ 64 chars and ends with an 8-char hex suffix.
4. Run `pytest tests/test_surface.py` — all tests must pass.

### Relevant Context
- `tests/test_surface.py` lines 262–303: existing `test_scan_openapi_from_file` — new tests
  follow the same pattern (temp file, `SurfaceScanner()`, assertions on `surface.tools`).
- `_mcp_tool_name` will be importable from `toolfence.engine.surface` after Sub-Task 2.

### Status
[ ] pending

---

## Corrections to earlier plan draft — applied

The following issues were caught during re-validation and are now reflected in the sub-tasks above:

### C1 — `_mcp_tool_name` must lowercase its output
The brief's sanitise regex `r"[^a-zA-Z0-9_-]"` preserves uppercase letters and hyphens.
`_build_surface` calls `_is_valid_name` which requires `^[a-z0-9_]+$` — uppercase or
hyphens would cause the name to be silently dropped. Sub-Task 2 must add a `.lower()` call
and replace `-` with `_` after the sanitise step (or widen the sanitise regex to also catch
`-`). The correct implementation is:
```python
_SANITIZE_RE = re.compile(r"[^a-z0-9_]+")   # lowercase only; replaces hyphens too

def _mcp_tool_name(server_name: str, operation_id: str) -> str:
    raw = _SANITIZE_RE.sub("_", f"mcp_{server_name}_{operation_id}".lower())
    if len(raw) <= _MAX_MCP_TOOL_NAME:
        return raw
    digest = hashlib.sha1(raw.encode()).hexdigest()[:_HASH_LEN]
    return f"{raw[:_MAX_MCP_TOOL_NAME - _HASH_LEN - 1]}_{digest}"
```
This matches nanobot's effective output (nanobot sanitises then lowercases via the
`mcp_` convention and FastAPI operationId convention) while guaranteeing the result
passes `_is_valid_name`.

### C2 — Sub-Task ordering: description concatenation change must precede fixture hash recompute
Sub-Task 3 introduces the `summary + "\n\n" + description` concatenation into
`scan_openapi`. Sub-Task 1 says "recompute all 5 hashes using the new rule." Those two
must happen in the right order: implement Sub-Task 3 first, then run the hash-recompute
script. The implementation order below reflects this.

### C3 — Two existing tests reference old wrong fixture names and will break after Sub-Task 1
- `tests/test_surface.py` line 123: `get_action_class(surface, "mcp_galaxium_cancel_booking__booking_id__post")`
  loads the fixture and looks up the old name — it will silently return `"state-changing"`
  (BASE-2 default) instead of `"irreversible"` after the rename, causing the assertion to fail.
- `tests/test_surface.py` line 314: `test_scan_mcp_with_mock_server` feeds the old wrong
  name as inline mock data — this does not break the test but leaves stale data that will
  confuse future readers.

Sub-Task 1 must also update these two test references as part of the same change.

---

## Implementation Order

```
Sub-Task 3 (description concat in scan_openapi)
  → Sub-Task 2 (operationId helper + server_name param)
    → Sub-Task 1 (fixture: rename 3 entries + recompute 5 hashes + fix 2 test references)
      → Sub-Task 4 (new operationId + truncation tests)
```

**Rationale for reorder:**
- Sub-Task 3 must land first so the hash-recompute script in Sub-Task 1 uses the correct
  concatenation rule.
- Sub-Task 2 must land before Sub-Task 1 so `_mcp_tool_name` is available to verify the
  three corrected names are exactly what the helper would produce.
- Sub-Task 4 depends on `_mcp_tool_name` being importable (Sub-Task 2).
