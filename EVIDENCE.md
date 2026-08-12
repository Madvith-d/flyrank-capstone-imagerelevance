# Evidence

Generated from the reproducible local commands on 2026-08-11.

| Definition-of-done check | Evidence |
|---|---|
| Structured vision output validated | `test_schema_rejects_invalid_output ... ok` |
| Low confidence flagged | `test_low_confidence_flagged ... ok`; `uncertain-01` is `flagged` |
| Batch job with retries/progress | `python3 app.py batch` returns `status: completed`, `processed: 6`, `total: 6`, `retries: 0` |
| Vision and embedding costs tracked | `GET /costs` returns one `vision` and one `embedding` entry per seeded image, each cost `0.0` |
| Ranked image suggestions | `test_fox_ranks_first ... ok` |
| Equivalent semantic concepts | Deterministic normalized embeddings rank captions and post concepts consistently; eval is 100% |
| Mismatch guard rejects wolf | `test_wolf_is_rejected ... ok`; reason contains `Animal category mismatch` |
| Human-readable rejection/no-match | `test_no_match ... ok`; API returns `No confident match found` or an explicit guard reason |
| Persistence and review API | SQLite schema includes images, posts, jobs, costs, reviews; `POST /reviews` records decisions |
| Automated tests and eval | `python3 -m unittest discover -s tests -v`: 9 tests passed; `python3 app.py eval`: `top1_precision: 1.0` |
| PostgreSQL deployment | `docker compose up --build` starts `postgres:16-alpine` and `api`; `migrations/001_init.sql` contains tables and indexes |
| Gemini cloud path | `providers.py::GeminiProvider` uses `generate_content` with JSON schema validation and `embed_content` with `SEMANTIC_SIMILARITY`; no key is committed |
| Ollama free local path | `providers.py::OllamaProvider` calls `/api/generate` and `/api/embed`; models and base URL are configurable in `.env` |
| Gemini live smoke test | 2026-08-12: after key rotation, a real Gemini job completed `processed: 6`, `retries: 0`; cost rows used `gemini-3.6-flash` and `gemini-embedding-001`. A later rerun hit the free-tier quota of 20 requests, so final cloud eval should be rerun after quota reset. |
| Boundary validation | FastAPI `GuardRequest`/`ReviewRequest` enforce non-empty IDs and approved/rejected decisions; invalid requests produce 422 |
| Idempotency | `POST /jobs/batch` accepts `Idempotency-Key` and returns the existing job on replay |
| Retry/failure alert | Batch attempts each provider item up to 3 times and persists `failed`, `retries`, and `error` before surfacing the failure |
| Background execution | FastAPI `POST /jobs/batch` creates a queued job and schedules `run_batch` through `BackgroundTasks`; `GET /jobs/{job_id}` exposes progress |
| Suggestions persistence | `suggestions` table stores rank, cosine score, accepted flag, reason, and has `(post_id,image_id)` uniqueness plus a post/rank index |
