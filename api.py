"""FastAPI transport layer; domain logic remains in app.py."""
from fastapi import BackgroundTasks, FastAPI, HTTPException, Header
from pydantic import BaseModel, Field
import app as engine

app = FastAPI(title="AI Image Matching Engine", version="1.0.0")

class GuardRequest(BaseModel):
    post_id: str = Field(min_length=1)
    image_id: str = Field(min_length=1)

class ReviewRequest(GuardRequest):
    decision: str = Field(pattern="^(approved|rejected)$")
    reason: str = ""

@app.get("/health")
def health(): return {"status": "ok", "database": "configured" if __import__('os').getenv("DATABASE_URL") else "sqlite"}

@app.get("/images")
def images():
    db = engine.connect()
    try: return {"images": [engine.row_image(x) for x in db.execute("SELECT * FROM images ORDER BY id")]}
    finally: db.close()

@app.get("/posts")
def posts():
    db = engine.connect()
    try: return {"posts": [dict(x) for x in db.execute("SELECT id,title,body,subject FROM posts ORDER BY id")]}
    finally: db.close()

@app.get("/posts/{post_id}/images")
def match(post_id: str):
    try: return engine.suggestions(post_id)
    except KeyError: raise HTTPException(404, "post not found")

@app.post("/jobs/batch", status_code=201)
def batch(background_tasks: BackgroundTasks, idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
    job = engine.create_batch_job(idempotency_key)
    if job["status"] in ("completed", "running"): return job
    background_tasks.add_task(engine.run_batch, idempotency_key, job["id"])
    return job

@app.get("/jobs/{job_id}")
def job(job_id: str):
    db = engine.connect()
    try:
        result = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not result: raise HTTPException(404, "job not found")
        return dict(result)
    finally: db.close()

@app.post("/guard")
def guard(request: GuardRequest):
    try:
        result = engine.suggestions(request.post_id)
        return next(x for x in result["suggestions"] if x["image_id"] == request.image_id)
    except (KeyError, StopIteration): raise HTTPException(404, "post or image not found")

@app.post("/reviews", status_code=201)
def review(request: ReviewRequest):
    db = engine.connect()
    try:
        db.execute("INSERT INTO reviews(post_id,image_id,decision,reason) VALUES(?,?,?,?)", (request.post_id, request.image_id, request.decision, request.reason)); db.commit()
        return {"status": "recorded"}
    finally: db.close()

@app.get("/reviews")
def reviews():
    db = engine.connect()
    try: return {"reviews": [dict(x) for x in db.execute("SELECT * FROM reviews ORDER BY id")]}
    finally: db.close()

@app.get("/costs")
def costs():
    db = engine.connect()
    try: return {"costs": [dict(x) for x in db.execute("SELECT * FROM costs ORDER BY id")]}
    finally: db.close()

@app.get("/eval")
def evaluation(): return engine.evaluate()
