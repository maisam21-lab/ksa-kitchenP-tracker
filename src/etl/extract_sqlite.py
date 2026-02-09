"""Extract data from SQLite — read from your own product's database."""

from pathlib import Path
from typing import Any


def extract_sqlite(
    db_path: str | Path,
    table_name: str = "ksa_kitchen_tracker",
    query: str | None = None,
) -> list[dict[str, Any]]:
    """
    Fetch rows from a SQLite database (e.g. from the Streamlit tracker app).
    Either table_name or query must be set.

    db_path: Path to the .db file (e.g. app/data/tracker.db)
    table_name: Table to select from (default ksa_kitchen_tracker). Ignored if query is set.
    query: Full SQL query (e.g. SELECT * FROM ksa_kitchen_tracker). If set, table_name is ignored.
    """
    import sqlite3

    path = Path(db_path)
    if not path.exists():
        raise FileNotFoundError(f"SQLite database not found: {path}")

    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        if query:
            cur = conn.execute(query)
        else:
            cur = conn.execute(f"SELECT * FROM {table_name}")
        return [dict(row) for row in cur]
    finally:
        conn.close()
