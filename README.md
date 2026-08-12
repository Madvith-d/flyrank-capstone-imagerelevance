# AI Image Understanding & Content Matching Engine

An end-to-end service that tags an image corpus, embeds image captions and article text, ranks candidates, and rejects unsafe matches. It runs offline for deterministic tests and supports PostgreSQL, Gemini, or Ollama in deployment.

## Run

### Docker + PostgreSQL

```bash
cp .env.example .env
docker compose up --build -d
docker compose exec api python3 app.py seed
docker compose exec api python3 app.py batch
docker compose exec api python3 app.py eval
```

The API is at `http://127.0.0.1:8000`. PostgreSQL uses the named volume `postgres_data`; migrations are also checked into `migrations/001_init.sql` and applied idempotently at startup.

### Local, no credentials

```bash
python3 app.py seed
python3 app.py batch
python3 app.py eval
python3 app.py serve
```

### Gemini cloud mode

Set `VISION_PROVIDER=gemini`, `GEMINI_API_KEY`, and optionally `GEMINI_VISION_MODEL` / `GEMINI_EMBEDDING_MODEL` in `.env`, download the licensed demo images, then run the batch:

```bash
python3 scripts/download_corpus.py
docker compose up --build -d
docker compose exec api python3 app.py seed
docker compose exec api python3 app.py batch
```

Gemini structured output is validated by `ImageTags.validate()` after the SDK response. The adapter uses `gemini-3.6-flash` for vision and `gemini-embedding-001` with `SEMANTIC_SIMILARITY` for embeddings by default. The current `0.25` similarity threshold is tuned against the labeled fox/wolf eval set.

### Ollama local model mode

Run Ollama separately, pull a vision model and an embedding model, then set `VISION_PROVIDER=ollama`, `OLLAMA_BASE_URL`, `OLLAMA_VISION_MODEL`, and `OLLAMA_EMBEDDING_MODEL`. The same batch and guard paths are used.

Then query `GET http://127.0.0.1:8000/posts/fox-post/images`. Force the wolf with `POST /guard` and body `{"post_id":"fox-post","image_id":"wolf-01"}`. Reviews use `POST /reviews` with `post_id`, `image_id`, and `decision` (`approved` or `rejected`). Batch jobs accept an `Idempotency-Key` header.

## Architecture

```text
images -> background batch + retry -> Gemini/Ollama/local vision -> validated tags -> embeddings -> PostgreSQL
posts  -----------------------------------------------------------> embeddings -> indexed candidate ranking
                                                               -> mismatch guard -> review API
```

## Quality

`python3 -m unittest discover -s tests -v` covers schema rejection, low-confidence flagging, idempotent batch execution, fox ranking, wolf rejection, no-match behavior, and eval precision. The seeded labeled set has top-1 precision 1.0 (100%). Docker validation forces `VISION_PROVIDER=local` so tests never spend cloud quota; normal batch runs use the provider selected in `.env`.

## Limitations

The local provider is deterministic reference data and hashed vectors, so it runs without API keys. For production, download licensed image files and select Gemini or Ollama. At larger scale, replace the text vector column with pgvector/ANN search; the current corpus is intentionally small and uses an indexed PostgreSQL schema plus cosine ranking in application code.

## Security and operations

Secrets are read only from environment variables and are excluded by `.gitignore`. Pydantic rejects malformed API bodies with 422 responses, review decisions are constrained to `approved`/`rejected`, invalid model JSON is rejected, low-confidence results are flagged, batch calls retry three times, and `MAX_AI_COST_USD` stops a cloud batch before it exceeds its budget.
