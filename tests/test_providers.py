import unittest

from review.models import (
    FindingCandidate,
    FindingCategory,
    ProviderReviewInput,
    Severity,
)
from review.pipeline import prepare_review
from review.providers import FakeReviewProvider, ReviewProvider


DIFF = """diff --git a/app.py b/app.py
--- a/app.py
+++ b/app.py
@@ -1 +1 @@
-old
+new
"""


def provider_input() -> ProviderReviewInput:
    preparation = prepare_review(DIFF)
    return ProviderReviewInput(
        reviewable_files=preparation.reviewable_files,
        chunks=preparation.chunks,
    )


def configured_candidate() -> FindingCandidate:
    return FindingCandidate(
        path="missing.py",
        start_line=999,
        end_line=999,
        severity=Severity.LOW,
        category=FindingCategory.MAINTAINABILITY,
        title="Configured fake candidate",
        explanation="Schema-valid test data for deterministic validation.",
        suggested_fix=None,
        confidence=0.4,
    )


class FakeReviewProviderTests(unittest.TestCase):
    def test_fake_provider_satisfies_contract(self):
        self.assertIsInstance(FakeReviewProvider(), ReviewProvider)

    def test_default_result_is_deterministic_and_clearly_synthetic(self):
        provider = FakeReviewProvider()
        review_input = provider_input()

        first = provider.review(review_input)
        second = provider.review(review_input)

        self.assertEqual(first, second)
        self.assertEqual(len(first.candidates), 1)
        finding = first.candidates[0]
        self.assertEqual((finding.path, finding.start_line), ("app.py", 1))
        self.assertIn("Dry-run fixture", finding.title)
        self.assertIn("not a detected defect", finding.explanation)

    def test_configured_candidates_are_returned_unchanged(self):
        candidate = configured_candidate()
        provider = FakeReviewProvider(candidates=(candidate,))

        result = provider.review(provider_input())

        self.assertEqual(result.candidates, (candidate,))

    def test_empty_input_is_safe(self):
        result = FakeReviewProvider().review(ProviderReviewInput())
        self.assertEqual(result.candidates, ())


if __name__ == "__main__":
    unittest.main()
