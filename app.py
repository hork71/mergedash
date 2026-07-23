"""Simple merge request dashboard server (Flask port of server.js).

Serves the same frontend (public/index.html) and the same JSON API.

Data source:
    default    -> fake-data.json (development stub)
    USE_DB=1   -> PostgreSQL, configured via the standard PG* environment
                  variables (PGHOST, PGDATABASE, ...) or DATABASE_URL.
"""

import json
import os
import re
from pathlib import Path

from flask import (
    Flask,
    abort,
    jsonify,
    redirect,
    render_template_string,
    request,
    send_from_directory,
    session,
    url_for,
)

BASE_DIR = Path(__file__).resolve().parent
USE_DB = os.environ.get("USE_DB") == "1"
USE_LDAP = os.environ.get("USE_LDAP") == "1"

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY")
if USE_LDAP and not app.secret_key:
    raise RuntimeError("SECRET_KEY must be set when USE_LDAP=1")


# --- AD authentication (only touched when USE_LDAP=1) ---

REQUIRED_GROUP_MATCH_RULE = "1.2.840.113556.1.4.803"  # AD: LDAP_MATCHING_RULE_IN_CHAIN
PUBLIC_PATHS = {"/login", "/logout"}


def _ldap_server():
    from ldap3 import Server, Tls
    import ssl

    # get_info defaults to NONE: we only bind/search, never read schema, and
    # fetching AD's live schema (get_info=ALL) is a known trigger for
    # ldap3 parsing errors (e.g. "category() argument must be a unicode
    # character, not str") against Active Directory.
    use_ssl = os.environ.get("LDAP_USE_SSL", "1") == "1"
    tls = Tls(validate=ssl.CERT_REQUIRED) if use_ssl else None

    # Strip any ldap(s):// scheme ourselves and pass a bare host[:port].
    raw = os.environ["LDAP_SERVER"].strip()
    raw = re.sub(r"^ldaps?://", "", raw, flags=re.IGNORECASE).rstrip("/")
    host, _, port = raw.partition(":")

    # A hostname is legitimately all-ASCII (letters/digits/hyphen/dot); any
    # other character here is invisible copy-paste noise (BOM, NBSP, smart
    # quotes, etc. from a wiki/Word doc/secrets UI). Python's socket/SSL
    # layer only calls into the IDNA "nameprep" codec when a hostname isn't
    # pure ASCII, and nameprep is where this crashes
    # ("TypeError: category() argument must be a unicode character, not
    # str" from stringprep.in_table_c12) — so stripping non-ASCII noise
    # here avoids that code path entirely rather than chasing the bug
    # inside stringprep itself.
    host = re.sub(r"[^A-Za-z0-9.-]", "", host)
    if not host:
        raise RuntimeError("LDAP_SERVER has no valid hostname characters after sanitizing")

    kwargs = {"use_ssl": use_ssl, "tls": tls}
    if port:
        kwargs["port"] = int(port)
    return Server(host, **kwargs)


def ldap_authenticate(username, password):
    """Verify username/password against AD and required group membership.

    Returns True iff the service account can search AD, exactly one user
    matches, a bind as that user's own DN with `password` succeeds, and
    that user is a member (including nested groups) of at least one of the
    groups listed in LDAP_REQUIRED_GROUP_DNS. Never raises — any failure
    yields False.
    """
    from ldap3 import Connection
    from ldap3.core.exceptions import LDAPException
    from ldap3.utils.conv import escape_filter_chars

    user_attr = os.environ.get("LDAP_USER_ATTR", "sAMAccountName")
    base_dn = os.environ["LDAP_BASE_DN"]
    # ';' (not ',') separates entries: DNs themselves contain commas
    # between RDN components, so commas can't delimit a list of DNs.
    group_dns = [
        g.strip() for g in os.environ["LDAP_REQUIRED_GROUP_DNS"].split(";") if g.strip()
    ]
    if not group_dns:
        return False

    service_conn = None
    user_conn = None
    try:
        service_conn = Connection(
            _ldap_server(),
            user=os.environ["LDAP_BIND_DN"],
            password=os.environ["LDAP_BIND_PASSWORD"],
            auto_bind=True,
        )

        service_conn.search(
            search_base=base_dn,
            search_filter=f"({user_attr}={escape_filter_chars(username)})",
            attributes=["distinguishedName"],
        )
        if len(service_conn.entries) != 1:
            return False
        user_dn = service_conn.entries[0].entry_dn

        user_conn = Connection(_ldap_server(), user=user_dn, password=password)
        if not user_conn.bind():
            return False

        group_clauses = "".join(
            f"(memberOf:{REQUIRED_GROUP_MATCH_RULE}:={escape_filter_chars(g)})"
            for g in group_dns
        )
        service_conn.search(
            search_base=base_dn,
            search_filter=(
                f"(&(distinguishedName={escape_filter_chars(user_dn)})"
                f"(|{group_clauses}))"
            ),
            attributes=["distinguishedName"],
        )
        return len(service_conn.entries) == 1
    except LDAPException:
        app.logger.exception("LDAP authentication error")
        return False
    finally:
        if user_conn is not None:
            user_conn.unbind()
        if service_conn is not None:
            service_conn.unbind()


LOGIN_PAGE = """<!doctype html>
<html>
<head><title>mergedash &mdash; sign in</title>
<style>
  :root { --bg:#f6f7f9; --fg:#1c2430; --muted:#5b6572; --card:#fff; --border:#d9dee5; --accent:#1f6feb; }
  body { margin:0; font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif; background:var(--bg); color:var(--fg);
         display:flex; align-items:center; justify-content:center; min-height:100vh; }
  form { background:var(--card); border:1px solid var(--border); border-radius:8px; padding:2rem; width:300px; }
  h1 { font-size:1.1rem; margin:0 0 1.25rem; }
  label { display:block; font-size:.85rem; color:var(--muted); margin-bottom:.25rem; }
  input { width:100%; padding:.5rem; margin-bottom:1rem; border:1px solid var(--border); border-radius:4px; box-sizing:border-box; }
  button { width:100%; padding:.6rem; background:var(--accent); color:#fff; border:0; border-radius:4px; cursor:pointer; }
  .error { color:#cf222e; font-size:.85rem; margin-bottom:1rem; }
</style></head>
<body>
  <form method="post" action="/login">
    <h1>mergedash</h1>
    {% if error %}<div class="error">{{ error }}</div>{% endif %}
    <label for="u">Username</label>
    <input id="u" name="username" autofocus required>
    <label for="p">Password</label>
    <input id="p" name="password" type="password" required>
    <input type="hidden" name="next" value="{{ next }}">
    <button type="submit">Sign in</button>
  </form>
</body>
</html>"""


@app.before_request
def require_login():
    if not USE_LDAP or request.path in PUBLIC_PATHS:
        return
    if "username" in session:
        return
    if request.path.startswith("/api/"):
        abort(401, description="authentication required")
    return redirect(url_for("login", next=request.path))


@app.route("/login", methods=["GET", "POST"])
def login():
    if not USE_LDAP:
        abort(404)

    if request.method == "GET":
        return render_template_string(LOGIN_PAGE, error=None, next=request.args.get("next", "/"))

    username = request.form.get("username", "")
    password = request.form.get("password", "")
    next_url = request.form.get("next") or "/"
    if not next_url.startswith("/"):
        next_url = "/"

    if not username or not password:
        return render_template_string(
            LOGIN_PAGE, error="Username and password required.", next=next_url
        ), 400

    if ldap_authenticate(username, password):
        session.clear()
        session["username"] = username
        return redirect(next_url)

    return render_template_string(
        LOGIN_PAGE, error="Invalid credentials or insufficient access.", next=next_url
    ), 401


@app.route("/logout", methods=["POST"])
def logout():
    if not USE_LDAP:
        abort(404)
    session.clear()
    return redirect(url_for("login"))


@app.errorhandler(401)
def handle_unauthorized(err):
    return jsonify({"error": str(err.description or "authentication required")}), 401


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
            if (project is None or r["project"] == project)
            and date_from <= r["month"] <= date_to
        ]
        # Chained stable sorts, least significant first, to get mixed
        # directions: month DESC, project ASC, created_at DESC, iid DESC.
        rows.sort(key=lambda r: r["iid"], reverse=True)
        rows.sort(key=lambda r: r["created_at"], reverse=True)
        rows.sort(key=lambda r: r["project"])
        rows.sort(key=lambda r: r["month"], reverse=True)
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
        project_clause = "AND project = %s " if project is not None else ""
        params = (date_from, date_to, project) if project is not None else (date_from, date_to)
        rows = self._query(
            f"""
            SELECT project, month, iid, title, source_branch, target_branch, state, author,
                   to_char(created_at, 'YYYY-MM-DD') AS created_at,
                   to_char(merged_at, 'YYYY-MM-DD')  AS merged_at,
                   merged_by, approved_by, web_url
              FROM gitlabmerges
             WHERE month >= %s AND month <= %s {project_clause}
             ORDER BY month DESC, project ASC, created_at DESC, iid DESC
            """,
            params,
        )
        cols = ("project", "month", "iid", "title", "source_branch", "target_branch",
                "state", "author", "created_at", "merged_at", "merged_by",
                "approved_by", "web_url")
        return [dict(zip(cols, r)) for r in rows]


store = DbStore() if USE_DB else FakeStore()


# --- routes ---

@app.route("/")
def index():
    return send_from_directory(BASE_DIR / "public", "index.html")


@app.route("/api/whoami")
def api_whoami():
    return jsonify({"username": session.get("username")})


@app.route("/api/projects")
def api_projects():
    return jsonify(store.projects())


@app.route("/api/months")
def api_months():
    return jsonify(store.months())


@app.route("/api/merges")
def api_merges():
    project = request.args.get("project") or None
    date_from = request.args.get("from")
    date_to = request.args.get("to")
    if not date_from or not date_to:
        return jsonify({"error": "from and to are required"}), 400
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
