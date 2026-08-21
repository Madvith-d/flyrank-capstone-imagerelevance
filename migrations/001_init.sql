-- AI Image Understanding & Content Matching Engine schema (PostgreSQL 16)
CREATE TABLE IF NOT EXISTS images (
  id TEXT PRIMARY KEY,
  subject TEXT NOT NULL,
  category TEXT NOT NULL CHECK (category <> ''),
  attributes TEXT NOT NULL,
  caption TEXT NOT NULL,
  confidence DOUBLE PRECISION NOT NULL CHECK (confidence BETWEEN 0 AND 1),
  status TEXT NOT NULL CHECK (status IN ('accepted', 'flagged')),
  embedding TEXT,
  image_path TEXT,
  source_url TEXT,
  license TEXT
);

CREATE TABLE IF NOT EXISTS image_tags (
  image_id TEXT PRIMARY KEY REFERENCES images(id) ON DELETE CASCADE,
  subject TEXT NOT NULL,
  category TEXT NOT NULL,
  attributes TEXT NOT NULL,
  caption TEXT NOT NULL,
  confidence DOUBLE PRECISION NOT NULL CHECK (confidence BETWEEN 0 AND 1),
  status TEXT NOT NULL CHECK (status IN ('accepted', 'flagged'))
);

CREATE TABLE IF NOT EXISTS posts (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  body TEXT NOT NULL,
  subject TEXT NOT NULL,
  embedding TEXT
);

CREATE TABLE IF NOT EXISTS image_embeddings (
  image_id TEXT PRIMARY KEY REFERENCES images(id) ON DELETE CASCADE,
  vector TEXT NOT NULL,
  model TEXT NOT NULL,
  dimension INTEGER NOT NULL CHECK (dimension > 0)
);

CREATE TABLE IF NOT EXISTS post_embeddings (
  post_id TEXT PRIMARY KEY REFERENCES posts(id) ON DELETE CASCADE,
  vector TEXT NOT NULL,
  model TEXT NOT NULL,
  dimension INTEGER NOT NULL CHECK (dimension > 0)
);

CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY,
  status TEXT NOT NULL CHECK (status IN ('queued', 'running', 'completed', 'failed')),
  processed INTEGER NOT NULL DEFAULT 0 CHECK (processed >= 0),
  total INTEGER NOT NULL CHECK (total >= 0),
  retries INTEGER NOT NULL DEFAULT 0 CHECK (retries >= 0),
  error TEXT,
  idempotency_key TEXT UNIQUE,
  created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS costs (
  id BIGSERIAL PRIMARY KEY,
  job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
  kind TEXT NOT NULL CHECK (kind IN ('vision', 'embedding')),
  item_id TEXT NOT NULL,
  model TEXT NOT NULL,
  input_tokens INTEGER DEFAULT 0,
  output_tokens INTEGER DEFAULT 0,
  cost DOUBLE PRECISION NOT NULL CHECK (cost >= 0),
  created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS reviews (
  id BIGSERIAL PRIMARY KEY,
  post_id TEXT NOT NULL REFERENCES posts(id),
  image_id TEXT NOT NULL REFERENCES images(id),
  decision TEXT NOT NULL CHECK (decision IN ('approved', 'rejected')),
  reason TEXT NOT NULL DEFAULT '',
  created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS suggestions (
  id BIGSERIAL PRIMARY KEY,
  post_id TEXT NOT NULL REFERENCES posts(id),
  image_id TEXT NOT NULL REFERENCES images(id),
  rank INTEGER NOT NULL CHECK (rank > 0),
  similarity DOUBLE PRECISION NOT NULL,
  accepted BOOLEAN NOT NULL,
  reason TEXT NOT NULL,
  created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
  UNIQUE (post_id, image_id)
);

CREATE INDEX IF NOT EXISTS images_subject_idx ON images(subject);
CREATE INDEX IF NOT EXISTS image_tags_subject_idx ON image_tags(subject);
CREATE INDEX IF NOT EXISTS image_embeddings_model_idx ON image_embeddings(model);
CREATE INDEX IF NOT EXISTS post_embeddings_model_idx ON post_embeddings(model);
CREATE INDEX IF NOT EXISTS jobs_status_idx ON jobs(status, created_at);
CREATE INDEX IF NOT EXISTS costs_job_idx ON costs(job_id, kind);
CREATE INDEX IF NOT EXISTS reviews_pair_idx ON reviews(post_id, image_id, created_at);
CREATE INDEX IF NOT EXISTS suggestions_post_idx ON suggestions(post_id, rank);
