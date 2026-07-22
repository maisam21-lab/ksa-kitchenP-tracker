"""
Export the [gsheet_service_account] block from .streamlit/secrets.toml to
.secrets/gsheet-service.json so cron jobs (refresh_jobs/refresh_gsheet.py) can
use it — cron cannot read Streamlit secrets.

Run on the server that already has the app secrets configured:
  python scripts/export_gsheet_credentials.py

The output file stays on the same machine, is chmod 600, and .secrets/ is
gitignored. Existing output is left untouched unless --force is passed.
"""
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
# Streamlit reads secrets from the repo .streamlit/ first, then ~/.streamlit/
SECRETS_TOML_CANDIDATES = [
    REPO_ROOT / ".streamlit" / "secrets.toml",
    Path.home() / ".streamlit" / "secrets.toml",
]
OUT_PATH = REPO_ROOT / ".secrets" / "gsheet-service.json"


def _load_toml(path: Path) -> dict:
    try:
        import tomllib  # Python 3.11+
        with open(path, "rb") as f:
            return tomllib.load(f)
    except ImportError:
        pass
    try:
        import tomli
        with open(path, "rb") as f:
            return tomli.load(f)
    except ImportError:
        pass
    import toml  # streamlit dependency, always present in the app env
    return toml.load(path)


def main() -> int:
    secrets_toml = next((p for p in SECRETS_TOML_CANDIDATES if p.exists()), None)
    if secrets_toml is None:
        tried = ", ".join(str(p) for p in SECRETS_TOML_CANDIDATES)
        print(f"ERROR: no secrets.toml found (tried: {tried}). Run this on the server where the app secrets are configured.")
        return 1
    if OUT_PATH.exists() and "--force" not in sys.argv:
        print(f"{OUT_PATH} already exists. Re-run with --force to overwrite.")
        return 0
    secrets = _load_toml(secrets_toml)
    info = secrets.get("gsheet_service_account")
    if not isinstance(info, dict) or not info.get("private_key"):
        print(f"ERROR: [gsheet_service_account] block with a private_key not found in {secrets_toml}.")
        return 1
    print(f"Reading service account from {secrets_toml}")
    info = dict(info)
    # Same defaults the app applies in _fetch_online_sheet
    info.setdefault("token_uri", "https://oauth2.googleapis.com/token")
    info.setdefault("auth_uri", "https://accounts.google.com/o/oauth2/auth")
    info.setdefault("type", "service_account")
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(OUT_PATH, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(info, f, indent=2, ensure_ascii=False)
    os.chmod(OUT_PATH, 0o600)
    print(f"Wrote {OUT_PATH} (permissions 600).")
    print(f"Service account: {info.get('client_email', '<no client_email found>')}")
    print("refresh_jobs/refresh_gsheet.py will pick this up automatically.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
