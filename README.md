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
