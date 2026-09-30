import hashlib
import hmac
import json
import os
import unittest
from unittest.mock import Mock, patch

os.environ["GITHUB_WEBHOOK_SECRET"] = "test-secret"
os.environ["REDIS_URL"] = "redis://localhost:6379"

from fastapi.testclient import TestClient

import main


class WebhookTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        self.redis = Mock()
        self.queue = Mock()
        self.redis.set.return_value = True
        self.patches = (
            patch.object(main, "redis_conn", self.redis),
            patch.object(main, "queue", self.queue),
        )
        for active_patch in self.patches:
            active_patch.start()

    def tearDown(self):
        for active_patch in reversed(self.patches):
            active_patch.stop()

    @staticmethod
    def _signature(body: bytes) -> str:
        digest = hmac.new(b"test-secret", body, hashlib.sha256).hexdigest()
        return f"sha256={digest}"

    @staticmethod
    def _payload() -> dict:
        return {
            "action": "opened",
            "installation": {"id": 123},
            "repository": {"full_name": "owner/repo"},
            "pull_request": {
                "number": 42,
                "head": {"sha": "abc123"},
            },
        }

    def _post(self, body: bytes, *, signature: str | None = None, delivery="delivery-1"):
        headers = {
            "X-GitHub-Event": "pull_request",
            "X-GitHub-Delivery": delivery,
            "X-Hub-Signature-256": signature or self._signature(body),
            "Content-Type": "application/json",
        }
        return self.client.post("/webhook", content=body, headers=headers)

    def test_valid_webhook_signature(self):
        body = json.dumps(self._payload()).encode()

        response = self._post(body)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"msg": "queued"})

    def test_invalid_webhook_signature(self):
        body = json.dumps(self._payload()).encode()

        response = self._post(body, signature="sha256=invalid")

        self.assertEqual(response.status_code, 401)
        self.queue.enqueue.assert_not_called()

    def test_duplicate_delivery(self):
        self.redis.set.return_value = False
        body = json.dumps(self._payload()).encode()

        response = self._post(body)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"msg": "duplicate delivery"})
        self.queue.enqueue.assert_not_called()

    def test_successful_enqueue(self):
        body = json.dumps(self._payload()).encode()

        response = self._post(body, delivery="delivery-2")

        self.assertEqual(response.status_code, 200)
        self.redis.set.assert_called_once_with(
            "delivery:delivery-2", 1, nx=True, ex=60 * 60 * 24
        )
        self.queue.enqueue.assert_called_once_with(
            "worker.review_pull_request",
            {
                "installation_id": 123,
                "repo_full_name": "owner/repo",
                "pr_number": 42,
                "head_sha": "abc123",
            },
            job_timeout=300,
        )

    def test_malformed_json_returns_400(self):
        body = b"{not-json"

        response = self._post(body)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"detail": "invalid JSON payload"})
        self.redis.set.assert_not_called()
        self.queue.enqueue.assert_not_called()

    def test_missing_required_fields_returns_400(self):
        body = json.dumps({"action": "opened"}).encode()

        response = self._post(body)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json(), {"detail": "missing required pull request fields"}
        )
        self.redis.set.assert_not_called()
        self.queue.enqueue.assert_not_called()

    def test_missing_delivery_id_returns_400(self):
        body = json.dumps(self._payload()).encode()

        response = self._post(body, delivery="")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json(), {"detail": "missing X-GitHub-Delivery header"}
        )
        self.redis.set.assert_not_called()
        self.queue.enqueue.assert_not_called()

    def test_enqueue_failure_releases_delivery_key(self):
        self.queue.enqueue.side_effect = RuntimeError("Redis unavailable")
        body = json.dumps(self._payload()).encode()

        response = self._post(body, delivery="delivery-3")

        self.assertEqual(response.status_code, 503)
        self.redis.delete.assert_called_once_with("delivery:delivery-3")


if __name__ == "__main__":
    unittest.main()
