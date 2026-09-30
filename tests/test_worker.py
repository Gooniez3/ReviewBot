import os
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("GITHUB_APP_ID", "123456")
os.environ.setdefault("GITHUB_PRIVATE_KEY", "test-key")

import worker


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
        self.assertIn("AI review is not enabled yet.", body)

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
