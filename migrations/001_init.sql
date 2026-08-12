-- PostgreSQL schema used by docker-compose. The application also applies this idempotently at startup.
CREATE TABLE IF NOT EXISTS images(id TEXT PRIMARY KEY, subject TEXT NOT NULL, category TEXT NOT NULL, attributes TEXT NOT NULL, caption TEXT NOT NULL, confidence DOUBLE PRECISION NOT NULL, status TEXT NOT NULL, embedding TEXT, image_path TEXT, source_url TEXT, license TEXT);
CREATE TABLE IF NOT EXISTS posts(id TEXT PRIMARY KEY, title TEXT NOT NULL, body TEXT NOT NULL, subject TEXT NOT NULL, embedding TEXT);
CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, status TEXT NOT NULL, processed INTEGER NOT NULL, total INTEGER NOT NULL, retries INTEGER NOT NULL, error TEXT, idempotency_key TEXT UNIQUE);
CREATE TABLE IF NOT EXISTS costs(id BIGSERIAL PRIMARY KEY, job_id TEXT NOT NULL, kind TEXT NOT NULL, item_id TEXT NOT NULL, model TEXT NOT NULL, input_tokens INTEGER DEFAULT 0, output_tokens INTEGER DEFAULT 0, cost DOUBLE PRECISION NOT NULL, created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS reviews(id BIGSERIAL PRIMARY KEY, post_id TEXT NOT NULL, image_id TEXT NOT NULL, decision TEXT NOT NULL CHECK(decision IN ('approved','rejected')), reason TEXT, created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS suggestions(id BIGSERIAL PRIMARY KEY, post_id TEXT NOT NULL, image_id TEXT NOT NULL, rank INTEGER NOT NULL, similarity DOUBLE PRECISION NOT NULL, accepted INTEGER NOT NULL, reason TEXT NOT NULL, created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP, UNIQUE(post_id, image_id));
CREATE INDEX IF NOT EXISTS images_subject_idx ON images(subject);
CREATE INDEX IF NOT EXISTS costs_job_idx ON costs(job_id);
CREATE INDEX IF NOT EXISTS reviews_pair_idx ON reviews(post_id, image_id);
CREATE INDEX IF NOT EXISTS suggestions_post_idx ON suggestions(post_id, rank);
