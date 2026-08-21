# Design: AI Image Understanding & Content Matching Engine

## Problem

The service processes a small, licensed image corpus and matches images to article content by meaning rather than filenames. Its central reliability promise is conservative behavior: a strong semantic candidate is returned only when the extracted subject, classification confidence, and similarity score all clear the guard; otherwise the API returns an explanation and no confident match.

## Data model

`images` stores the source record and denormalized current metadata. `image_tags` stores the validated vision result as a first-class record. `image_embeddings` and `post_embeddings` store JSON vectors, model names, and dimensions. `posts` stores article text and its current embedding. `suggestions` stores ranked candidate decisions and explanations. `jobs` tracks asynchronous batch progress, retries, failures, and idempotency keys. `costs` records every vision or embedding call. `reviews` records human approval or rejection decisions with the reason shown to the reviewer.

## Matching and guard strategy

The batch worker calls one provider for each image, validates the exact `ImageTags` schema, flags classifications below `LOW_CONFIDENCE_THRESHOLD`, and writes an image embedding from the caption. Article text is embedded into the same vector space. Candidates are ranked by cosine similarity. The guard first rejects flagged images, then requires overlap between normalized subject concepts such as `foxes` and `vulpes`, and finally requires `MATCH_SIMILARITY_THRESHOLD`. Every rejection reason is returned with the candidate.

## API surface

| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/health` | Liveness and database mode. |
| `GET` | `/images` | Inspect image metadata and classification state. |
| `GET` | `/posts/{post_id}/images` | Rank candidates and return the accepted match or no-match explanation. |
| `POST` | `/jobs/batch` | Create an idempotent asynchronous batch job. |
| `GET` | `/jobs/{job_id}` | Read progress, retry count, and failure details. |
| `POST` | `/guard` | Force-inspect one candidate against one post. |
| `POST` | `/reviews` | Approve or reject a pairing with validated input. |
| `GET` | `/reviews` | Inspect the review trail. |
| `GET` | `/costs` | Inspect per-call cost attribution. |
| `GET` | `/eval` | Run the committed labeled top-1 evaluation set. |

Mutating endpoints accept an optional `X-API-Key` when `API_AUTH_TOKEN` is configured. It is blank by default for the evaluator's local demo path.

## Layer sketch

```text
HTTP / FastAPI boundary
          |
          v
Domain engine: schema validation -> batch worker -> embeddings -> ranking -> mismatch guard
          |
          +--> Provider adapters: local reference | Gemini | Ollama
          |
          v
Persistence: PostgreSQL in Docker or SQLite fallback
          |
          +--> image_tags / image_embeddings / post_embeddings / jobs / costs / suggestions / reviews
```

## Explicit non-goal

This capstone does not build a public image-management UI, multi-tenant account system, or large-scale ANN search service. The review interface is intentionally API-first, and JSON vectors are sufficient for the small reproducible corpus; a production deployment could later adopt pgvector and a full identity provider.

