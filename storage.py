"""Small SQLite/PostgreSQL compatibility layer; business logic stays database-agnostic."""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path


class Row(dict):
    def __getitem__(self, key):
        return list(self.values())[key] if isinstance(key, int) else super().__getitem__(key)


class Result(list):
    def fetchone(self):
        return self[0] if self else None


class Database:
    def __init__(self, raw, postgres=False):
        self.raw, self.postgres = raw, postgres

    def execute(self, sql, params=()):
        if self.postgres:
            sql = sql.replace("?", "%s")
            with self.raw.cursor() as cur:
                cur.execute(sql, params)
                if cur.description:
                    names = [x.name for x in cur.description]
                    return Result(Row(zip(names, row)) for row in cur.fetchall())
            return Result()
        cur = self.raw.execute(sql, params)
        if cur.description:
            return Result(Row(dict(row)) for row in cur.fetchall())
        return Result()

    def executescript(self, statements):
        for statement in statements:
            if statement.strip():
                self.execute(statement)

    def commit(self):
        self.raw.commit()

    def close(self):
        self.raw.close()


SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS images(
  id TEXT PRIMARY KEY,
  subject TEXT NOT NULL,
  category TEXT NOT NULL CHECK(category <> ''),
  attributes TEXT NOT NULL,
  caption TEXT NOT NULL,
  confidence REAL NOT NULL CHECK(confidence >= 0 AND confidence <= 1),
  status TEXT NOT NULL CHECK(status IN ('accepted','flagged')),
  embedding TEXT,
  image_path TEXT,
  source_url TEXT,
  license TEXT
);
CREATE TABLE IF NOT EXISTS image_tags(
  image_id TEXT PRIMARY KEY,
  subject TEXT NOT NULL,
  category TEXT NOT NULL,
  attributes TEXT NOT NULL,
  caption TEXT NOT NULL,
  confidence REAL NOT NULL CHECK(confidence >= 0 AND confidence <= 1),
  status TEXT NOT NULL CHECK(status IN ('accepted','flagged')),
  FOREIGN KEY(image_id) REFERENCES images(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS posts(
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  body TEXT NOT NULL,
  subject TEXT NOT NULL,
  embedding TEXT
);
CREATE TABLE IF NOT EXISTS image_embeddings(
  image_id TEXT PRIMARY KEY,
  vector TEXT NOT NULL,
  model TEXT NOT NULL,
  dimension INTEGER NOT NULL CHECK(dimension > 0),
  FOREIGN KEY(image_id) REFERENCES images(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS post_embeddings(
  post_id TEXT PRIMARY KEY,
  vector TEXT NOT NULL,
  model TEXT NOT NULL,
  dimension INTEGER NOT NULL CHECK(dimension > 0),
  FOREIGN KEY(post_id) REFERENCES posts(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS jobs(
  id TEXT PRIMARY KEY,
  status TEXT NOT NULL CHECK(status IN ('queued','running','completed','failed')),
  processed INTEGER NOT NULL DEFAULT 0 CHECK(processed >= 0),
  total INTEGER NOT NULL CHECK(total >= 0),
  retries INTEGER NOT NULL DEFAULT 0 CHECK(retries >= 0),
  error TEXT,
  idempotency_key TEXT UNIQUE,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS costs(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id TEXT NOT NULL,
  kind TEXT NOT NULL CHECK(kind IN ('vision','embedding')),
  item_id TEXT NOT NULL,
  model TEXT NOT NULL,
  input_tokens INTEGER DEFAULT 0,
  output_tokens INTEGER DEFAULT 0,
  cost REAL NOT NULL CHECK(cost >= 0),
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS reviews(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  post_id TEXT NOT NULL,
  image_id TEXT NOT NULL,
  decision TEXT NOT NULL CHECK(decision IN ('approved','rejected')),
  reason TEXT NOT NULL DEFAULT '',
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY(post_id) REFERENCES posts(id),
  FOREIGN KEY(image_id) REFERENCES images(id)
);
CREATE TABLE IF NOT EXISTS suggestions(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  post_id TEXT NOT NULL,
  image_id TEXT NOT NULL,
  rank INTEGER NOT NULL CHECK(rank > 0),
  similarity REAL NOT NULL,
  accepted INTEGER NOT NULL CHECK(accepted IN (0,1)),
  reason TEXT NOT NULL,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(post_id, image_id),
  FOREIGN KEY(post_id) REFERENCES posts(id),
  FOREIGN KEY(image_id) REFERENCES images(id)
);
CREATE INDEX IF NOT EXISTS images_subject_idx ON images(subject);
CREATE INDEX IF NOT EXISTS image_tags_subject_idx ON image_tags(subject);
CREATE INDEX IF NOT EXISTS image_embeddings_model_idx ON image_embeddings(model);
CREATE INDEX IF NOT EXISTS post_embeddings_model_idx ON post_embeddings(model);
CREATE INDEX IF NOT EXISTS jobs_status_idx ON jobs(status, created_at);
CREATE INDEX IF NOT EXISTS costs_job_idx ON costs(job_id, kind);
CREATE INDEX IF NOT EXISTS reviews_pair_idx ON reviews(post_id, image_id, created_at);
CREATE INDEX IF NOT EXISTS suggestions_post_idx ON suggestions(post_id, rank);
"""

POSTGRES_SCHEMA = """
CREATE TABLE IF NOT EXISTS images(
  id TEXT PRIMARY KEY,
  subject TEXT NOT NULL,
  category TEXT NOT NULL CHECK(category <> ''),
  attributes TEXT NOT NULL,
  caption TEXT NOT NULL,
  confidence DOUBLE PRECISION NOT NULL CHECK(confidence >= 0 AND confidence <= 1),
  status TEXT NOT NULL CHECK(status IN ('accepted','flagged')),
  embedding TEXT,
  image_path TEXT,
  source_url TEXT,
  license TEXT
);
CREATE TABLE IF NOT EXISTS image_tags(
  image_id TEXT PRIMARY KEY REFERENCES images(id) ON DELETE CASCADE,
  subject TEXT NOT NULL,
  category TEXT NOT NULL,
  attributes TEXT NOT NULL,
  caption TEXT NOT NULL,
  confidence DOUBLE PRECISION NOT NULL CHECK(confidence >= 0 AND confidence <= 1),
  status TEXT NOT NULL CHECK(status IN ('accepted','flagged'))
);
CREATE TABLE IF NOT EXISTS posts(
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  body TEXT NOT NULL,
  subject TEXT NOT NULL,
  embedding TEXT
);
CREATE TABLE IF NOT EXISTS image_embeddings(
  image_id TEXT PRIMARY KEY REFERENCES images(id) ON DELETE CASCADE,
  vector TEXT NOT NULL,
  model TEXT NOT NULL,
  dimension INTEGER NOT NULL CHECK(dimension > 0)
);
CREATE TABLE IF NOT EXISTS post_embeddings(
  post_id TEXT PRIMARY KEY REFERENCES posts(id) ON DELETE CASCADE,
  vector TEXT NOT NULL,
  model TEXT NOT NULL,
  dimension INTEGER NOT NULL CHECK(dimension > 0)
);
CREATE TABLE IF NOT EXISTS jobs(
  id TEXT PRIMARY KEY,
  status TEXT NOT NULL CHECK(status IN ('queued','running','completed','failed')),
  processed INTEGER NOT NULL DEFAULT 0 CHECK(processed >= 0),
  total INTEGER NOT NULL CHECK(total >= 0),
  retries INTEGER NOT NULL DEFAULT 0 CHECK(retries >= 0),
  error TEXT,
  idempotency_key TEXT UNIQUE,
  created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS costs(
  id BIGSERIAL PRIMARY KEY,
  job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
  kind TEXT NOT NULL CHECK(kind IN ('vision','embedding')),
  item_id TEXT NOT NULL,
  model TEXT NOT NULL,
  input_tokens INTEGER DEFAULT 0,
  output_tokens INTEGER DEFAULT 0,
  cost DOUBLE PRECISION NOT NULL CHECK(cost >= 0),
  created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS reviews(
  id BIGSERIAL PRIMARY KEY,
  post_id TEXT NOT NULL REFERENCES posts(id),
  image_id TEXT NOT NULL REFERENCES images(id),
  decision TEXT NOT NULL CHECK(decision IN ('approved','rejected')),
  reason TEXT NOT NULL DEFAULT '',
  created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS suggestions(
  id BIGSERIAL PRIMARY KEY,
  post_id TEXT NOT NULL REFERENCES posts(id),
  image_id TEXT NOT NULL REFERENCES images(id),
  rank INTEGER NOT NULL CHECK(rank > 0),
  similarity DOUBLE PRECISION NOT NULL,
  accepted BOOLEAN NOT NULL,
  reason TEXT NOT NULL,
  created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(post_id, image_id)
);
CREATE INDEX IF NOT EXISTS images_subject_idx ON images(subject);
CREATE INDEX IF NOT EXISTS image_tags_subject_idx ON image_tags(subject);
CREATE INDEX IF NOT EXISTS image_embeddings_model_idx ON image_embeddings(model);
CREATE INDEX IF NOT EXISTS post_embeddings_model_idx ON post_embeddings(model);
CREATE INDEX IF NOT EXISTS jobs_status_idx ON jobs(status, created_at);
CREATE INDEX IF NOT EXISTS costs_job_idx ON costs(job_id, kind);
CREATE INDEX IF NOT EXISTS reviews_pair_idx ON reviews(post_id, image_id, created_at);
CREATE INDEX IF NOT EXISTS suggestions_post_idx ON suggestions(post_id, rank);
"""


def connect() -> Database:
    url = os.getenv("DATABASE_URL", "").strip()
    if url.startswith(("postgres://", "postgresql://")):
        try:
            import psycopg
        except ImportError as exc:
            raise RuntimeError("PostgreSQL requires psycopg[binary]; run pip install -r requirements.txt") from exc
        db = Database(psycopg.connect(url), postgres=True)
        db.executescript(POSTGRES_SCHEMA.split(";"))
        db.commit()
        return db

    path = os.getenv("SQLITE_PATH", "data/capstone.sqlite3")
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    raw = sqlite3.connect(path)
    raw.row_factory = sqlite3.Row
    raw.execute("PRAGMA foreign_keys = ON")
    db = Database(raw)
    db.executescript(SQLITE_SCHEMA.split(";"))
    # Add columns introduced after the first public demo without destroying local data.
    for statement in (
        "ALTER TABLE images ADD COLUMN image_path TEXT",
        "ALTER TABLE images ADD COLUMN source_url TEXT",
        "ALTER TABLE images ADD COLUMN license TEXT",
        "ALTER TABLE jobs ADD COLUMN idempotency_key TEXT",
        "ALTER TABLE jobs ADD COLUMN created_at TEXT DEFAULT CURRENT_TIMESTAMP",
        "ALTER TABLE jobs ADD COLUMN updated_at TEXT DEFAULT CURRENT_TIMESTAMP",
        "ALTER TABLE costs ADD COLUMN model TEXT",
        "ALTER TABLE costs ADD COLUMN input_tokens INTEGER DEFAULT 0",
        "ALTER TABLE costs ADD COLUMN output_tokens INTEGER DEFAULT 0",
    ):
        try:
            db.execute(statement)
        except sqlite3.OperationalError:
            pass
    db.commit()
    return db
