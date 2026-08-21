#!/usr/bin/env python3
"""Offline-first image understanding and content matching engine."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import time
from dataclasses import asdict, dataclass, fields
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from storage import connect

ROOT = Path(__file__).parent
LOW_CONFIDENCE = float(os.getenv("LOW_CONFIDENCE_THRESHOLD", "0.70"))
SIMILARITY_THRESHOLD = float(os.getenv("MATCH_SIMILARITY_THRESHOLD", "0.25"))
MAX_RETRIES = 3


@dataclass
class ImageTags:
    subject: str
    category: str
    attributes: list[str]
    caption: str
    confidence: float

    @classmethod
    def schema(cls) -> dict:
        return {
            "type": "object",
            "properties": {
                "subject": {"type": "string", "minLength": 1},
                "category": {"type": "string", "enum": ["animal"]},
                "attributes": {"type": "array", "items": {"type": "string"}},
                "caption": {"type": "string", "minLength": 1},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            },
            "required": ["subject", "category", "attributes", "caption", "confidence"],
            "additionalProperties": False,
        }

    @classmethod
    def validate(cls, value: dict) -> "ImageTags":
        required = {field.name for field in fields(cls)}
        if not isinstance(value, dict) or set(value) != required:
            raise ValueError("vision output must contain exactly the required fields")
        if not isinstance(value["subject"], str) or not value["subject"].strip():
            raise ValueError("subject must be a non-empty string")
        if value["category"] != "animal":
            raise ValueError("category must be animal")
        if not isinstance(value["attributes"], list) or not all(isinstance(item, str) and item.strip() for item in value["attributes"]):
            raise ValueError("attributes must be a non-empty list of strings")
        if not isinstance(value["caption"], str) or not value["caption"].strip():
            raise ValueError("caption must be a non-empty string")
        if isinstance(value["confidence"], bool) or not isinstance(value["confidence"], (int, float)) or not 0 <= value["confidence"] <= 1:
            raise ValueError("confidence must be between 0 and 1")
        return cls(value["subject"].strip(), value["category"], value["attributes"], value["caption"].strip(), float(value["confidence"]))


CORPUS = [
    ("fox-01", "red fox", "A red fox standing in a forest", ["orange fur", "wild", "forest"], 0.94),
    ("wolf-01", "gray wolf", "A gray wolf standing in a forest", ["gray fur", "wild", "forest"], 0.93),
    ("dog-01", "dog", "A domestic dog in a park", ["pet", "friendly", "park"], 0.95),
    ("bear-01", "brown bear", "A brown bear in a woodland", ["brown fur", "wild", "forest"], 0.92),
    ("deer-01", "deer", "A deer in a meadow", ["antlers", "wild", "meadow"], 0.91),
    ("uncertain-01", "animal", "An animal partly hidden by shadows", ["unclear", "shadows"], 0.42),
]
POSTS = [
    ("fox-post", "The behavior of red foxes", "red fox"),
    ("wolf-post", "How gray wolves live in the forest", "gray wolf"),
    ("dog-post", "Caring for a domestic dog", "dog"),
    ("unmatched-post", "A guide to ocean coral reefs", "coral reef"),
]
EVAL_SET = [("fox-post", "fox-01"), ("wolf-post", "wolf-01"), ("dog-post", "dog-01")]
CORPUS_META = {
    item["id"]: (item["source_url"], item.get("license", "Wikimedia Commons license"))
    for item in json.loads((ROOT / "data/corpus.json").read_text())["images"]
}
UNCERTAIN_IDS = {"uncertain-01"}


ALIASES = {
    "vulpes": "fox",
    "foxes": "fox",
    "wolves": "wolf",
    "canines": "dog",
}
STOP_WORDS = {"a", "an", "the", "of", "in", "on", "how", "to", "and", "for", "is"}
KNOWN_SUBJECTS = {"fox", "wolf", "dog", "bear", "deer"}


def embed(text: str) -> list[float]:
    """Deterministic reference embedding used offline; provider vectors replace it in cloud/local-model mode."""
    words = [ALIASES.get(word, word) for word in re.findall(r"[a-z]+", text.lower()) if word not in STOP_WORDS]
    vector = [0.0] * 64
    for word in words:
        digest = hashlib.sha256(word.encode()).digest()
        vector[int.from_bytes(digest[:2], "big") % len(vector)] += 1
    norm = math.sqrt(sum(value * value for value in vector)) or 1
    return [round(value / norm, 8) for value in vector]


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    return sum(x * y for x, y in zip(a, b))


def _upsert_tag_and_vector(db, image_id: str, tags: ImageTags, vector: list[float], model: str) -> None:
    status = "flagged" if tags.confidence < LOW_CONFIDENCE else "accepted"
    db.execute(
        "UPDATE images SET subject=?,category=?,attributes=?,caption=?,confidence=?,status=?,embedding=? WHERE id=?",
        (tags.subject, tags.category, json.dumps(tags.attributes), tags.caption, tags.confidence, status, json.dumps(vector), image_id),
    )
    db.execute(
        "INSERT INTO image_tags(image_id,subject,category,attributes,caption,confidence,status) VALUES(?,?,?,?,?,?,?) "
        "ON CONFLICT(image_id) DO UPDATE SET subject=excluded.subject,category=excluded.category,attributes=excluded.attributes,caption=excluded.caption,confidence=excluded.confidence,status=excluded.status",
        (image_id, tags.subject, tags.category, json.dumps(tags.attributes), tags.caption, tags.confidence, status),
    )
    db.execute(
        "INSERT INTO image_embeddings(image_id,vector,model,dimension) VALUES(?,?,?,?) "
        "ON CONFLICT(image_id) DO UPDATE SET vector=excluded.vector,model=excluded.model,dimension=excluded.dimension",
        (image_id, json.dumps(vector), model, len(vector)),
    )


def _upsert_post_vector(db, post_id: str, vector: list[float], model: str) -> None:
    db.execute("UPDATE posts SET embedding=? WHERE id=?", (json.dumps(vector), post_id))
    db.execute(
        "INSERT INTO post_embeddings(post_id,vector,model,dimension) VALUES(?,?,?,?) "
        "ON CONFLICT(post_id) DO UPDATE SET vector=excluded.vector,model=excluded.model,dimension=excluded.dimension",
        (post_id, json.dumps(vector), model, len(vector)),
    )


def seed() -> None:
    db = connect()
    for image_id, subject, caption, attrs, confidence in CORPUS:
        tags = ImageTags(subject, "animal", attrs, caption, confidence)
        status = "flagged" if confidence < LOW_CONFIDENCE else "accepted"
        source_url, license_name = CORPUS_META[image_id]
        vector = embed(caption)
        db.execute(
            "INSERT INTO images(id,subject,category,attributes,caption,confidence,status,embedding,image_path,source_url,license) VALUES(?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(id) DO UPDATE SET subject=excluded.subject,category=excluded.category,attributes=excluded.attributes,caption=excluded.caption,confidence=excluded.confidence,status=excluded.status,embedding=excluded.embedding,image_path=excluded.image_path,source_url=excluded.source_url,license=excluded.license",
            (image_id, subject, tags.category, json.dumps(attrs), caption, confidence, status, json.dumps(vector), f"data/images/{image_id}.jpg", source_url, license_name),
        )
        _upsert_tag_and_vector(db, image_id, tags, vector, "local-hash")
    for post_id, title, subject in POSTS:
        vector = embed(title)
        db.execute(
            "INSERT INTO posts(id,title,body,subject,embedding) VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET title=excluded.title,body=excluded.body,subject=excluded.subject,embedding=excluded.embedding",
            (post_id, title, title, subject, json.dumps(vector)),
        )
        _upsert_post_vector(db, post_id, vector, "local-hash")
    db.commit()
    db.close()


def ensure_seeded() -> None:
    db = connect()
    count = db.execute("SELECT COUNT(*) AS count FROM images").fetchone()["count"]
    db.close()
    if count < len(CORPUS):
        seed()


def row_image(row) -> dict:
    return {
        "id": row["id"],
        "image_path": row.get("image_path"),
        "source_url": row.get("source_url"),
        "license": row.get("license"),
        "tags": {
            "subject": row["subject"],
            "category": row["category"],
            "attributes": json.loads(row["attributes"]),
            "caption": row["caption"],
            "confidence": row["confidence"],
        },
        "status": row["status"],
    }


def _normalise_subject_tokens(value: str) -> set[str]:
    return {ALIASES.get(token, token) for token in re.findall(r"[a-z]+", value.lower())}


def guard(post, image, similarity: float) -> tuple[bool, str]:
    expected = post["subject"].lower()
    detected = image["subject"].lower()
    if image["status"] == "flagged":
        return False, "Low-confidence classification is flagged for review"
    expected_tokens = _normalise_subject_tokens(expected)
    detected_tokens = _normalise_subject_tokens(detected)
    subject_matches = bool(expected_tokens & detected_tokens & KNOWN_SUBJECTS)
    if not subject_matches:
        return False, f"Animal category mismatch: expected {expected}, detected {detected}"
    if similarity < SIMILARITY_THRESHOLD:
        return False, f"Similarity below threshold ({similarity:.3f} < {SIMILARITY_THRESHOLD})"
    return True, "Passed subject, confidence, and similarity checks"


def suggestions(post_id: str) -> dict:
    ensure_seeded()
    db = connect()
    post = db.execute("SELECT * FROM posts WHERE id=?", (post_id,)).fetchone()
    if not post:
        tokens = [token for token in re.findall(r"[a-z]+", post_id.replace("-", " ").replace("_", " ").lower()) if token not in STOP_WORDS]
        subject = " ".join(tokens) if tokens else post_id
        title = " ".join(tokens).title() if tokens else post_id.replace("-", " ").replace("_", " ").title()
        vector = embed(title)
        db.execute("INSERT INTO posts(id,title,body,subject,embedding) VALUES(?,?,?,?,?)", (post_id, title, title, subject, json.dumps(vector)))
        _upsert_post_vector(db, post_id, vector, "local-hash")
        db.commit()
        post = db.execute("SELECT * FROM posts WHERE id=?", (post_id,)).fetchone()
    candidates = []
    post_vector = json.loads(post["embedding"] or "[]")
    for image in db.execute("SELECT * FROM images"):
        score = cosine(post_vector, json.loads(image["embedding"] or "[]"))
        ok, reason = guard(post, image, score)
        candidates.append({"image_id": image["id"], "similarity": round(score, 4), "accepted": ok, "reason": reason, "image": row_image(image)})
    candidates.sort(key=lambda item: item["similarity"], reverse=True)
    for rank, candidate in enumerate(candidates, 1):
        db.execute(
            "INSERT INTO suggestions(post_id,image_id,rank,similarity,accepted,reason) VALUES(?,?,?,?,?,?) "
            "ON CONFLICT(post_id,image_id) DO UPDATE SET rank=excluded.rank,similarity=excluded.similarity,accepted=excluded.accepted,reason=excluded.reason",
            (post_id, candidate["image_id"], rank, candidate["similarity"], int(candidate["accepted"]), candidate["reason"]),
        )
    db.commit()
    accepted = next((item for item in candidates if item["accepted"]), None)
    db.close()
    return {
        "post": {"id": post["id"], "title": post["title"]},
        "suggestions": candidates,
        "match": accepted,
        "message": None if accepted else "No confident match found",
    }


def create_batch_job(idempotency_key: str | None = None) -> dict:
    ensure_seeded()
    db = connect()
    if idempotency_key:
        previous = db.execute("SELECT * FROM jobs WHERE idempotency_key=?", (idempotency_key,)).fetchone()
        if previous:
            result = dict(previous)
            db.close()
            return result
    job_id = f"job-{time.time_ns()}"
    db.execute(
        "INSERT INTO jobs(id,status,processed,total,retries,error,idempotency_key) VALUES(?,?,?,?,?,?,?)",
        (job_id, "queued", 0, len(CORPUS), 0, None, idempotency_key),
    )
    db.commit()
    result = dict(db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())
    db.close()
    return result


def claim_batch_job(job_id: str) -> bool:
    db = connect()
    claimed = bool(db.execute("UPDATE jobs SET status=?,updated_at=CURRENT_TIMESTAMP WHERE id=? AND status=? RETURNING id", ("running", job_id, "queued")))
    db.commit()
    db.close()
    return claimed


def _provider_for_batch():
    from providers import provider as make_provider
    return make_provider()


def run_batch(idempotency_key: str | None = None, job_id: str | None = None) -> dict:
    ensure_seeded()
    db = connect()
    if idempotency_key and not job_id:
        previous = db.execute("SELECT * FROM jobs WHERE idempotency_key=?", (idempotency_key,)).fetchone()
        if previous and previous["status"] in ("completed", "running"):
            result = dict(previous)
            db.close()
            return result
    job_id = job_id or f"job-{time.time_ns()}"
    existing = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    if existing and existing["status"] == "completed":
        result = dict(existing)
        db.close()
        return result
    if existing:
        db.execute("UPDATE jobs SET status=?,error=? WHERE id=?", ("running", None, job_id))
    else:
        db.execute("INSERT INTO jobs(id,status,processed,total,retries,error,idempotency_key) VALUES(?,?,?,?,?,?,?)", (job_id, "running", 0, len(CORPUS), 0, None, idempotency_key))
    db.commit()
    db.close()

    provider = _provider_for_batch()
    processed = 0
    retries = 0
    total_cost = 0.0
    budget = float(os.getenv("MAX_AI_COST_USD", "1.00"))
    try:
        for image_id, subject, caption, attrs, confidence in CORPUS:
            call_tags = call_embed = None
            for attempt in range(MAX_RETRIES):
                try:
                    call_tags = provider.classify(f"data/images/{image_id}.jpg")
                    payload = asdict(call_tags.value) if hasattr(call_tags.value, "__dataclass_fields__") else call_tags.value
                    tags = ImageTags.validate(payload)
                    call_embed = provider.embed(tags.caption)
                    if not isinstance(call_embed.value, list) or not call_embed.value:
                        raise ValueError("embedding provider returned an empty vector")
                    if total_cost + call_tags.cost + call_embed.cost > budget:
                        raise RuntimeError("AI budget exceeded")
                    break
                except Exception as exc:
                    retries += 1
                    if attempt == MAX_RETRIES - 1:
                        raise RuntimeError(f"{image_id}: {exc}") from exc
            db = connect()
            vector = [float(value) for value in call_embed.value]
            _upsert_tag_and_vector(db, image_id, tags, vector, call_embed.model)
            for kind, call in (("vision", call_tags), ("embedding", call_embed)):
                total_cost += call.cost
                db.execute(
                    "INSERT INTO costs(job_id,kind,item_id,model,input_tokens,output_tokens,cost) VALUES(?,?,?,?,?,?,?)",
                    (job_id, kind, image_id, call.model, call.input_tokens, call.output_tokens, call.cost),
                )
            processed += 1
            db.execute("UPDATE jobs SET processed=?,retries=?,updated_at=CURRENT_TIMESTAMP WHERE id=?", (processed, retries, job_id))
            db.commit()
            db.close()

        db = connect()
        for post_id, title, _ in POSTS:
            call = provider.embed(title)
            if not isinstance(call.value, list) or not call.value:
                raise ValueError("embedding provider returned an empty vector")
            if total_cost + call.cost > budget:
                raise RuntimeError("AI budget exceeded")
            total_cost += call.cost
            _upsert_post_vector(db, post_id, [float(value) for value in call.value], call.model)
            db.execute(
                "INSERT INTO costs(job_id,kind,item_id,model,input_tokens,output_tokens,cost) VALUES(?,?,?,?,?,?,?)",
                (job_id, "embedding", post_id, call.model, call.input_tokens, call.output_tokens, call.cost),
            )
        db.execute("UPDATE jobs SET status=?,processed=?,retries=?,updated_at=CURRENT_TIMESTAMP WHERE id=?", ("completed", processed, retries, job_id))
        db.commit()
        result = dict(db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())
        db.close()
        return result
    except Exception as exc:
        db = connect()
        db.execute("UPDATE jobs SET status=?,processed=?,retries=?,error=?,updated_at=CURRENT_TIMESTAMP WHERE id=?", ("failed", processed, retries, str(exc), job_id))
        db.commit()
        result = dict(db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())
        db.close()
        raise RuntimeError(json.dumps(result)) from exc


def evaluate() -> dict:
    correct = sum(bool((result := suggestions(post_id))["match"] and result["match"]["image_id"] == expected_image) for post_id, expected_image in EVAL_SET)
    return {"top1_precision": round(correct / len(EVAL_SET), 4), "correct": correct, "total": len(EVAL_SET), "dataset": "data/eval.json"}


class Handler(BaseHTTPRequestHandler):
    def send_json(self, value, status=200):
        payload = json.dumps(value).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def body(self):
        length = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(length) or b"{}")

    def do_GET(self):
        path = urlparse(self.path).path
        db = connect()
        try:
            if path == "/health": return self.send_json({"status": "ok"})
            if path == "/images": return self.send_json({"images": [row_image(row) for row in db.execute("SELECT * FROM images ORDER BY id")]})
            if path == "/posts": return self.send_json({"posts": [dict(row) for row in db.execute("SELECT id,title,body,subject FROM posts ORDER BY id")]})
            if path.startswith("/posts/") and path.endswith("/images"): return self.send_json(suggestions(path.split("/")[2]))
            if path.startswith("/jobs/"):
                row = db.execute("SELECT * FROM jobs WHERE id=?", (path.split("/")[2],)).fetchone()
                return self.send_json(dict(row) if row else {"error": "not found"}, 200 if row else 404)
            if path == "/costs": return self.send_json({"costs": [dict(row) for row in db.execute("SELECT * FROM costs ORDER BY id")]})
            if path == "/reviews": return self.send_json({"reviews": [dict(row) for row in db.execute("SELECT * FROM reviews ORDER BY id")]})
            if path == "/eval": return self.send_json(evaluate())
            return self.send_json({"error": "not found"}, 404)
        except KeyError:
            return self.send_json({"error": "not found"}, 404)
        finally:
            db.close()

    def do_POST(self):
        path = urlparse(self.path).path
        try:
            if path == "/jobs/batch":
                return self.send_json(run_batch(), 201)
            if path == "/guard":
                data = self.body()
                if not isinstance(data.get("post_id"), str) or not data["post_id"].strip() or not isinstance(data.get("image_id"), str) or not data["image_id"].strip():
                    return self.send_json({"error": "post_id and image_id are required"}, 422)
                result = suggestions(data["post_id"])
                candidate = next((item for item in result["suggestions"] if item["image_id"] == data["image_id"]), None)
                if candidate is None:
                    return self.send_json({"error": "image_id not found for post"}, 404)
                return self.send_json(candidate)
            if path == "/reviews":
                data = self.body()
                decision = data.get("decision")
                if not isinstance(data.get("post_id"), str) or not data["post_id"].strip() or not isinstance(data.get("image_id"), str) or not data["image_id"].strip():
                    return self.send_json({"error": "post_id and image_id are required"}, 422)
                if decision not in ("approved", "rejected"):
                    return self.send_json({"error": "decision must be approved or rejected"}, 422)
                candidate = next((item for item in suggestions(data["post_id"])["suggestions"] if item["image_id"] == data["image_id"]), None)
                if candidate is None:
                    return self.send_json({"error": "post or image not found"}, 404)
                reason = data.get("reason") or candidate["reason"]
                db = connect()
                db.execute("INSERT INTO reviews(post_id,image_id,decision,reason) VALUES(?,?,?,?)", (data["post_id"], data["image_id"], decision, reason))
                db.commit()
                db.close()
                return self.send_json({"status": "recorded", "decision": decision, "reason": reason}, 201)
            return self.send_json({"error": "not found"}, 404)
        except (KeyError, ValueError, json.JSONDecodeError) as exc:
            return self.send_json({"error": str(exc)}, 400)

    def log_message(self, *_):
        pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("seed", "batch", "eval", "serve"))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    if args.command == "seed":
        seed(); print("seeded")
    elif args.command == "batch":
        print(json.dumps(run_batch(), indent=2))
    elif args.command == "eval":
        print(json.dumps(evaluate(), indent=2))
    else:
        seed(); ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
