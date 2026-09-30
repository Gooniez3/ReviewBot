import hashlib
import hmac
import json
import os

import redis
from fastapi import FastAPI, Header, HTTPException, Request
from rq import Queue

WEBHOOK_SECRET = os.environ["GITHUB_WEBHOOK_SECRET"]
REDIS_URL = os.environ["REDIS_URL"]

app = FastAPI(title="reviewbot")
redis_conn = redis.from_url(REDIS_URL)
queue = Queue("reviews", connection=redis_conn)

# Only review when a PR is opened, updated with new commits, or reopened.
REVIEW_ACTIONS = {"opened", "synchronize", "reopened"}


def verify_signature(body: bytes, signature_header: str | None) -> bool:
    """GitHub signs the raw body with HMAC-SHA256 using your webhook secret."""
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(
        WEBHOOK_SECRET.encode(), body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature_header)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/webhook")
async def webhook(
    request: Request,
    x_github_event: str = Header(default=""),
    x_github_delivery: str = Header(default=""),
    x_hub_signature_256: str | None = Header(default=None),
):
    body = await request.body()

    if not verify_signature(body, x_hub_signature_256):
        raise HTTPException(status_code=401, detail="invalid signature")

    if x_github_event == "ping":
        return {"msg": "pong"}

    if x_github_event != "pull_request":
        return {"msg": "ignored event"}

    payload = json.loads(body)
    if payload.get("action") not in REVIEW_ACTIONS:
        return {"msg": "ignored action"}

    # GitHub can deliver the same event more than once. SET NX makes this idempotent.
    first_time = redis_conn.set(
        f"delivery:{x_github_delivery}", 1, nx=True, ex=60 * 60 * 24
    )
    if not first_time:
        return {"msg": "duplicate delivery"}

    pr = payload["pull_request"]
    job_data = {
        "installation_id": payload["installation"]["id"],
        "repo_full_name": payload["repository"]["full_name"],
        "pr_number": pr["number"],
        "head_sha": pr["head"]["sha"],
    }

    # Respond fast: GitHub expects a reply within ~10 seconds. Do the work in a worker.
    queue.enqueue("app.worker.review_pull_request", job_data, job_timeout=300)
    return {"msg": "queued"}
