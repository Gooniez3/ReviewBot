import hashlib
import hmac
import json
import logging
import os

import redis
from fastapi import FastAPI, Header, HTTPException, Request
from rq import Queue

logger = logging.getLogger(__name__)

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

    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=400, detail="invalid JSON payload") from exc

    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="payload must be a JSON object")

    if payload.get("action") not in REVIEW_ACTIONS:
        return {"msg": "ignored action"}

    delivery_id = x_github_delivery.strip()
    if not delivery_id:
        raise HTTPException(
            status_code=400, detail="missing X-GitHub-Delivery header"
        )

    try:
        installation_id = payload["installation"]["id"]
        repo_full_name = payload["repository"]["full_name"]
        pr = payload["pull_request"]
        pr_number = pr["number"]
        head_sha = pr["head"]["sha"]
    except (KeyError, TypeError) as exc:
        raise HTTPException(
            status_code=400, detail="missing required pull request fields"
        ) from exc

    if (
        not isinstance(installation_id, int)
        or isinstance(installation_id, bool)
        or installation_id <= 0
        or not isinstance(repo_full_name, str)
        or not repo_full_name.strip()
        or not isinstance(pr_number, int)
        or isinstance(pr_number, bool)
        or pr_number <= 0
        or not isinstance(head_sha, str)
        or not head_sha.strip()
    ):
        raise HTTPException(
            status_code=400, detail="invalid required pull request fields"
        )

    # GitHub can deliver the same event more than once. SET NX makes this idempotent.
    delivery_key = f"delivery:{delivery_id}"
    first_time = redis_conn.set(
        delivery_key, 1, nx=True, ex=60 * 60 * 24
    )
    if not first_time:
        return {"msg": "duplicate delivery"}

    job_data = {
        "installation_id": installation_id,
        "repo_full_name": repo_full_name,
        "pr_number": pr_number,
        "head_sha": head_sha,
    }

    # Respond fast: GitHub expects a reply within ~10 seconds. Do the work in a worker.
    try:
        queue.enqueue("worker.review_pull_request", job_data, job_timeout=300)
    except Exception as exc:
        # Allow a GitHub redelivery to try again if enqueueing did not succeed.
        try:
            redis_conn.delete(delivery_key)
        except Exception:
            logger.exception("failed to release webhook delivery key after enqueue error")
        raise HTTPException(status_code=503, detail="failed to enqueue review") from exc

    return {"msg": "queued"}
