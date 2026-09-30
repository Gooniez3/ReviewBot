import unittest

from review.models import BudgetPolicy
from review.pipeline import prepare_review


def file_diff(path: str, old: str = "old", new: str = "new") -> str:
    return (
        f"diff --git a/{path} b/{path}\n"
        f"--- a/{path}\n"
        f"+++ b/{path}\n"
        "@@ -1 +1 @@\n"
        f"-{old}\n"
        f"+{new}\n"
    )


class PipelineTests(unittest.TestCase):
    def test_reviewable_and_skipped_counts_preserve_order(self):
        preparation = prepare_review(
            file_diff("z.py") + file_diff("image.png") + file_diff("a.py")
        )

        self.assertEqual(
            [item.path for item in preparation.parsed_diff.files],
            ["z.py", "image.png", "a.py"],
        )
        self.assertEqual(
            [item.path for item in preparation.reviewable_files], ["z.py", "a.py"]
        )
        self.assertEqual([item.path for item in preparation.skipped_files], ["image.png"])
        self.assertEqual(preparation.hunk_count, 2)
        self.assertEqual(preparation.added_reviewable_lines, 2)

    def test_chunks_are_deterministic_and_do_not_split_hunks(self):
        diff = file_diff("a.py") + file_diff("b.py")
        first = prepare_review(diff)
        second = prepare_review(diff)

        self.assertEqual(first, second)
        self.assertEqual([chunk.path for chunk in first.chunks], ["a.py", "b.py"])
        self.assertEqual(first.chunks[0].hunk_indexes, (0,))
        self.assertTrue(first.chunks[0].text.startswith("@@ -1 +1 @@"))

    def test_raw_byte_budget_is_explicit(self):
        preparation = prepare_review(
            file_diff("a.py"), BudgetPolicy(max_raw_diff_bytes=10)
        )
        self.assertTrue(preparation.budget_exhausted)
        self.assertEqual(preparation.reviewable_files, ())
        self.assertIn("raw diff", preparation.budget_reasons[0])

    def test_file_budget_is_explicit_and_deterministic(self):
        preparation = prepare_review(
            file_diff("a.py") + file_diff("b.py"), BudgetPolicy(max_files=1)
        )
        self.assertEqual([item.path for item in preparation.reviewable_files], ["a.py"])
        self.assertEqual(preparation.skipped_files[0].path, "b.py")
        self.assertTrue(preparation.budget_exhausted)

    def test_changed_line_and_total_line_budgets(self):
        per_file = prepare_review(
            file_diff("a.py"), BudgetPolicy(max_changed_lines_per_file=1)
        )
        total = prepare_review(
            file_diff("a.py") + file_diff("b.py"),
            BudgetPolicy(max_total_reviewable_lines=2),
        )
        self.assertIn("changed-line", per_file.skipped_files[0].reason)
        self.assertEqual([item.path for item in total.reviewable_files], ["a.py"])
        self.assertIn("total reviewable-line", total.skipped_files[0].reason)

    def test_chunk_character_and_chunk_count_budgets(self):
        too_large = prepare_review(
            file_diff("a.py"), BudgetPolicy(max_chunk_chars=5)
        )
        too_many = prepare_review(
            file_diff("a.py") + file_diff("b.py"), BudgetPolicy(max_chunks=1)
        )
        self.assertIn("hunk exceeds", too_large.skipped_files[0].reason)
        self.assertEqual([item.path for item in too_many.reviewable_files], ["a.py"])
        self.assertIn("chunk limit", too_many.skipped_files[0].reason)

    def test_malformed_input_is_safely_skipped(self):
        malformed = """diff --git a/a.py b/a.py
--- a/a.py
+++ b/a.py
@@ -1,2 +1,2 @@
-old
+new
"""
        preparation = prepare_review(malformed)
        self.assertEqual(preparation.reviewable_files, ())
        self.assertIn("malformed diff", preparation.skipped_files[0].reason)


if __name__ == "__main__":
    unittest.main()
