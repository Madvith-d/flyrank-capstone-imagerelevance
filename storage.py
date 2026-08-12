"""Small SQLite/PostgreSQL compatibility layer; business code stays database-agnostic."""
from __future__ import annotations

import os, sqlite3
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
            if statement.strip(): self.execute(statement)

    def commit(self): self.raw.commit()
    def close(self): self.raw.close()


SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS images(id TEXT PRIMARY KEY, subject TEXT, category TEXT, attributes TEXT, caption TEXT, confidence REAL, status TEXT, embedding TEXT, image_path TEXT, source_url TEXT, license TEXT);
CREATE TABLE IF NOT EXISTS posts(id TEXT PRIMARY KEY, title TEXT, body TEXT, subject TEXT, embedding TEXT);
CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, status TEXT, processed INTEGER, total INTEGER, retries INTEGER, error TEXT, idempotency_key TEXT UNIQUE);
CREATE TABLE IF NOT EXISTS costs(id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT, kind TEXT, item_id TEXT, model TEXT, input_tokens INTEGER DEFAULT 0, output_tokens INTEGER DEFAULT 0, cost REAL, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS reviews(id INTEGER PRIMARY KEY AUTOINCREMENT, post_id TEXT, image_id TEXT, decision TEXT, reason TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS suggestions(id INTEGER PRIMARY KEY AUTOINCREMENT, post_id TEXT, image_id TEXT, rank INTEGER, similarity REAL, accepted INTEGER, reason TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP, UNIQUE(post_id, image_id));
CREATE INDEX IF NOT EXISTS images_subject_idx ON images(subject);
CREATE INDEX IF NOT EXISTS costs_job_idx ON costs(job_id);
CREATE INDEX IF NOT EXISTS reviews_pair_idx ON reviews(post_id, image_id);
CREATE INDEX IF NOT EXISTS suggestions_post_idx ON suggestions(post_id, rank);
"""
POSTGRES_SCHEMA = """
CREATE TABLE IF NOT EXISTS images(id TEXT PRIMARY KEY, subject TEXT, category TEXT, attributes TEXT, caption TEXT, confidence DOUBLE PRECISION, status TEXT, embedding TEXT, image_path TEXT, source_url TEXT, license TEXT);
CREATE TABLE IF NOT EXISTS posts(id TEXT PRIMARY KEY, title TEXT, body TEXT, subject TEXT, embedding TEXT);
CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, status TEXT, processed INTEGER, total INTEGER, retries INTEGER, error TEXT, idempotency_key TEXT UNIQUE);
CREATE TABLE IF NOT EXISTS costs(id BIGSERIAL PRIMARY KEY, job_id TEXT, kind TEXT, item_id TEXT, model TEXT, input_tokens INTEGER DEFAULT 0, output_tokens INTEGER DEFAULT 0, cost DOUBLE PRECISION, created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS reviews(id BIGSERIAL PRIMARY KEY, post_id TEXT, image_id TEXT, decision TEXT, reason TEXT, created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS suggestions(id BIGSERIAL PRIMARY KEY, post_id TEXT, image_id TEXT, rank INTEGER, similarity DOUBLE PRECISION, accepted INTEGER, reason TEXT, created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP, UNIQUE(post_id, image_id));
CREATE INDEX IF NOT EXISTS images_subject_idx ON images(subject);
CREATE INDEX IF NOT EXISTS costs_job_idx ON costs(job_id);
CREATE INDEX IF NOT EXISTS reviews_pair_idx ON reviews(post_id, image_id);
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
    db = Database(raw)
    db.executescript(SQLITE_SCHEMA.split(";"))
    # Upgrade databases created by the original demo without destructive resets.
    for statement in ("ALTER TABLE images ADD COLUMN image_path TEXT", "ALTER TABLE images ADD COLUMN source_url TEXT", "ALTER TABLE images ADD COLUMN license TEXT", "ALTER TABLE jobs ADD COLUMN idempotency_key TEXT", "ALTER TABLE costs ADD COLUMN model TEXT", "ALTER TABLE costs ADD COLUMN input_tokens INTEGER DEFAULT 0", "ALTER TABLE costs ADD COLUMN output_tokens INTEGER DEFAULT 0"):
        try: db.execute(statement)
        except sqlite3.OperationalError: pass
    db.commit()
    return db
