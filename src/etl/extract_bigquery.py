"""Extract data from Google BigQuery API — read from a table or run a query."""

from typing import Any


def extract_bigquery(
    project_id: str,
    dataset_id: str,
    table_id: str | None = None,
    query: str | None = None,
    credentials_path: str | None = None,
) -> list[dict[str, Any]]:
    """
    Fetch rows from BigQuery via the Google BigQuery API.
    Either (dataset_id + table_id) or (query) must be set.

    project_id: GCP project ID
    dataset_id: BigQuery dataset ID
    table_id: BigQuery table ID (optional if query is set)
    query: Full SQL query (e.g. SELECT * FROM `project.dataset.table`). If set, table_id is ignored.
    credentials_path: Optional path to service account JSON. Else uses GOOGLE_APPLICATION_CREDENTIALS or default credentials.
    """
    try:
        from google.cloud import bigquery
        from google.oauth2 import service_account
    except ImportError:
        raise ImportError("Install: pip install google-cloud-bigquery") from None

    if credentials_path:
        creds = service_account.Credentials.from_service_account_file(credentials_path)
        client = bigquery.Client(project=project_id, credentials=creds)
    else:
        client = bigquery.Client(project=project_id)
    if query:
        job = client.query(query)
    else:
        query = f"SELECT * FROM `{project_id}.{dataset_id}.{table_id}`"
        job = client.query(query)

    rows = job.result()
    return [dict(row) for row in rows]
