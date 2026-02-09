"""Extract data from Airtable API — replaces Google Sheets as the tracker source."""

import os
from typing import Any

def extract_airtable(
    base_id: str,
    table_name: str,
    api_key: str | None = None,
    field_mapping: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """
    Fetch all records from an Airtable table. Uses offset pagination (max 100 per page).
    api_key: from config or set env AIRTABLE_API_KEY.
    field_mapping: optional dict mapping Airtable field names to schema names, e.g. {"Record ID": "record_id"}.
    """
    try:
        import requests
    except ImportError:
        raise ImportError("Install requests: pip install requests") from None

    token = api_key or os.environ.get("AIRTABLE_API_KEY")
    if not token:
        raise ValueError("Airtable API key required: set in config (api_key) or env AIRTABLE_API_KEY")

    url = f"https://api.airtable.com/v0/{base_id}/{table_name}"
    headers = {"Authorization": f"Bearer {token}"}
    rows: list[dict[str, Any]] = []
    offset = None

    while True:
        params = {}
        if offset:
            params["offset"] = offset
        resp = requests.get(url, headers=headers, params=params if params else None, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        for rec in data.get("records", []):
            fields = rec.get("fields", {})
            row = dict(fields)
            if field_mapping:
                row = {field_mapping.get(k, k): v for k, v in row.items()}
            if row:
                rows.append(row)
        offset = data.get("offset")
        if not offset:
            break

    return rows
