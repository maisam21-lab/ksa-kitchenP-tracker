# Why someone can't login (e.g. Jad, Tala) and how to add them

## Access tiers (who sees what)

| Who | What they see |
|-----|----------------|
| **Developer (Maysam)** | Full access. Sign in with **developer key** only — keep the key secret. |
| **Super users** | Master Kitchen Data + **Dashboard** + Discussions + Admin / Data Health. Add their emails to `DEVELOPER_IDS` or `SUPER_USER_EMAILS` in secrets. |
| **Normal users** | Master Kitchen Data + Discussions only. Add their emails to `ALLOWLIST_IDS` only (do not add to DEVELOPER_IDS/SUPER_USER_EMAILS). |

---

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

---

## What to do now (you have a set of user emails)

You can add users and assign roles in two ways.

### Option 1 — In the app (easiest if you don’t use ALLOWLIST_IDS in secrets)

1. **Sign in as developer** (sidebar → Developer access → enter your developer key).
2. Open **Admin / Data Health**.
3. Under **Add user**:
   - Enter each email in **Email (or name)**.
   - Choose **Role**:
     - **Normal (Master Kitchens + Discussions)** — they only see Kitchen Master Data and Discussions.
     - **Manager (+ Dashboard)** — also see Dashboard.
     - **Super user (all tabs)** — see everything including Admin.
   - Click **Add user**.
4. Repeat for every email. You can **Remove** anyone from the list in the same page.

**Note:** If you have **ALLOWLIST_IDS** set in Streamlit secrets, the app overwrites this list on each restart from secrets. In that case use Option 2.

### Option 2 — Streamlit Cloud secrets (good for production)

1. In **Streamlit Cloud** → your app → **Settings** → **Secrets**.
2. Enable the allowlist and list everyone who may access the app:
   ```toml
   ALLOWLIST_ENABLED = true
   ALLOWLIST_IDS = ["user1@company.com", "user2@company.com", "user3@company.com"]
   ```
   (Use the exact emails users sign in with.)
3. Give **super user** to people who should see all tabs (including Dashboard and Admin). **They must also be in `ALLOWLIST_IDS`** or they cannot sign in.

   **Option A — `DEVELOPER_IDS` (reliable):**  
   Add super user emails to **DEVELOPER_IDS** (same secret as developer access). Anyone in this list gets Dashboard and Admin when they sign in (no developer key needed):
   ```toml
   DEVELOPER_IDS = "maysam.abukashabeh@cloudkitchens.com,jad.hajjar@cloudkitchens.com,tala.zeineddine@cloudkitchens.com,yazan.saeed@cloudkitchens.com,tarek.trad@cloudkitchens.com"
   ```

   **Option B — `SUPER_USER_EMAILS`:**  
   Same idea, separate list (comma-separated):
   ```toml
   SUPER_USER_EMAILS = "admin@company.com,jad.hajjar@cloudkitchens.com,tala.zeineddine@cloudkitchens.com"
   ```

   **Option C — `[allowed_user_roles]` dict:**  
   ```toml
   [allowed_user_roles]
   "admin@company.com" = "super_user"
   "manager@company.com" = "super_user"
   ```
   To give someone Dashboard but not Admin: `"someone@company.com" = "manager_viewer"`

   Anyone in `ALLOWLIST_IDS` but not listed as super/manager gets **Normal** (Master Kitchens + Discussions only).
4. Save and **redeploy** the app.

**Developer access** stays separate: only people with the developer key (or listed in developer IDs in secrets) get full access; you keep that for yourself.
