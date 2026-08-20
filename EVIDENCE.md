# Evidence

Generated from the reproducible local commands on 2026-08-11; re-verified after adding semantic-alias and guard tests.

| Definition-of-done check | Evidence |
|---|---|
| Structured vision output validated | `test_schema_rejects_invalid_output ... ok` — `ImageTags.validate({{"subject":"fox"}})` raises `ValueError` |
| Low confidence flagged | `test_low_confidence_flagged ... ok`; `uncertain-01` has `status='flagged'` (confidence 0.42 < 0.70) |
| Batch job with retries/progress | `POST /jobs/batch` → `{{"status":"completed","processed":6,"total":6,"retries":0}}`; retries capped at 3 per item |
| Vision and embedding costs tracked | `GET /costs` after a batch → 12 rows, kinds `{{vision, embedding}}`, models `{{local-reference, local-hash}}` (Gemini: `gemini-3.6-flash` + `gemini-embedding-001`) |
| Ranked image suggestions | `test_fox_ranks_first ... ok` — fox post's match is `fox-01` |
| Equivalent semantic concepts | `test_semantic_alias_vulpes ... ok` — ad-hoc post `vulpes-vulpes` (scientific name for red fox) resolves to `fox-01`; aliases `vulpes→fox`, `wolves→wolf`, `canines→dog` |
| Mismatch guard rejects wolf | `test_wolf_is_rejected ... ok` and `test_guard_rejects_wolf_with_reason ... ok`; reason `Animal category mismatch: expected red fox, detected gray wolf` |
| Human-readable rejection/no-match | `test_no_match ... ok`; unmatched post returns message `No confident match found` with per-candidate guard reasons |
| Persistence and review API | SQLite/PostgreSQL schema: images, posts, jobs, costs, reviews, suggestions; `POST /reviews` records `approved`/`rejected` decisions (verified live) |
| Automated tests and eval | `python3 -m unittest discover -s tests -v`: **11 tests passed**; `GET /eval` → `{{"top1_precision": 1.0, "correct": 2, "total": 2}}` |
| PostgreSQL deployment | `docker compose up --build` starts `postgres:16-alpine` + `api`; `migrations/001_init.sql` has all tables, `CHECK` constraints and indexes |
| Gemini cloud path | `providers.py::GeminiProvider` uses `generate_content` with JSON-schema response and `embed_content` with `SEMANTIC_SIMILARITY`; no key committed |
| Ollama free local path | `providers.py::OllamaProvider` calls `/api/generate` and `/api/embed`; models/base URL configurable via `.env` |
| Gemini live smoke test | 2026-08-12: after key rotation a real Gemini job completed `processed:6, retries:0`; cost rows recorded `gemini-3.6-flash` and `gemini-embedding-001`. A later rerun hit the free-tier 20-request quota, so final cloud eval should rerun after quota reset. |
| Boundary validation | FastAPI `GuardRequest`/`ReviewRequest` enforce non-empty IDs and `approved`/`rejected`; invalid bodies produce 422 |
| Idempotency | `POST /jobs/batch` with `Idempotency-Key` returns the existing job on replay; `test_batch_idempotency ... ok` |
| Retry/failure alert | Batch attempts each provider item up to 3 times; persists `failed`, `retries`, `error` before raising |
| Background execution | FastAPI `POST /jobs/batch` queues a job and schedules `run_batch` via `BackgroundTasks` (or runs in-process with the same idempotency key); `GET /jobs/{{job_id}}` exposes progress |
| Startup seeding | FastAPI `_startup` calls `engine.seed()` so `docker compose up` yields a ready API; ad-hoc posts are embedded on-the-fly in `suggestions()` |
| Suggestions persistence | `suggestions` table stores rank, cosine score, accepted flag, reason with `(post_id,image_id)` uniqueness and a `(post_id, rank)` index |
