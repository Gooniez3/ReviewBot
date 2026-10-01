import unittest

from review.models import (
    FindingCandidate,
    FindingCategory,
    ProviderPolicy,
    ProviderResult,
    Severity,
)
from review.orchestration import run_dry_review
from review.pipeline import prepare_review
from review.providers import FakeReviewProvider


DIFF = """diff --git a/app.py b/app.py
--- a/app.py
+++ b/app.py
@@ -10,3 +10,3 @@
 context
-deleted
+added
 tail
@@ -20 +19,0 @@
-deleted only
"""


def candidate(**overrides) -> FindingCandidate:
    values = {
        "path": "app.py",
        "start_line": 11,
        "end_line": 11,
        "severity": Severity.HIGH,
        "category": FindingCategory.CORRECTNESS,
        "title": "Incorrect value",
        "explanation": "This value produces an incorrect result.",
        "suggested_fix": None,
        "confidence": 0.8,
    }
    values.update(overrides)
    return FindingCandidate(**values)


class RaisingProvider:
    name = "raising-test-provider"
    model_name = None

    def review(self, review_input):
        raise RuntimeError("sensitive provider text must not escape")


class MalformedProvider:
    name = "malformed-test-provider"
    model_name = None

    def review(self, review_input):
        return {"candidates": [{"untrusted": "output"}]}


class OrchestrationTests(unittest.TestCase):
    def setUp(self):
        self.preparation = prepare_review(DIFF)

    def run_candidates(self, *findings, policy=None):
        return run_dry_review(
            self.preparation,
            FakeReviewProvider(candidates=tuple(findings)),
            policy or ProviderPolicy(),
        )

    def test_valid_candidate_is_accepted(self):
        finding = candidate()
        result = self.run_candidates(finding)
        self.assertEqual(result.validation.accepted, (finding,))
        self.assertEqual(result.validation.rejected, ())

    def test_unknown_path_is_rejected(self):
        result = self.run_candidates(candidate(path="other.py"))
        self.assertIn("not present", result.validation.rejected[0].reason)

    def test_nonexistent_line_is_rejected(self):
        result = self.run_candidates(candidate(start_line=999, end_line=999))
        self.assertIn("does not exist", result.validation.rejected[0].reason)

    def test_context_line_is_rejected(self):
        result = self.run_candidates(candidate(start_line=10, end_line=10))
        self.assertEqual(result.validation.rejected[0].reason, "line is not an addition")

    def test_deletion_line_is_rejected(self):
        result = self.run_candidates(candidate(start_line=20, end_line=20))
        self.assertIn("deletion", result.validation.rejected[0].reason)

    def test_duplicate_candidates_preserve_existing_validation_behavior(self):
        lower = candidate(confidence=0.3)
        higher = candidate(confidence=0.9)
        result = self.run_candidates(lower, higher)
        self.assertEqual(result.validation.accepted, (higher,))
        self.assertEqual(result.validation.rejected[0].candidate, lower)
        self.assertIn("duplicate", result.validation.rejected[0].reason)

    def test_candidate_and_accepted_caps_account_for_every_candidate(self):
        findings = tuple(
            candidate(title=f"Finding {index:02d}", explanation=f"Explanation {index}")
            for index in range(6)
        )
        policy = ProviderPolicy(max_candidates=4, max_accepted_findings=2)

        result = self.run_candidates(*findings, policy=policy)

        self.assertEqual(len(result.candidates), 6)
        self.assertEqual(len(result.validation.accepted), 2)
        self.assertEqual(len(result.validation.rejected), 4)
        reasons = [item.reason for item in result.validation.rejected]
        self.assertEqual(reasons.count("accepted finding cap exceeded"), 2)
        self.assertEqual(reasons.count("provider candidate cap exceeded"), 2)
        self.assertEqual(
            len(result.candidates),
            len(result.validation.accepted) + len(result.validation.rejected),
        )

    def test_default_caps_are_50_candidates_and_20_accepted(self):
        findings = tuple(
            candidate(title=f"Finding {index:02d}", explanation=f"Explanation {index}")
            for index in range(52)
        )
        result = self.run_candidates(*findings)
        self.assertEqual(len(result.validation.accepted), 20)
        self.assertEqual(len(result.validation.rejected), 32)

    def test_provider_failure_fails_open_without_exception_text(self):
        result = run_dry_review(self.preparation, RaisingProvider())
        self.assertFalse(result.provider_available)
        self.assertEqual(result.candidates, ())
        self.assertEqual(result.validation.accepted, ())
        self.assertEqual(result.validation.rejected, ())
        self.assertEqual(result.provider_errors, ("provider_exception:RuntimeError",))
        self.assertNotIn("sensitive", " ".join(result.provider_errors))

    def test_malformed_provider_result_fails_safely(self):
        result = run_dry_review(self.preparation, MalformedProvider())
        self.assertFalse(result.provider_available)
        self.assertEqual(result.candidates, ())
        self.assertEqual(result.provider_errors, ("malformed_provider_result",))

    def test_filtered_file_cannot_be_reintroduced_by_provider(self):
        diff = DIFF + """diff --git a/logo.png b/logo.png
Binary files a/logo.png and b/logo.png differ
"""
        preparation = prepare_review(diff)
        finding = candidate(path="logo.png", start_line=1, end_line=1)
        result = run_dry_review(
            preparation, FakeReviewProvider(candidates=(finding,))
        )
        self.assertIn("not reviewable", result.validation.rejected[0].reason)

    def test_empty_preparation_is_safe(self):
        preparation = prepare_review("")
        result = run_dry_review(preparation, FakeReviewProvider())
        self.assertTrue(result.provider_available)
        self.assertEqual(result.candidates, ())
        self.assertEqual(result.validation.accepted, ())


if __name__ == "__main__":
    unittest.main()
