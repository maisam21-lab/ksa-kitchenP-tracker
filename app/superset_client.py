"""
Superset API client: login, CSRF, and Chart Data API.
Uses GET /api/v1/chart/{id}/data/ (query context stored with chart).
Auth: username/password or pre-generated SUPERSET_ACCESS_TOKEN from env.
"""
import logging
import os
from typing import Optional

import requests

logger = logging.getLogger(__name__)

try:
    import pandas as pd
except ImportError:
    pd = None


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default).strip()


def _get_base_url() -> str:
    url = _env("SUPERSET_URL") or _env("SUPSERSET_URL")
    return url.rstrip("/") if url else ""


class SupersetClient:
    """Authenticates to Superset and fetches chart data via Chart Data API."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        access_token: Optional[str] = None,
        timeout: int = 90,
    ):
        self.base_url = (base_url or _get_base_url()).rstrip("/")
        self.username = username or _env("SUPERSET_USERNAME") or _env("SUPSERSET_USERNAME")
        self.password = password or _env("SUPERSET_PASSWORD") or _env("SUPSERSET_PASSWORD")
        self.access_token = access_token or _env("SUPERSET_ACCESS_TOKEN")
        self.timeout = timeout
        self.session = requests.Session()
        self._csrf_token: Optional[str] = None

    def get_csrf_token(self) -> Optional[str]:
        """Fetch CSRF token from Superset (for cookie-based session)."""
        if not self.base_url:
            logger.error("Superset base URL not set")
            return None
        try:
            r = self.session.get(
                f"{self.base_url}/api/v1/security/csrf_token/",
                timeout=self.timeout,
            )
            r.raise_for_status()
            data = r.json()
            self._csrf_token = data.get("result")
            return self._csrf_token
        except requests.exceptions.RequestException as e:
            logger.exception("Failed to get CSRF token: %s", e)
            return None

    def login(self) -> bool:
        """
        Login with username/password or use pre-generated access token.
        Handles CSRF and session cookies when using username/password.
        """
        if not self.base_url:
            logger.error("Superset base URL not set (SUPERSET_URL)")
            return False

        if self.access_token:
            self.session.headers["Authorization"] = f"Bearer {self.access_token}"
            # Verify token works
            try:
                r = self.session.get(
                    f"{self.base_url}/api/v1/me/",
                    timeout=self.timeout,
                )
                if r.status_code == 200:
                    return True
                logger.warning("SUPERSET_ACCESS_TOKEN returned %s", r.status_code)
            except requests.exceptions.RequestException as e:
                logger.exception("Token auth check failed: %s", e)
            return False

        if not self.username or not self.password:
            logger.error("Set SUPERSET_USERNAME/SUPERSET_PASSWORD or SUPERSET_ACCESS_TOKEN")
            return False

        self.get_csrf_token()
        try:
            r = self.session.post(
                f"{self.base_url}/api/v1/security/login",
                json={"username": self.username, "password": self.password, "provider": "db"},
                headers={"Content-Type": "application/json"},
                timeout=self.timeout,
            )
            if r.status_code == 401:
                logger.error("Superset login 401 Unauthorized")
                return False
            if r.status_code == 403:
                logger.error("Superset login 403 Forbidden (SSO may block automated login; use SUPERSET_ACCESS_TOKEN)")
                return False
            r.raise_for_status()
            data = r.json()
            token = data.get("access_token")
            if token:
                self.session.headers["Authorization"] = f"Bearer {token}"
            return True
        except requests.exceptions.Timeout:
            logger.exception("Superset login timeout")
            return False
        except requests.exceptions.RequestException as e:
            logger.exception("Superset login failed: %s", e)
            return False

    def fetch_chart_data(self, chart_id: int):
        """
        Fetch chart data via GET /api/v1/chart/{chart_id}/data/.
        Returns pandas.DataFrame with correct column names, or None on failure.
        """
        if pd is None:
            logger.error("pandas required for fetch_chart_data")
            return None
        if not self.base_url:
            logger.error("Superset base URL not set")
            return None
        if not self.session.headers.get("Authorization") and not self.login():
            return None

        url = f"{self.base_url}/api/v1/chart/{chart_id}/data/"
        try:
            r = self.session.get(url, timeout=self.timeout)
            if r.status_code == 401:
                logger.error("Chart data 401: re-auth may be required")
                return None
            if r.status_code == 403:
                logger.error("Chart data 403: no permission for chart %s", chart_id)
                return None
            if r.status_code == 400:
                logger.error("Chart data 400: chart %s may have no query context saved (save chart in UI)", chart_id)
                return None
            r.raise_for_status()
            data = r.json()
        except requests.exceptions.Timeout:
            logger.exception("Chart data timeout for chart_id=%s", chart_id)
            return None
        except requests.exceptions.RequestException as e:
            logger.exception("Chart data request failed for chart_id=%s: %s", chart_id, e)
            return None

        # Response shape: often { "result": [ { "data": [...], "colnames": [...] }, ... ] }
        result = data.get("result") or []
        if not result:
            logger.warning("Chart %s returned empty result", chart_id)
            return pd.DataFrame()

        # Use first result slice
        first = result[0] if isinstance(result, list) else result
        if isinstance(first, list):
            # List of rows
            return pd.DataFrame(first)
        if isinstance(first, dict):
            data_rows = first.get("data", first.get("rows", []))
            colnames = first.get("colnames", first.get("columns", []))
            if colnames and data_rows:
                return pd.DataFrame(data_rows, columns=colnames)
            if data_rows:
                return pd.DataFrame(data_rows)
        return pd.DataFrame()

    def fetch_saved_query_results(self, query_id: int):
        """
        Fallback: run a Saved SQL Lab query and return results as DataFrame.
        Uses GET /api/v1/saved_query/{query_id}/ or equivalent.
        """
        if pd is None:
            return None
        if not self.base_url or (not self.session.headers.get("Authorization") and not self.login()):
            return None
        # Superset: saved query results may be under /api/v1/sql_lab/ or saved_query
        url = f"{self.base_url}/api/v1/saved_query/{query_id}/"
        try:
            r = self.session.get(url, timeout=self.timeout)
            if r.status_code != 200:
                logger.warning("Saved query %s returned %s", query_id, r.status_code)
                return None
            meta = r.json()
            # If API returns result payload for execution, use it; else try execute endpoint
            result_url = meta.get("result_url") or f"{self.base_url}/api/v1/sql_lab/{query_id}/"
            r2 = self.session.get(result_url, timeout=self.timeout)
            r2.raise_for_status()
            data = r2.json()
            res = data.get("result") or data.get("data") or data
            if isinstance(res, list):
                return pd.DataFrame(res)
            if isinstance(res, dict) and "data" in res:
                return pd.DataFrame(res["data"], columns=res.get("columns", []))
            return pd.DataFrame()
        except Exception as e:
            logger.exception("Saved query fetch failed: %s", e)
            return None
