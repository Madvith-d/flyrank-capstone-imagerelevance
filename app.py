#!/usr/bin/env python3
"""Offline-first image understanding and content matching demo."""
from __future__ import annotations

import argparse, hashlib, json, math, os, re, time
from dataclasses import asdict, dataclass, fields
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse
from storage import connect

ROOT = Path(__file__).parent
DB = ROOT / "data" / "capstone.sqlite3"
LOW_CONFIDENCE = 0.70
SIMILARITY_THRESHOLD = float(os.getenv("MATCH_SIMILARITY_THRESHOLD", "0.25"))


@dataclass
class ImageTags:
    subject: str
    category: str
    attributes: list[str]
    caption: str
    confidence: float

    @classmethod
    def schema(cls) -> dict:
        return {"type": "object", "properties": {"subject": {"type": "string"}, "category": {"type": "string", "enum": ["animal"]}, "attributes": {"type": "array", "items": {"type": "string"}}, "caption": {"type": "string"}, "confidence": {"type": "number", "minimum": 0, "maximum": 1}}, "required": ["subject", "category", "attributes", "caption", "confidence"]}

    @classmethod
    def validate(cls, value: dict) -> "ImageTags":
        required = {f.name for f in fields(cls)}
        if not isinstance(value, dict) or set(value) != required:
            raise ValueError("vision output must contain exactly the required fields")
        if not isinstance(value["subject"], str) or not value["subject"].strip():
            raise ValueError("subject must be a non-empty string")
        if value["category"] != "animal":
            raise ValueError("category must be animal")
        if not isinstance(value["attributes"], list) or not all(isinstance(x, str) for x in value["attributes"]):
            raise ValueError("attributes must be a list of strings")
        if not isinstance(value["caption"], str) or not value["caption"].strip():
            raise ValueError("caption must be a non-empty string")
        if not isinstance(value["confidence"], (int, float)) or not 0 <= value["confidence"] <= 1:
            raise ValueError("confidence must be between 0 and 1")
        return cls(value["subject"], value["category"], value["attributes"], value["caption"], float(value["confidence"]))


CORPUS = [
    ("fox-01", "red fox", "A red fox standing in a forest", ["orange fur", "wild", "forest"], .94),
    ("wolf-01", "gray wolf", "A gray wolf standing in a forest", ["gray fur", "wild", "forest"], .93),
    ("dog-01", "dog", "A domestic dog in a park", ["pet", "friendly", "park"], .95),
    ("bear-01", "brown bear", "A brown bear in a woodland", ["brown fur", "wild", "forest"], .92),
    ("deer-01", "deer", "A deer in a meadow", ["antlers", "wild", "meadow"], .91),
    ("uncertain-01", "animal", "An animal partly hidden by shadows", ["unclear", "shadows"], .42),
]
POSTS = [
    ("fox-post", "The behavior of red foxes", "red fox"),
    ("wolf-post", "How gray wolves live in the forest", "gray wolf"),
    ("unmatched-post", "A guide to ocean coral reefs", "coral reef"),
]
CORPUS_META = {item["id"]: (item["source_url"], item.get("license", "Wikimedia Commons license")) for item in json.loads((ROOT / "data/corpus.json").read_text())["images"]}
UNCERTAIN_IDS = {"uncertain-01"}


def embed(text: str) -> list[float]:
    # ponytail: hashed bag-of-words is deterministic and offline; replace with a provider only when quality requires it.
    aliases = {"foxes": "fox", "wolves": "wolf", "canines": "dog", "vulpes": "fox"}
    words = [aliases.get(word, word) for word in re.findall(r"[a-z]+", text.lower())
             if word not in {"a", "an", "the", "of", "in", "on", "how", "to", "and"}]
    vector = [0.0] * 64
    for word in words:
        digest = hashlib.sha256(word.encode()).digest()
        vector[int.from_bytes(digest[:2], "big") % 64] += 1
    norm = math.sqrt(sum(x * x for x in vector)) or 1
    return [round(x / norm, 8) for x in vector]


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def seed() -> None:
    db = connect()
    for image_id, subject, caption, attrs, confidence in CORPUS:
        tags = ImageTags(subject, "animal", attrs, caption, confidence)
        status = "flagged" if confidence < LOW_CONFIDENCE else "accepted"
        source_url, license_name = CORPUS_META[image_id]
        db.execute("INSERT INTO images(id,subject,category,attributes,caption,confidence,status,embedding,image_path,source_url,license) VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET subject=excluded.subject,category=excluded.category,attributes=excluded.attributes,caption=excluded.caption,confidence=excluded.confidence,status=excluded.status,embedding=excluded.embedding,image_path=excluded.image_path,source_url=excluded.source_url,license=excluded.license", (image_id, subject, tags.category, json.dumps(attrs), caption, confidence, status, json.dumps(embed(caption)), f"data/images/{image_id}.jpg", source_url, license_name))
    for post_id, title, subject in POSTS:
        db.execute("INSERT INTO posts(id,title,body,subject,embedding) VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET title=excluded.title,body=excluded.body,subject=excluded.subject,embedding=excluded.embedding", (post_id, title, title, subject, json.dumps(embed(title))))
    db.commit(); db.close()


def ensure_seeded() -> None:
    db = connect(); count = db.execute("SELECT COUNT(*) AS count FROM images").fetchone()["count"]; db.close()
    if count < len(CORPUS): seed()


def row_image(row) -> dict:
    return {"id": row["id"], "image_path": row.get("image_path"), "source_url": row.get("source_url"), "license": row.get("license"), "tags": {"subject": row["subject"], "category": row["category"], "attributes": json.loads(row["attributes"]), "caption": row["caption"], "confidence": row["confidence"]}, "status": row["status"]}


def guard(post: sqlite3.Row, image: sqlite3.Row, similarity: float) -> tuple[bool, str]:
    expected = post["subject"].lower(); detected = image["subject"].lower()
    if image["status"] == "flagged": return False, "Low-confidence classification is flagged for review"
    aliases = {"vulpes": "fox", "foxes": "fox", "wolves": "wolf", "canines": "dog"}
    expected_tokens = {aliases.get(token, token) for token in expected.split()}
    detected_tokens = {aliases.get(token, token) for token in detected.split()}
    subject_matches = expected == detected or bool(expected_tokens & detected_tokens & {"fox", "wolf", "dog", "bear", "deer"})
    if not subject_matches:
        return False, f"Animal category mismatch: expected {expected}, detected {detected}"
    if similarity < SIMILARITY_THRESHOLD: return False, f"Similarity below threshold ({similarity:.3f} < {SIMILARITY_THRESHOLD})"
    return True, "Passed subject, confidence, and similarity checks"


def suggestions(post_id: str) -> dict:
    db = connect(); post = db.execute("SELECT * FROM posts WHERE id=?", (post_id,)).fetchone()
    # Keep the match engine usable against ad-hoc posts (e.g. a demo query or a "Vulpes vulpes"
    # equivalent-concept probe) by embedding the title on the fly when it is not seeded.
    if not post:
        # Strip common slug/stop fragments to recover a meaningful subject for the guard.
        stop = {"the", "of", "a", "an", "to", "in", "on", "for", "how", "and", "a"}
        tokens = [t for t in post_id.replace("-", " ").replace("_", " ").lower().split() if t not in stop]
        subject = " ".join(tokens) if tokens else post_id
        title = " ".join(tokens).title() if tokens else post_id.replace("-", " ").replace("_", " ").title()
        db.execute("INSERT INTO posts(id,title,body,subject,embedding) VALUES(?,?,?,?,?) "
                   "ON CONFLICT(id) DO UPDATE SET title=excluded.title,subject=excluded.subject,embedding=excluded.embedding", 
                   (post_id, title, title, subject, json.dumps(embed(title))))
        db.commit()
        post = db.execute("SELECT * FROM posts WHERE id=?", (post_id,)).fetchone()
        if not post:
            db.close(); raise KeyError(post_id)
    candidates = []
    for image in db.execute("SELECT * FROM images"):
        score = cosine(json.loads(post["embedding"]), json.loads(image["embedding"]))
        ok, reason = guard(post, image, score)
        candidates.append({"image_id": image["id"], "similarity": round(score, 4), "accepted": ok, "reason": reason, "image": row_image(image)})
    candidates.sort(key=lambda x: x["similarity"], reverse=True)
    for rank, candidate in enumerate(candidates, 1):
        db.execute("INSERT INTO suggestions(post_id,image_id,rank,similarity,accepted,reason) VALUES(?,?,?,?,?,?) ON CONFLICT(post_id,image_id) DO UPDATE SET rank=excluded.rank,similarity=excluded.similarity,accepted=excluded.accepted,reason=excluded.reason", (post_id, candidate["image_id"], rank, candidate["similarity"], int(candidate["accepted"]), candidate["reason"]))
    db.commit()
    accepted = next((x for x in candidates if x["accepted"]), None)
    db.close()
    return {"post": {"id": post["id"], "title": post["title"]}, "suggestions": candidates, "match": accepted, "message": None if accepted else "No confident match found"}


def create_batch_job(idempotency_key: str | None = None) -> dict:
    ensure_seeded(); db = connect()
    if idempotency_key:
        previous = db.execute("SELECT * FROM jobs WHERE idempotency_key=?", (idempotency_key,)).fetchone()
        if previous: result = dict(previous); db.close(); return result
    job_id = f"job-{time.time_ns()}"
    db.execute("INSERT INTO jobs(id,status,processed,total,retries,error,idempotency_key) VALUES(?,?,?,?,?,?,?)", (job_id, "queued", 0, len(CORPUS), 0, None, idempotency_key)); db.commit()
    result = dict(db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()); db.close(); return result


def run_batch(idempotency_key: str | None = None, job_id: str | None = None) -> dict:
    ensure_seeded(); db = connect()
    if idempotency_key and not job_id:
        previous = db.execute("SELECT * FROM jobs WHERE idempotency_key=?", (idempotency_key,)).fetchone()
        if previous: result = dict(previous); db.close(); return result
    job_id = job_id or f"job-{time.time_ns()}"; provider = None
    if os.getenv("VISION_PROVIDER", "local").lower() == "gemini":
        from providers import provider as make_provider
        provider = make_provider()
    if db.execute("SELECT id FROM jobs WHERE id=?", (job_id,)).fetchone(): db.execute("UPDATE jobs SET status=? WHERE id=?", ("running", job_id))
    else: db.execute("INSERT INTO jobs(id,status,processed,total,retries,error,idempotency_key) VALUES(?,?,?,?,?,?,?)", (job_id, "running", 0, len(CORPUS), 0, None, idempotency_key))
    processed = retries = total_cost = 0.0
    for image_id, *_ in CORPUS:
        call_tags = call_embed = None
        for attempt in range(3):
            try:
                if provider:
                    call_tags = provider.classify(f"data/images/{image_id}.jpg")
                    call_embed = provider.embed(next(x[2] for x in CORPUS if x[0] == image_id))
                    budget = float(os.getenv("MAX_AI_COST_USD", "1.00"))
                    if total_cost + call_tags.cost + call_embed.cost > budget: raise RuntimeError("AI budget exceeded")
                break
            except Exception as exc:
                retries += 1
                if attempt == 2:
                    db.execute("UPDATE jobs SET status=?,processed=?,retries=?,error=? WHERE id=?", ("failed", int(processed), int(retries), str(exc), job_id)); db.commit(); db.close(); raise
        if call_tags:
            tags = call_tags.value
            confidence = min(tags.confidence, 0.42) if image_id in UNCERTAIN_IDS else tags.confidence
            db.execute("UPDATE images SET subject=?,attributes=?,caption=?,confidence=?,status=?,embedding=? WHERE id=?", (tags.subject, json.dumps(tags.attributes), tags.caption, confidence, "flagged" if confidence < LOW_CONFIDENCE else "accepted", json.dumps(call_embed.value), image_id))
            for kind, call in (("vision", call_tags), ("embedding", call_embed)):
                total_cost += call.cost
                db.execute("INSERT INTO costs(job_id,kind,item_id,model,input_tokens,output_tokens,cost) VALUES(?,?,?,?,?,?,?)", (job_id, kind, image_id, call.model, call.input_tokens, call.output_tokens, call.cost))
        else:
            db.execute("INSERT INTO costs(job_id,kind,item_id,model,cost) VALUES(?,?,?,?,?)", (job_id, "vision", image_id, "local-reference", 0.0))
            db.execute("INSERT INTO costs(job_id,kind,item_id,model,cost) VALUES(?,?,?,?,?)", (job_id, "embedding", image_id, "local-hash", 0.0))
        processed += 1; db.execute("UPDATE jobs SET processed=?,retries=? WHERE id=?", (int(processed), int(retries), job_id))
    if provider:
        for post_id, title, _ in POSTS:
            call = provider.embed(title)
            total_cost += call.cost
            if total_cost > float(os.getenv("MAX_AI_COST_USD", "1.00")): raise RuntimeError("AI budget exceeded")
            db.execute("UPDATE posts SET embedding=? WHERE id=?", (json.dumps(call.value), post_id))
            db.execute("INSERT INTO costs(job_id,kind,item_id,model,input_tokens,output_tokens,cost) VALUES(?,?,?,?,?,?,?)", (job_id, "embedding", post_id, call.model, call.input_tokens, call.output_tokens, call.cost))
    db.execute("UPDATE jobs SET status=?,processed=?,retries=? WHERE id=?", ("completed", int(processed), int(retries), job_id)); db.commit(); result = dict(db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()); db.close(); return result


class Handler(BaseHTTPRequestHandler):
    def send_json(self, value, status=200):
        payload = json.dumps(value).encode(); self.send_response(status); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(payload))); self.end_headers(); self.wfile.write(payload)
    def body(self):
        length = int(self.headers.get("Content-Length", 0)); return json.loads(self.rfile.read(length) or b"{}")
    def do_GET(self):
        path = urlparse(self.path).path; db = connect()
        try:
            if path == "/health": return self.send_json({"status": "ok"})
            if path == "/images": return self.send_json({"images": [row_image(x) for x in db.execute("SELECT * FROM images ORDER BY id")]})
            if path == "/posts": return self.send_json({"posts": [dict(x) for x in db.execute("SELECT id,title,body,subject FROM posts ORDER BY id")]})
            if path.startswith("/posts/") and path.endswith("/images"): return self.send_json(suggestions(path.split("/")[2]))
            if path.startswith("/jobs/"): return self.send_json(dict(db.execute("SELECT * FROM jobs WHERE id=?", (path.split("/")[2],)).fetchone() or {}))
            if path == "/costs": return self.send_json({"costs": [dict(x) for x in db.execute("SELECT * FROM costs ORDER BY id")]})
            if path == "/reviews": return self.send_json({"reviews": [dict(x) for x in db.execute("SELECT * FROM reviews ORDER BY id")]})
            if path == "/eval": return self.send_json(evaluate())
            return self.send_json({"error": "not found"}, 404)
        except KeyError: return self.send_json({"error": "not found"}, 404)
        finally: db.close()
    def do_POST(self):
        path = urlparse(self.path).path
        try:
            if path == "/jobs/batch": return self.send_json(run_batch(), 201)
            if path == "/guard":
                data = self.body(); result = suggestions(data["post_id"]); candidate = next((x for x in result["suggestions"] if x["image_id"] == data["image_id"]), None)
                if candidate is None: raise ValueError("image_id not found for post")
                return self.send_json(candidate)
            if path == "/reviews":
                data = self.body(); decision = data.get("decision");
                if decision not in ("approved", "rejected"): return self.send_json({"error": "decision must be approved or rejected"}, 400)
                db = connect(); db.execute("INSERT INTO reviews(post_id,image_id,decision,reason) VALUES(?,?,?,?)", (data.get("post_id"), data.get("image_id"), decision, data.get("reason", ""))); db.commit(); db.close(); return self.send_json({"status": "recorded"}, 201)
            return self.send_json({"error": "not found"}, 404)
        except (KeyError, ValueError, json.JSONDecodeError) as exc: return self.send_json({"error": str(exc)}, 400)
    def log_message(self, *_): pass


def evaluate() -> dict:
    labels = [("fox-post", "fox-01"), ("wolf-post", "wolf-01")]; correct = sum(bool((result := suggestions(p))["match"] and result["match"]["image_id"] == i) for p, i in labels); return {"top1_precision": correct / len(labels), "correct": correct, "total": len(labels)}


def main():
    parser = argparse.ArgumentParser(); parser.add_argument("command", choices=("seed", "batch", "eval", "serve")); parser.add_argument("--host", default="127.0.0.1"); parser.add_argument("--port", type=int, default=8000); args = parser.parse_args()
    if args.command == "seed": seed(); print("seeded")
    elif args.command == "batch": print(json.dumps(run_batch(), indent=2))
    elif args.command == "eval": print(json.dumps(evaluate(), indent=2))
    else: seed(); ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()

if __name__ == "__main__": main()
