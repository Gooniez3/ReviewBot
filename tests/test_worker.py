import os
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("GITHUB_APP_ID", "123456")
os.environ.setdefault("GITHUB_PRIVATE_KEY", "test-key")

import worker
from review.providers import FakeReviewProvider


DIFF = """diff --git a/app.py b/app.py
--- a/app.py
+++ b/app.py
@@ -1 +1 @@
-old
+new
diff --git a/logo.png b/logo.png
Binary files a/logo.png and b/logo.png differ
"""


class WorkerTests(unittest.TestCase):
    def test_review_job_preserves_flow_and_posts_deterministic_summary(self):
        job = {
            "installation_id": 9,
            "repo_full_name": "owner/repo",
            "pr_number": 7,
            "head_sha": "abc",
        }
        with (
            patch.object(worker, "_installation_token", return_value="token") as token,
            patch.object(worker, "_fetch_diff", return_value=DIFF) as fetch,
            patch.object(worker, "_post_summary") as post,
        ):
            worker.review_pull_request(job)

        token.assert_called_once_with(9)
        fetch.assert_called_once_with("token", "owner/repo", 7)
        body = post.call_args.args[3]
        self.assertIn("- 1 reviewable files", body)
        self.assertIn("- 1 skipped files", body)
        self.assertIn("- 1 hunks", body)
        self.assertIn("- 1 added reviewable lines", body)
        self.assertIn("- 1 candidate findings", body)
        self.assertIn("- 1 accepted findings", body)
        self.assertIn("- 0 rejected findings", body)
        self.assertIn("AI findings are currently running in dry-run mode.", body)
        self.assertIn("No inline review comments were posted.", body)
        self.assertNotIn("Dry-run fixture: synthetic finding", body)

    def test_provider_failure_still_posts_safe_dry_run_summary(self):
        class RaisingProvider:
            name = "raising-provider"
            model_name = None

            def review(self, review_input):
                raise RuntimeError("secret response text")

        job = {
            "installation_id": 9,
            "repo_full_name": "owner/repo",
            "pr_number": 7,
            "head_sha": "abc",
        }
        with (
            patch.object(worker, "_installation_token", return_value="token"),
            patch.object(worker, "_fetch_diff", return_value=DIFF),
            patch.object(worker, "_review_provider", return_value=RaisingProvider()),
            patch.object(worker, "_post_summary") as post,
        ):
            worker.review_pull_request(job)

        body = post.call_args.args[3]
        self.assertIn("- 0 candidate findings", body)
        self.assertIn("- 0 accepted findings", body)
        self.assertIn("Provider status: unavailable", body)
        self.assertNotIn("secret response text", body)

    def test_worker_can_use_configured_fake_provider(self):
        job = {
            "installation_id": 9,
            "repo_full_name": "owner/repo",
            "pr_number": 7,
            "head_sha": "abc",
        }
        with (
            patch.object(worker, "_installation_token", return_value="token"),
            patch.object(worker, "_fetch_diff", return_value=DIFF),
            patch.object(
                worker,
                "_review_provider",
                return_value=FakeReviewProvider(candidates=()),
            ),
            patch.object(worker, "_post_summary") as post,
        ):
            worker.review_pull_request(job)

        self.assertIn("- 0 candidate findings", post.call_args.args[3])

    def test_fetch_diff_keeps_api_version_and_diff_accept_headers(self):
        response = Mock(text=DIFF)
        with patch.object(worker.httpx, "get", return_value=response) as get:
            result = worker._fetch_diff("token", "owner/repo", 7)

        self.assertEqual(result, DIFF)
        response.raise_for_status.assert_called_once_with()
        headers = get.call_args.kwargs["headers"]
        self.assertEqual(headers["Accept"], "application/vnd.github.diff")
        self.assertEqual(headers["X-GitHub-Api-Version"], worker.GITHUB_API_VERSION)

    def test_installation_token_keeps_app_jwt_exchange(self):
        response = Mock()
        response.json.return_value = {"token": "installation-token"}
        with (
            patch.object(worker, "_app_jwt", return_value="app-jwt"),
            patch.object(worker.httpx, "post", return_value=response) as post,
        ):
            result = worker._installation_token(9)

        self.assertEqual(result, "installation-token")
        response.raise_for_status.assert_called_once_with()
        self.assertEqual(post.call_args.kwargs["headers"]["Authorization"], "Bearer app-jwt")


if __name__ == "__main__":
    unittest.main()
