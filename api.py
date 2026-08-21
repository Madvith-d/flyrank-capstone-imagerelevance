"""FastAPI transport layer; domain logic remains in app.py."""
from __future__ import annotations

import os

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

import app as engine

app = FastAPI(title="AI Image Understanding & Content Matching Engine", version="1.1.0")


@app.on_event("startup")
def _startup():
    engine.seed()


class GuardRequest(BaseModel):
    post_id: str = Field(min_length=1)
    image_id: str = Field(min_length=1)


class ReviewRequest(GuardRequest):
    decision: str = Field(pattern="^(approved|rejected)$")
    reason: str = Field(default="", max_length=1000)


def _authorize(api_key: str | None) -> None:
    expected = os.getenv("API_AUTH_TOKEN", "").strip()
    if expected and api_key != expected:
        raise HTTPException(status_code=401, detail="missing or invalid X-API-Key")


@app.get("/health")
def health():
    return {"status": "ok", "database": "configured" if os.getenv("DATABASE_URL") else "sqlite"}


@app.get("/images")
def images():
    db = engine.connect()
    try:
        return {"images": [engine.row_image(row) for row in db.execute("SELECT * FROM images ORDER BY id")]}
    finally:
        db.close()


@app.get("/posts")
def posts():
    db = engine.connect()
    try:
        return {"posts": [dict(row) for row in db.execute("SELECT id,title,body,subject FROM posts ORDER BY id")]}
    finally:
        db.close()


@app.get("/posts/{post_id}/images")
def match(post_id: str):
    try:
        return engine.suggestions(post_id)
    except KeyError:
        raise HTTPException(404, "post not found")


@app.post("/jobs/batch", status_code=202)
def batch(
    background_tasks: BackgroundTasks,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
):
    _authorize(x_api_key)
    job = engine.create_batch_job(idempotency_key)
    if job["status"] in ("completed", "running"):
        return job
    if engine.claim_batch_job(job["id"]):
        background_tasks.add_task(engine.run_batch, idempotency_key, job["id"])
    return job


@app.get("/jobs/{job_id}")
def job(job_id: str):
    db = engine.connect()
    try:
        result = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not result:
            raise HTTPException(404, "job not found")
        return dict(result)
    finally:
        db.close()


@app.post("/guard")
def guard(request: GuardRequest, x_api_key: str | None = Header(default=None, alias="X-API-Key")):
    _authorize(x_api_key)
    try:
        result = engine.suggestions(request.post_id)
        return next(item for item in result["suggestions"] if item["image_id"] == request.image_id)
    except (KeyError, StopIteration):
        raise HTTPException(404, "post or image not found")


@app.post("/reviews", status_code=201)
def review(request: ReviewRequest, x_api_key: str | None = Header(default=None, alias="X-API-Key")):
    _authorize(x_api_key)
    result = engine.suggestions(request.post_id)
    candidate = next((item for item in result["suggestions"] if item["image_id"] == request.image_id), None)
    if candidate is None:
        raise HTTPException(404, "post or image not found")
    reason = request.reason or candidate["reason"]
    db = engine.connect()
    try:
        db.execute("INSERT INTO reviews(post_id,image_id,decision,reason) VALUES(?,?,?,?)", (request.post_id, request.image_id, request.decision, reason))
        db.commit()
        return {"status": "recorded", "decision": request.decision, "reason": reason}
    finally:
        db.close()


@app.get("/reviews")
def reviews():
    db = engine.connect()
    try:
        return {"reviews": [dict(row) for row in db.execute("SELECT * FROM reviews ORDER BY id")]}
    finally:
        db.close()


@app.get("/costs")
def costs():
    db = engine.connect()
    try:
        return {"costs": [dict(row) for row in db.execute("SELECT * FROM costs ORDER BY id")]}
    finally:
        db.close()


@app.get("/eval")
def evaluation():
    return engine.evaluate()
