"""Load ETL config from YAML — no editable sheets, single source of truth for pipeline config."""

from pathlib import Path
from typing import Any

import yaml


def load_config(config_path: str | Path | None = None) -> dict[str, Any]:
    base = Path(__file__).resolve().parent.parent.parent
    path = Path(config_path) if config_path else base / "config" / "sources.yaml"
    if not path.is_absolute():
        path = base / path
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)
