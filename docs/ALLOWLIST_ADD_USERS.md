# Why someone can't login (e.g. Jad, Tala) and how to add them

## Why Jad and Tala (or anyone) can't login

The app uses an **allowlist**: only users whose **email or name** is in the list can access the tracker when allowlist is enabled.

- **"Access restricted. Your name or email is not on the authorized list."** means the exact text they entered in the sidebar (e.g. `jad@company.com` or `Jad`) is **not** in the allowlist.
- The check is **case-insensitive** (e.g. `Jad` and `jad` are the same).

So **Jad and Tala couldn't login because their email or name was not on the allowlist** at the time they tried.

## Where the allowlist lives

1. **Streamlit secrets** (e.g. in Cloud): `ALLOWLIST_IDS` or `[allowlist_ids]` — list of emails/names.
2. **Environment variable**: `ALLOWLIST_IDS` (JSON array or comma-separated).
3. **Database**: table `allowed_users` (identifier, added_at, role) — managed via Developer UI in the app (Admin section) or by editing the DB.

If **allowlist is enabled** (`ALLOWLIST_ENABLED=1` or in secrets), only identifiers in (1), (2), or (3) can access.

## How to add Jad and Tala (and others)

**Option A — Streamlit Cloud / secrets**  
Add their emails (or names) to the allowlist in your secrets, e.g.:

```toml
ALLOWLIST_IDS = ["maysam.abukashabeh@cloudkitchens.com", "jad@company.com", "tala@company.com"]
```

Or if you use a TOML list:

```toml
[allowlist_ids]
ids = ["maysam.abukashabeh@cloudkitchens.com", "jad@company.com", "tala@company.com"]
```

Use the **exact** email (or name) they will type in the sidebar. Redeploy/restart the app after changing secrets.

**Option B — Database (allowed_users table)**  
If the app has an Admin section and you have super_user/developer access, you can add users there. Otherwise, add rows to `app/data/tracker.db` table `allowed_users`:

```sql
INSERT INTO allowed_users (identifier, added_at, role) VALUES ('jad@company.com', datetime('now'), 'associate_viewer');
INSERT INTO allowed_users (identifier, added_at, role) VALUES ('tala@company.com', datetime('now'), 'associate_viewer');
```

Replace with the real emails (or names) they use to log in.

**Option C — Developer key**  
If they have the developer key, they can unlock without being on the allowlist (for testing only).

## After adding

Ask Jad and Tala to **reload the app** and enter the **same** email or name you added (e.g. the work email they use). They should then get in.
