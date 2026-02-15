"""
One-time script to get a Salesforce refresh token (no username/password in the app).
Run: python scripts/get_sf_refresh_token.py

Set SF_CONSUMER_KEY and SF_CONSUMER_SECRET in the environment, or paste them when prompted.
1. Open the URL this script prints in your browser.
2. Log in to Salesforce (sandbox or production).
3. After redirect, copy the FULL URL from the address bar and paste it here.
4. Script prints refresh_token — put it in Streamlit secrets as SF_REFRESH_TOKEN.
"""
import os
import urllib.parse
import urllib.request
import sys

# From env (never commit real values). Example: set SF_CONSUMER_KEY=... SF_CONSUMER_SECRET=... before running.
CONSUMER_KEY = (os.environ.get("SF_CONSUMER_KEY") or "").strip()
CONSUMER_SECRET = (os.environ.get("SF_CONSUMER_SECRET") or "").strip()
if not CONSUMER_KEY:
    CONSUMER_KEY = input("Paste your Connected App Consumer Key: ").strip()
if not CONSUMER_SECRET:
    CONSUMER_SECRET = input("Paste your Connected App Consumer Secret: ").strip()
if not CONSUMER_KEY or not CONSUMER_SECRET:
    print("Error: Consumer Key and Consumer Secret are required.")
    sys.exit(1)
USE_SANDBOX = True
# Use test.salesforce.com (instance URL rejects external callback like pstmn.io with "character not allowed")
LOGIN_HOST = "https://test.salesforce.com" if USE_SANDBOX else "https://login.salesforce.com"
# ME Reporting App callback (you can't change it) — must match Salesforce exactly
REDIRECT_URI_DEFAULT = "https://oauth.pstmn.io/v1/browser-callback"


def main():
    print("Using ME Reporting App callback (cannot be changed):", REDIRECT_URI_DEFAULT)
    redirect_uri_input = input("Paste different Callback URL or press Enter: ").strip()
    REDIRECT_URI = (redirect_uri_input if redirect_uri_input else REDIRECT_URI_DEFAULT).rstrip("/")
    print(f"redirect_uri: {REDIRECT_URI}\n")
    auth_url = (
        f"{LOGIN_HOST}/services/oauth2/authorize?"
        + urllib.parse.urlencode({
            "response_type": "code",
            "client_id": CONSUMER_KEY,
            "redirect_uri": REDIRECT_URI,
            "prompt": "consent",  # Force consent screen so Salesforce returns refresh_token
        })
    )
    print("Step 1: Open this URL in your browser and log in:\n")
    print(auth_url)
    print("\nStep 2: After login you'll be redirected. Copy the FULL URL from the address bar.")
    print(f"        It looks like: {REDIRECT_URI}?code=...\n")
    redirect_url = input("Paste the full redirect URL here: ").strip()
    if not redirect_url:
        print("No URL entered. Exiting.")
        sys.exit(1)
    parsed = urllib.parse.urlparse(redirect_url)
    params = urllib.parse.parse_qs(parsed.query)
    code = (params.get("code") or [None])[0]
    if not code:
        print("Could not find 'code' in the URL. Make sure you pasted the full redirect URL.")
        sys.exit(1)
    token_url = f"{LOGIN_HOST}/services/oauth2/token"
    data = urllib.parse.urlencode({
        "grant_type": "authorization_code",
        "code": code,
        "client_id": CONSUMER_KEY,
        "client_secret": CONSUMER_SECRET,
        "redirect_uri": REDIRECT_URI,
    }).encode("utf-8")
    req = urllib.request.Request(token_url, data=data, method="POST", headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        out = resp.read().decode()
    import json
    try:
        tokens = json.loads(out)
    except json.JSONDecodeError:
        print("Response was not JSON:", out[:500])
        sys.exit(1)
    refresh = tokens.get("refresh_token")
    if refresh:
        print("\n--- Success. Add this to Streamlit secrets as SF_REFRESH_TOKEN ---\n")
        print(refresh)
        print("\n--- End ---")
    else:
        print("Response did not contain refresh_token. Full response:", json.dumps(tokens, indent=2))


if __name__ == "__main__":
    main()
