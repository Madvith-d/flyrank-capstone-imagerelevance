# Evidence

Re-verified locally on 2026-08-21 with `VISION_PROVIDER=local`, a fresh SQLite database, and the committed six-record acceptance corpus. The primary command was:

```text
$ VISION_PROVIDER=local python3 -m unittest discover -s tests -v
Ran 16 tests in 0.076s
OK
```

| Definition-of-done checkbox | Evidence |
|---|---|
| Vision output is schema-validated and invalid output is never trusted. | `test_schema_rejects_invalid_output` and `test_schema_rejects_extra_fields_and_boolean_confidence` pass. `ImageTags.validate()` requires exactly five fields, rejects extras, and rejects malformed confidence values. Gemini and Ollama adapters validate responses before persistence. |
| Low-confidence classifications are flagged. | `test_low_confidence_flagged` passes; `uncertain-01` is stored with `status='flagged'` because confidence `0.42` is below `LOW_CONFIDENCE_THRESHOLD=0.70`. |
| Images run through a background batch job with retries. | `POST /jobs/batch` creates a queued job and FastAPI schedules `run_batch` through `BackgroundTasks`; `test_atomic_batch_claim` proves one queued job can be claimed once; `test_retry_failure_is_persisted` proves three attempts and a persisted `failed` status/error. |
| Vision and embedding costs are tracked per call. | `test_costs_are_attributed` passes; the `costs` table contains `vision` and `embedding` rows with non-empty model names, item IDs, job IDs, token fields, and cost values. `MAX_AI_COST_USD` stops a batch before the configured budget is exceeded. |
| Image and post embeddings are stored and ranked. | `test_normalized_tags_and_embeddings_are_persisted` passes with six `image_tags`, six `image_embeddings`, and four `post_embeddings` records. `test_fox_ranks_first` proves the fox candidate is ranked above the wolf. |
| Equivalent semantic concepts match. | `test_semantic_alias_vulpes` passes: ad-hoc `vulpes-vulpes` resolves to `fox-01` through the normalized alias map. |
| The mismatch guard rejects the wolf on a fox post. | `test_wolf_is_rejected` and `test_guard_rejects_wolf_with_reason` pass. The returned reason contains `Animal category mismatch: expected red fox, detected gray wolf`. |
| Rejections have human-readable explanations. | Every candidate includes a non-empty `reason`; the wolf probe returns the explicit subject mismatch explanation, and `test_no_match` verifies reasons are present for all candidates. |
| No suitable image returns a safe no-match response. | `test_no_match` passes for `unmatched-post`; response has `match: null`, message `No confident match found`, and per-candidate reasons such as subject mismatch or similarity below threshold. |
| Database models and required indexes exist. | `migrations/001_init.sql` and the runtime schema define `images`, `image_tags`, `image_embeddings`, `posts`, `post_embeddings`, `jobs`, `costs`, `suggestions`, and constrained `reviews`; indexes cover subjects, vector models, job status/costs, review pairs, and `(post_id, rank)` suggestions. |
| Validated API endpoints and review workflow exist. | `test_api_boundary_validation` proves invalid IDs and decisions raise Pydantic validation errors. `POST /reviews` validates the pairing, stores `approved`/`rejected` plus the displayed reason, and `GET /reviews` exposes the audit trail. Optional `API_AUTH_TOKEN` protects mutating endpoints with `X-API-Key`. |
| Automated tests cover schema, mismatch rejection, and matching accuracy. | The deterministic suite has 16 passing tests covering schema, low confidence, ranking, semantic aliasing, guard rejection, no-match, persistence, retries, idempotency, authorization models, and evaluation. |
| A labeled evaluation dataset measures top-1 precision. | `data/eval.json` contains three labels: fox, wolf, and dog. `GET /eval` and `python3 app.py eval` report `{"top1_precision": 1.0, "correct": 3, "total": 3}`. |
| README, architecture, and submission-pack files exist. | `README.md`, `DESIGN.md`, `capstone.yaml`, `EVIDENCE.md`, `BUILDLOG.md`, `.env.example`, `migrations/001_init.sql`, and `data/eval.json` are committed. README includes the ASCII architecture, exact local/Docker commands, evaluator probes, precision number, and limitations. |

## Acceptance probe transcript

```text
$ VISION_PROVIDER=local python3 app.py eval
{
  "top1_precision": 1.0,
  "correct": 3,
  "total": 3,
  "dataset": "data/eval.json"
}

$ VISION_PROVIDER=local python3 -m unittest discover -s tests -v
Ran 16 tests in 0.076s
OK
```

The cloud providers are optional and were not invoked during the deterministic verification run, so the verification does not consume a paid or rate-limited service.
