 CREATE TABLE IF NOT EXISTS gitlabmerges (
     project      TEXT NOT NULL,
     month        TEXT NOT NULL,
     iid          INTEGER NOT NULL,
     title        TEXT,
     state        TEXT,
     author       TEXT,
     created_at   DATE,
     merged_at    DATE,
     merged_by    TEXT,
     approved_by  TEXT,
     web_url      TEXT,
     synced_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
     PRIMARY KEY (project, iid)
 );

