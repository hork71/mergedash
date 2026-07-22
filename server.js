// Simple merge request dashboard server.
// Uses only Node built-ins + the 'pg' PostgreSQL driver.
//
// Data source:
//   default    -> fake-data.json (development stub)
//   USE_DB=1   -> PostgreSQL, configured via the standard PG* environment
//                 variables (PGHOST, PGDATABASE, ...) or DATABASE_URL.

const http = require('http');
const fs = require('fs');
const path = require('path');

const PORT = process.env.PORT || 3000;
const USE_DB = process.env.USE_DB === '1';

// --- data layer: both backends expose projects(), months(), merges() ---

function fakeStore() {
  const rows = JSON.parse(
    fs.readFileSync(path.join(__dirname, 'fake-data.json'), 'utf8')
  );
  const distinct = (key) => [...new Set(rows.map((r) => r[key]))].sort();
  return {
    projects: async () => distinct('project'),
    months: async () => distinct('month'),
    merges: async (project, from, to) =>
      rows
        .filter((r) => r.project === project && r.month >= from && r.month <= to)
        .sort(
          (a, b) =>
            b.month.localeCompare(a.month) ||
            b.created_at.localeCompare(a.created_at) ||
            b.iid - a.iid
        ),
  };
}

function dbStore() {
  const { Pool } = require('pg');
  const pool = new Pool(
    process.env.DATABASE_URL ? { connectionString: process.env.DATABASE_URL } : {}
  );
  return {
    projects: async () =>
      (await pool.query('SELECT DISTINCT project FROM gitlabmerges ORDER BY project'))
        .rows.map((r) => r.project),
    months: async () =>
      (await pool.query('SELECT DISTINCT month FROM gitlabmerges ORDER BY month'))
        .rows.map((r) => r.month),
    merges: async (project, from, to) =>
      (await pool.query(
        `SELECT month, iid, title, source_branch, target_branch, state, author,
                to_char(created_at, 'YYYY-MM-DD') AS created_at,
                to_char(merged_at, 'YYYY-MM-DD')  AS merged_at,
                merged_by, approved_by, web_url
           FROM gitlabmerges
          WHERE project = $1 AND month >= $2 AND month <= $3
          ORDER BY month DESC, created_at DESC, iid DESC`,
        [project, from, to]
      )).rows,
  };
}

const store = USE_DB ? dbStore() : fakeStore();

// --- http server ---

function sendJson(res, status, data) {
  const body = JSON.stringify(data);
  res.writeHead(status, {
    'Content-Type': 'application/json; charset=utf-8',
    'Content-Length': Buffer.byteLength(body),
  });
  res.end(body);
}

async function handleApi(req, res, url) {
  try {
    if (url.pathname === '/api/whoami') {
      // No authentication in this backend — always reports logged-out so
      // the shared frontend's sign-out button stays hidden.
      return sendJson(res, 200, { username: null });
    }
    if (url.pathname === '/api/projects') {
      return sendJson(res, 200, await store.projects());
    }
    if (url.pathname === '/api/months') {
      return sendJson(res, 200, await store.months());
    }
    if (url.pathname === '/api/merges') {
      const project = url.searchParams.get('project');
      const from = url.searchParams.get('from');
      const to = url.searchParams.get('to');
      if (!project || !from || !to) {
        return sendJson(res, 400, { error: 'project, from and to are required' });
      }
      return sendJson(res, 200, await store.merges(project, from, to));
    }
    sendJson(res, 404, { error: 'not found' });
  } catch (err) {
    console.error(err);
    sendJson(res, 500, { error: 'data source error' });
  }
}

const server = http.createServer((req, res) => {
  const url = new URL(req.url, `http://${req.headers.host}`);

  if (url.pathname.startsWith('/api/')) {
    return handleApi(req, res, url);
  }

  if (url.pathname === '/' || url.pathname === '/index.html') {
    const file = path.join(__dirname, 'public', 'index.html');
    return fs.readFile(file, (err, data) => {
      if (err) {
        res.writeHead(500);
        return res.end('cannot read index.html');
      }
      res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
      res.end(data);
    });
  }

  res.writeHead(404);
  res.end('not found');
});

server.listen(PORT, () => {
  console.log(
    `mergedash listening on http://localhost:${PORT} ` +
    `(data source: ${USE_DB ? 'PostgreSQL' : 'fake-data.json'})`
  );
});
