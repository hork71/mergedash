# mergedash

A small dashboard that displays GitLab merge request results stored in a
PostgreSQL table (`gitlabmerges`, see `table.sql`). Merge requests are shown
per project, grouped by month, with status information per MR and — for
merged MRs — who merged and approved them.

The web UI has a searchable project dropdown, start/end month dropdowns
(populated from the data), and a **Go** button that renders one table per
month.

Two interchangeable backend implementations are included. Both serve the
identical JSON API and the same frontend, so you can run either one:

| | Node.js | Python |
|---|---|---|
| Entry point | `server.js` | `app.py` |
| Dependencies | `pg` (PostgreSQL driver only) | `flask`, optionally `psycopg2-binary` |

Shared files:

- `public/index.html` — the entire frontend (vanilla JS/CSS, no libraries)
- `fake-data.json` — development stub data
- `table.sql` — table definition for the real database

## Data source

Both versions default to **fake data** from `fake-data.json` so they run
without a database. Set `USE_DB=1` to switch to **PostgreSQL**, configured
via either:

- the standard `PG*` environment variables (`PGHOST`, `PGPORT`,
  `PGDATABASE`, `PGUSER`, `PGPASSWORD`), or
- a single `DATABASE_URL`, e.g. `postgres://user:pass@host:5432/dbname`

Both servers listen on **http://localhost:3000** (override with `PORT`).
Run only one at a time, or give them different ports.

## Node.js version

Requires Node.js 18+.

```sh
npm install

# with fake data
npm start

# with PostgreSQL
USE_DB=1 PGDATABASE=yourdb PGUSER=youruser PGPASSWORD=secret npm start
# or
USE_DB=1 DATABASE_URL=postgres://user:pass@host/dbname npm start
```

## Python (Flask) version

Requires Python 3.9+.

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# with fake data
.venv/bin/python app.py

# with PostgreSQL (psycopg2-binary is only needed for this mode)
USE_DB=1 PGDATABASE=yourdb PGUSER=youruser PGPASSWORD=secret .venv/bin/python app.py
# or
USE_DB=1 DATABASE_URL=postgres://user:pass@host/dbname .venv/bin/python app.py
```

## Authentication (Flask version only)

The Flask backend (`app.py`) can require sign-in against Active Directory
before serving the dashboard or its API, using a service account to search
AD and a required-group check. The Node.js version (`server.js`) has no
authentication and is intended for local/demo use only — use the Flask
version for any AD-integrated or production deployment.

Set `USE_LDAP=1` plus:

- `LDAP_SERVER` — AD host, e.g. `ldaps://ad.example.com:636`
- `LDAP_BASE_DN` — search base, e.g. `DC=example,DC=com`
- `LDAP_USER_ATTR` — attribute matched against the login username
  (default `sAMAccountName`)
- `LDAP_BIND_DN` / `LDAP_BIND_PASSWORD` — service account used to search AD
- `LDAP_REQUIRED_GROUP_DN` — users must belong to this group (including via
  nested groups) to be granted access
- `LDAP_USE_SSL` — `1` (default) to use LDAPS, `0` for plaintext (test only)
- `SECRET_KEY` — random secret used to sign the session cookie; required
  whenever `USE_LDAP=1`

```sh
USE_LDAP=1 \
LDAP_SERVER=ldaps://ad.example.com:636 \
LDAP_BASE_DN="DC=example,DC=com" \
LDAP_BIND_DN="CN=svc-mergedash,OU=Service Accounts,DC=example,DC=com" \
LDAP_BIND_PASSWORD=secret \
LDAP_REQUIRED_GROUP_DN="CN=Mergedash Users,OU=Groups,DC=example,DC=com" \
SECRET_KEY=$(python3 -c "import secrets;print(secrets.token_hex(32))") \
.venv/bin/python app.py
```

When `USE_LDAP` is unset (default), the app behaves exactly as before — no
login is required. `USE_LDAP` and `USE_DB` are independent switches and can
be combined (AD login + PostgreSQL data), or either can be used alone.

## API

Both backends expose the same three endpoints:

- `GET /api/projects` — sorted list of distinct project names
- `GET /api/months` — sorted list of distinct months (`YYYY-MM`)
- `GET /api/merges?project=<name>&from=<YYYY-MM>&to=<YYYY-MM>` — merge
  requests for one project within an inclusive month range, sorted newest
  first. Returns `400` if any parameter is missing.

## Setting up the real table

```sh
psql -d yourdb -f table.sql
```

Note: the month range filter compares the `month` column as text, which is
correct as long as months are stored in a sortable `YYYY-MM` format.

## Four-eyes check for production merges

Each MR carries its `source_branch` and `target_branch` (as reported by the
GitLab API). For MRs merged into the production branch, the author and the
person who merged must be different people: violations are marked with a
"⚠ self-merged" badge on the *Merged by* cell and counted in the status
line. Which branch names count as production is configured in the
`PRODUCTION_BRANCHES` constant at the top of the script in
`public/index.html` (default: `['production']`). Existing databases need the
two extra columns — see the `ALTER TABLE` comment in `table.sql`.
