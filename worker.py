import os
import time

import httpx
import jwt  # PyJWT

APP_ID = os.environ["GITHUB_APP_ID"]
PRIVATE_KEY = os.environ["GITHUB_PRIVATE_KEY"].replace("\\n", "\n")
API = "https://api.github.com"


def _app_jwt() -> str:
    """Short-lived JWT that proves we are the GitHub App."""
    now = int(time.time())
    payload = {"iat": now - 60, "exp": now + 9 * 60, "iss": APP_ID}
    return jwt.encode(payload, PRIVATE_KEY, algorithm="RS256")


def _installation_token(installation_id: int) -> str:
    """Exchange the app JWT for a token scoped to the repo owner's installation."""
    r = httpx.post(
        f"{API}/app/installations/{installation_id}/access_tokens",
        headers={
            "Authorization": f"Bearer {_app_jwt()}",
            "Accept": "application/vnd.github+json",
        },
        timeout=15,
    )
    r.raise_for_status()
    return r.json()["token"]


def _fetch_diff(token: str, repo: str, pr_number: int) -> str:
    r = httpx.get(
        f"{API}/repos/{repo}/pulls/{pr_number}",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github.v3.diff",
        },
        timeout=30,
    )
    r.raise_for_status()
    return r.text


def _post_summary(token: str, repo: str, pr_number: int, body: str) -> None:
    r = httpx.post(
        f"{API}/repos/{repo}/issues/{pr_number}/comments",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
        },
        json={"body": body},
        timeout=15,
    )
    r.raise_for_status()


def review_pull_request(job: dict) -> None:
    token = _installation_token(job["installation_id"])
    diff = _fetch_diff(token, job["repo_full_name"], job["pr_number"])

    # TODO (week 2): chunk the diff by file, call the LLM agent, filter low-confidence
    # comments, and post inline review comments instead of this placeholder.
    lines_changed = sum(
        1 for line in diff.splitlines() if line.startswith(("+", "-"))
        and not line.startswith(("+++", "---"))
    )
    _post_summary(
        token,
        job["repo_full_name"],
        job["pr_number"],
        f"reviewbot received this PR ({lines_changed} changed lines). Review coming soon.",
    )
