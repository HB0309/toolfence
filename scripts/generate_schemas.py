"""Generate JSON Schemas from the Pydantic models in toolfence/contracts/.

Run once (or whenever a model changes) and commit the output:

    python scripts/generate_schemas.py

The four files written are:
    toolfence/contracts/schemas/surface.schema.json
    toolfence/contracts/schemas/trace.schema.json
    toolfence/contracts/schemas/trial.schema.json
    toolfence/contracts/schemas/profile.schema.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Make sure the package is importable when run from the repo root.
sys.path.insert(0, str(Path(__file__).parent.parent))

from toolfence.contracts.profile import TargetProfile
from toolfence.contracts.surface import SurfaceFile
from toolfence.contracts.trace import Trace
from toolfence.contracts.trial import TrialRecord

SCHEMAS_DIR = Path(__file__).parent.parent / "toolfence" / "contracts" / "schemas"
SCHEMAS_DIR.mkdir(parents=True, exist_ok=True)

_TARGETS = [
    (SurfaceFile,   "surface.schema.json"),
    (Trace,         "trace.schema.json"),
    (TrialRecord,   "trial.schema.json"),
    (TargetProfile, "profile.schema.json"),
]


def main() -> None:
    for model_cls, filename in _TARGETS:
        schema = model_cls.model_json_schema()
        # Add the standard $schema declaration so validators know the dialect.
        schema.setdefault("$schema", "https://json-schema.org/draft/2020-12/schema")
        out = SCHEMAS_DIR / filename
        out.write_text(json.dumps(schema, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {out.relative_to(Path.cwd())}")


if __name__ == "__main__":
    main()
