"""Simple merge request dashboard server (Flask port of server.js).

Serves the same frontend (public/index.html) and the same JSON API.

Data source:
    default    -> fake-data.json (development stub)
    USE_DB=1   -> PostgreSQL, configured via the standard PG* environment
                  variables (PGHOST, PGDATABASE, ...) or DATABASE_URL.
"""

import json
import os
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

BASE_DIR = Path(__file__).resolve().parent
USE_DB = os.environ.get("USE_DB") == "1"

app = Flask(__name__)


# --- data layer: both backends expose projects(), months(), merges() ---

class FakeStore:
    def __init__(self):
        with open(BASE_DIR / "fake-data.json", encoding="utf-8") as f:
            self.rows = json.load(f)

    def _distinct(self, key):
        return sorted({r[key] for r in self.rows})

    def projects(self):
        return self._distinct("project")

    def months(self):
        return self._distinct("month")

    def merges(self, project, date_from, date_to):
        rows = [
            r for r in self.rows
            if r["project"] == project and date_from <= r["month"] <= date_to
        ]
        rows.sort(
            key=lambda r: (r["month"], r["created_at"], r["iid"]),
            reverse=True,
        )
        return rows


class DbStore:
    def _connect(self):
        import psycopg2
        # An explicit DATABASE_URL wins; otherwise psycopg2 picks up the
        # standard PG* environment variables.
        return psycopg2.connect(os.environ.get("DATABASE_URL", ""))

    def _query(self, sql, params=()):
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                return cur.fetchall()
        finally:
            conn.close()

    def projects(self):
        rows = self._query(
            "SELECT DISTINCT project FROM gitlabmerges ORDER BY project"
        )
        return [r[0] for r in rows]

    def months(self):
        rows = self._query(
            "SELECT DISTINCT month FROM gitlabmerges ORDER BY month"
        )
        return [r[0] for r in rows]

    def merges(self, project, date_from, date_to):
        rows = self._query(
            """
            SELECT month, iid, title, source_branch, target_branch, state, author,
                   to_char(created_at, 'YYYY-MM-DD') AS created_at,
                   to_char(merged_at, 'YYYY-MM-DD')  AS merged_at,
                   merged_by, approved_by, web_url
              FROM gitlabmerges
             WHERE project = %s AND month >= %s AND month <= %s
             ORDER BY month DESC, created_at DESC, iid DESC
            """,
            (project, date_from, date_to),
        )
        cols = ("month", "iid", "title", "source_branch", "target_branch",
                "state", "author", "created_at", "merged_at", "merged_by",
                "approved_by", "web_url")
        return [dict(zip(cols, r)) for r in rows]


store = DbStore() if USE_DB else FakeStore()


# --- routes ---

@app.route("/")
def index():
    return send_from_directory(BASE_DIR / "public", "index.html")


@app.route("/api/projects")
def api_projects():
    return jsonify(store.projects())


@app.route("/api/months")
def api_months():
    return jsonify(store.months())


@app.route("/api/merges")
def api_merges():
    project = request.args.get("project")
    date_from = request.args.get("from")
    date_to = request.args.get("to")
    if not project or not date_from or not date_to:
        return jsonify({"error": "project, from and to are required"}), 400
    return jsonify(store.merges(project, date_from, date_to))


@app.errorhandler(Exception)
def handle_error(err):
    from werkzeug.exceptions import HTTPException
    if isinstance(err, HTTPException):
        return err
    app.logger.exception(err)
    return jsonify({"error": "data source error"}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 3000))
    print(f"mergedash listening on http://localhost:{port} "
          f"(data source: {'PostgreSQL' if USE_DB else 'fake-data.json'})")
    app.run(host="127.0.0.1", port=port)
