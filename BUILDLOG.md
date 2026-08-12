# Build log

2026-08-11

- AI helped inspect the capstone brief and scaffold the smallest runnable implementation.
- The repository had no existing code, dependencies, corpus, or test runner, so the implementation uses Python stdlib, SQLite, and deterministic seeded metadata.
- The brief expects a real vision provider, but adding a network dependency would make the evaluator unable to reproduce the run offline. I used a local deterministic substitute and documented the limitation in `README.md`.
- I added tests for the risky paths: malformed structured output, low confidence, wrong-animal rejection, no match, ranking, and precision.
- Added a PostgreSQL-compatible storage layer, Docker Compose, a checked-in SQL migration, FastAPI validation transport, Gemini structured-output/embedding adapter, and an Ollama adapter.
- Gemini and Ollama are optional at test time because the evaluator may have no credentials or GPU; setting `VISION_PROVIDER` selects them without changing business logic.
- The first supplied key returned HTTP 403 project denial. After rotation, a real Gemini job completed all 6 images and persisted Gemini vision/embedding model records. A later cloud rerun reached the free-tier 20-request quota; the evaluator test command remains local/deterministic to avoid consuming quota.
