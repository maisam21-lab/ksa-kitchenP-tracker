"""Schema validation — enforces structure before data reaches Looker Studio."""

import json
from pathlib import Path
from typing import Any

import jsonschema


def load_schema(schema_ref: str, schemas_dir: Path | None = None) -> dict[str, Any]:
    base = Path(__file__).resolve().parent.parent.parent
    dir_ = schemas_dir or (base / "config" / "schemas")
    path = dir_ / f"{schema_ref}.json"
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def validate_rows(rows: list[dict[str, Any]], schema: dict[str, Any]) -> tuple[list[dict], list[dict]]:
    """Validate each row; return (valid_rows, invalid_rows with _error)."""
    valid, invalid = [], []
    for i, row in enumerate(rows):
        try:
            jsonschema.validate(instance=row, schema=schema)
            valid.append(row)
        except jsonschema.ValidationError as e:
            invalid.append({**row, "_error": str(e), "_row_index": i})
    return valid, invalid
