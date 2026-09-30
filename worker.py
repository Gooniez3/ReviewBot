import os
import time

import httpx
import jwt  # PyJWT

from review import prepare_review

APP_ID = os.environ["GITHUB_APP_ID"]
PRIVATE_KEY = os.environ["GITHUB_PRIVATE_KEY"].replace("\\n", "\n")
API = "https://api.github.com"
GITHUB_API_VERSION = "2026-03-10"


def _github_headers(token: str, accept: str = "application/vnd.github+json") -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": accept,
        "X-GitHub-Api-Version": GITHUB_API_VERSION,
    }


def _app_jwt() -> str:
    """Short-lived JWT that proves we are the GitHub App."""
    now = int(time.time())
    payload = {"iat": now - 60, "exp": now + 9 * 60, "iss": APP_ID}
    return jwt.encode(payload, PRIVATE_KEY, algorithm="RS256")


def _installation_token(installation_id: int) -> str:
    """Exchange the app JWT for a token scoped to the repo owner's installation."""
    r = httpx.post(
        f"{API}/app/installations/{installation_id}/access_tokens",
        headers=_github_headers(_app_jwt()),
        timeout=15,
    )
    r.raise_for_status()
    return r.json()["token"]


def _fetch_diff(token: str, repo: str, pr_number: int) -> str:
    r = httpx.get(
        f"{API}/repos/{repo}/pulls/{pr_number}",
        headers=_github_headers(token, "application/vnd.github.diff"),
        timeout=30,
    )
    r.raise_for_status()
    return r.text


def _post_summary(token: str, repo: str, pr_number: int, body: str) -> None:
    r = httpx.post(
        f"{API}/repos/{repo}/issues/{pr_number}/comments",
        headers=_github_headers(token),
        json={"body": body},
        timeout=15,
    )
    r.raise_for_status()


def review_pull_request(job: dict) -> None:
    token = _installation_token(job["installation_id"])
    diff = _fetch_diff(token, job["repo_full_name"], job["pr_number"])
    preparation = prepare_review(diff)

    summary = [
        "ReviewBot analyzed this PR:",
        f"- {len(preparation.reviewable_files)} reviewable files",
        f"- {len(preparation.skipped_files)} skipped files",
        f"- {preparation.hunk_count} hunks",
        f"- {preparation.added_reviewable_lines} added reviewable lines",
    ]
    if preparation.budget_exhausted:
        summary.append("- A review preparation budget was reached")
    summary.extend(("", "AI review is not enabled yet."))
    _post_summary(
        token,
        job["repo_full_name"],
        job["pr_number"],
        "\n".join(summary),
    )
