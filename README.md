# AI Image Understanding & Content Matching Engine

An offline-first backend service that understands an image corpus, validates structured vision metadata, embeds image descriptions and article text, ranks semantic candidates, and refuses unsafe matches. The reliability contract is simple: **good suggestions when confident, safe rejection when uncertain**.

## What is implemented

The service contains five layers. A batch worker classifies every corpus record through a provider adapter, validates the exact `ImageTags` schema, flags low-confidence results, generates embeddings, records per-call costs, and exposes progress and failure state. The matching engine ranks image vectors against post vectors with cosine similarity. The mismatch guard rejects flagged images, subject mismatches, and candidates below the configured similarity threshold, returning a human-readable reason. The review API records approved or rejected pairings and preserves the reason shown to the reviewer.

The default provider is a deterministic local reference provider, so the evaluator can reproduce the complete behavior without credentials. Optional Gemini and Ollama adapters use the same validated provider contract.

## Architecture

```text
Images ──► POST /jobs/batch ──► async worker + retries ──► provider adapter
  │                                                     ├─ local reference
  │                                                     ├─ Gemini structured JSON
  │                                                     └─ Ollama JSON
  │                                                               │
  │                                     ImageTags.validate() ◄─────┘
  │                                              │
  │                         image_tags + image_embeddings + costs
  │                                              │
Posts ───────────────────────────────────► post_embeddings
                                                │
GET /posts/{id}/images ─► cosine ranking ─► mismatch guard
                                                ├─ accepted suggestion + explanation
                                                └─ No confident match found + reasons
                                                             │
                                           POST /reviews ─► review trail
```

See [DESIGN.md](DESIGN.md) for the one-page design, data model, API surface, guard rules, and explicit non-goal.

## Run locally with no credentials

```bash
cp .env.example .env
python3 -m pip install -r requirements.txt
VISION_PROVIDER=local python3 app.py seed
VISION_PROVIDER=local python3 app.py batch
VISION_PROVIDER=local python3 app.py eval
VISION_PROVIDER=local uvicorn api:app --host 127.0.0.1 --port 8000
```

The SQLite fallback is created at `data/capstone.sqlite3`, which is ignored by Git. For the HTTP demo, the API is available at `http://127.0.0.1:8000`.

## Run with Docker and PostgreSQL

The one-command evaluator path is:

```bash
cp .env.example .env
docker compose up --build -d
curl http://127.0.0.1:8000/health
curl -X POST http://127.0.0.1:8000/jobs/batch -H 'Idempotency-Key: demo-batch'
curl http://127.0.0.1:8000/jobs/<job_id>
curl http://127.0.0.1:8000/posts/fox-post/images
```

`POST /jobs/batch` returns `202 Accepted` with a queued or running job. The worker is scheduled through FastAPI background tasks, so slow vision and embedding calls do not block the request. Use the returned job ID with `GET /jobs/{job_id}` to inspect `queued`, `running`, `completed`, or `failed` status, processed count, retries, and error details.

## Acceptance probes

After the batch completes, the following probes demonstrate the required behavior:

```bash
# Ranked suggestions: fox is the accepted top result.
curl http://127.0.0.1:8000/posts/fox-post/images

# Force the wolf against the fox article: the guard rejects it with a category reason.
curl -X POST http://127.0.0.1:8000/guard \
  -H 'Content-Type: application/json' \
  -d '{"post_id":"fox-post","image_id":"wolf-01"}'

# No suitable image: returns the no-match message and per-candidate reasons.
curl http://127.0.0.1:8000/posts/unmatched-post/images

# Human review trail: both decisions are validated and persisted.
curl -X POST http://127.0.0.1:8000/reviews \
  -H 'Content-Type: application/json' \
  -d '{"post_id":"fox-post","image_id":"fox-01","decision":"approved"}'
curl -X POST http://127.0.0.1:8000/reviews \
  -H 'Content-Type: application/json' \
  -d '{"post_id":"fox-post","image_id":"wolf-01","decision":"rejected"}'
curl http://127.0.0.1:8000/reviews

# Cost attribution and evaluation.
curl http://127.0.0.1:8000/costs
curl http://127.0.0.1:8000/eval
```

The committed evaluation set is `data/eval.json`. Its current result is **top-1 precision 1.0 (3/3)** for the red fox, gray wolf, and domestic dog labels. The unmatched article is a safety probe rather than a positive precision label.

## Providers and free-tier operation

Set `VISION_PROVIDER=local` for the deterministic offline path. Set `VISION_PROVIDER=gemini` with `GEMINI_API_KEY` for Gemini structured vision and semantic embeddings, or set `VISION_PROVIDER=ollama` with the Ollama URL and model names for a fully local model path. All API keys are environment-only; `.env` is ignored and `.env.example` contains placeholders. `MAX_AI_COST_USD` is a hard batch budget, while `LOW_CONFIDENCE_THRESHOLD` and `MATCH_SIMILARITY_THRESHOLD` control the guard.

## Corpus and licensing

The checked-in `data/corpus.json` is a small six-record acceptance corpus covering red fox, gray wolf, dog, bear, deer, and one deliberately uncertain record. Images are not committed; `scripts/download_corpus.py` downloads the Wikimedia Commons sources recorded in the manifest, preserves source URLs and license notes, and copies the uncertain fixture from the fox source. The small corpus keeps the demo free and deterministic; a production corpus should expand toward the brief's approximately 50 images and independently review every source license.

## Tests and submission pack

Run the deterministic suite with:

```bash
VISION_PROVIDER=local python3 -m unittest discover -s tests -v
```

The suite covers exact schema rejection, invalid confidence types, normalized tag/vector persistence, low-confidence flagging, ranking, semantic aliasing (`vulpes` → fox), mismatch rejection, no-match explanations, top-1 evaluation, idempotency, atomic background-job claiming, retry failure persistence, cost attribution, and FastAPI boundary validation.

The repository includes the required `README.md`, `capstone.yaml`, `EVIDENCE.md`, `BUILDLOG.md`, and `.env.example`, plus `DESIGN.md`, the migration, and the reproducible evaluation dataset.

## Limitations

The default local provider is a deterministic reference implementation, not a general-purpose vision model. The six-record corpus is intentionally smaller than a production library, and vectors are stored as JSON because the capstone scale does not require ANN infrastructure. The optional API key is a deployment guard, not a complete user identity or multi-tenant authorization system. These trade-offs are explicit non-goals rather than hidden behavior.
