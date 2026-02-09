"""Single pipeline: extract → validate → transform → load. No shared state, repeatable runs."""

from pathlib import Path
from typing import Any, Callable

from .config_loader import load_config
from .validate import load_schema, validate_rows
from .extract_airtable import extract_airtable
from .extract_google_sheets import extract_google_sheets
from .extract_bigquery import extract_bigquery
from .extract_sqlite import extract_sqlite


def extract_file(path: Path) -> list[dict[str, Any]]:
    import csv
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def transform_passthrough(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Default: no transform. Replace with aggregations, renames, lookups as needed."""
    return rows


def load_file(rows: list[dict[str, Any]], out_path: Path) -> None:
    import csv
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        return
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def run_pipeline(
    config_path: str | Path | None = None,
    transform: Callable[[list[dict]], list[dict]] | None = None,
) -> dict[str, Any]:
    """
    Run ETL: extract from configured sources → validate → transform → load.
    Returns run summary (counts, errors) for auditability.
    """
    config = load_config(config_path)
    base = Path(__file__).resolve().parent.parent.parent
    transform_fn = transform or transform_passthrough
    summary = {"sources": [], "valid": 0, "invalid": 0, "loaded": 0}

    for source in config.get("sources", []):
        schema = load_schema(source["schema_ref"])
        if source["type"] == "file":
            path = base / source["path"]
            rows = extract_file(path)
        elif source["type"] == "airtable":
            rows = extract_airtable(
                base_id=source["base_id"],
                table_name=source["table_name"],
                api_key=source.get("api_key"),
                field_mapping=source.get("field_mapping"),
            )
        elif source["type"] == "google_sheets":
            creds_path = source.get("credentials_path")
            if creds_path and not Path(creds_path).is_absolute():
                creds_path = str(base / creds_path)
            rows = extract_google_sheets(
                sheet_id=source["sheet_id"],
                table_name_or_gid=source["table_name_or_gid"],
                credentials_path=creds_path,
            )
        elif source["type"] == "bigquery":
            bq_creds = source.get("credentials_path")
            if bq_creds and not Path(bq_creds).is_absolute():
                bq_creds = str(base / bq_creds)
            rows = extract_bigquery(
                project_id=source["project_id"],
                dataset_id=source["dataset_id"],
                table_id=source.get("table_id"),
                query=source.get("query"),
                credentials_path=bq_creds,
            )
        elif source["type"] == "sqlite":
            db_path = source["db_path"]
            if not Path(db_path).is_absolute():
                db_path = base / db_path
            rows = extract_sqlite(
                db_path=db_path,
                table_name=source.get("table_name", "ksa_kitchen_tracker"),
                query=source.get("query"),
            )
        else:
            raise ValueError(f"Unsupported source type: {source['type']}")

        valid, invalid = validate_rows(rows, schema)
        summary["valid"] += len(valid)
        summary["invalid"] += len(invalid)
        summary["sources"].append({
            "id": source["id"],
            "extracted": len(rows),
            "valid": len(valid),
            "invalid": len(invalid),
        })

        if invalid:
            quarantine = base / "data" / "quarantine" / f"{source['id']}_invalid.csv"
            quarantine.parent.mkdir(parents=True, exist_ok=True)
            load_file(invalid, quarantine)

        modeled = transform_fn(valid)
        summary["loaded"] += len(modeled)

        out_cfg = config.get("output", {})
        if out_cfg.get("type") == "file":
            out_path = base / out_cfg["path"] / f"{source['id']}.csv"
            load_file(modeled, out_path)
        # Add BigQuery loader here when ready:
        # elif out_cfg.get("type") == "bigquery": ...

    return summary
