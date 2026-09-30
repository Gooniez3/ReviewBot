import unittest

from pydantic import ValidationError

from review.diff_parser import parse_unified_diff
from review.models import FindingCandidate, FindingCategory, Severity
from review.validation import validate_findings


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
        "suggested_fix": "Use the validated value.",
        "confidence": 0.8,
    }
    values.update(overrides)
    return FindingCandidate(**values)


class FindingValidationTests(unittest.TestCase):
    def setUp(self):
        self.parsed = parse_unified_diff(DIFF)

    def test_valid_finding_on_addition(self):
        result = validate_findings([candidate()], self.parsed)
        self.assertEqual(result.accepted, (candidate(),))
        self.assertEqual(result.rejected, ())

    def test_unknown_path(self):
        result = validate_findings([candidate(path="other.py")], self.parsed)
        self.assertIn("not present", result.rejected[0].reason)

    def test_deletion_target(self):
        result = validate_findings(
            [candidate(start_line=20, end_line=20)], self.parsed
        )
        self.assertIn("deletion", result.rejected[0].reason)

    def test_context_target(self):
        result = validate_findings(
            [candidate(start_line=10, end_line=10)], self.parsed
        )
        self.assertEqual(result.rejected[0].reason, "line is not an addition")

    def test_nonexistent_line(self):
        result = validate_findings(
            [candidate(start_line=999, end_line=999)], self.parsed
        )
        self.assertIn("does not exist", result.rejected[0].reason)

    def test_reversed_and_multiline_targets(self):
        for start, end in ((12, 11), (10, 11)):
            with self.subTest(start=start, end=end):
                result = validate_findings(
                    [candidate(start_line=start, end_line=end)], self.parsed
                )
                self.assertIn("single-line", result.rejected[0].reason)

    def test_invalid_confidence_is_rejected_by_schema(self):
        with self.assertRaises(ValidationError):
            candidate(confidence=1.01)

    def test_duplicate_keeps_higher_confidence(self):
        lower = candidate(confidence=0.4)
        higher = candidate(confidence=0.9)
        result = validate_findings([lower, higher], self.parsed)
        self.assertEqual(result.accepted, (higher,))
        self.assertEqual(result.rejected[0].candidate, lower)
        self.assertIn("duplicate", result.rejected[0].reason)

    def test_malicious_paths_are_rejected_by_schema(self):
        for path in ("../secret", "/etc/passwd", "C:/secret", "bad\\path", "bad\x00path"):
            with self.subTest(path=path), self.assertRaises(ValidationError):
                candidate(path=path)

    def test_excessive_text_is_rejected_by_schema(self):
        with self.assertRaises(ValidationError):
            candidate(explanation="x" * 2001)


if __name__ == "__main__":
    unittest.main()
