from __future__ import annotations

import json
from pathlib import Path

from jsonschema import validate

ROOT = Path(__file__).resolve().parents[1]
schema = json.loads((ROOT / "schemas" / "latest.schema.json").read_text(encoding="utf-8"))
latest = json.loads((ROOT / "data" / "latest.json").read_text(encoding="utf-8"))
validate(latest, schema)
print("latest_json_schema=valid")

