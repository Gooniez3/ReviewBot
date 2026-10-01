import unittest

from review.diff_parser import parse_unified_diff
from review.filters import skip_reason


def parsed_file(path: str = "src/app.py", *, body: str = "+new"):
    diff = (
        f"diff --git a/{path} b/{path}\n"
        f"--- a/{path}\n"
        f"+++ b/{path}\n"
        "@@ -0,0 +1 @@\n"
        f"{body}\n"
    )
    return parse_unified_diff(diff).files[0]


class FilterTests(unittest.TestCase):
    def test_normal_source_is_accepted(self):
        self.assertIsNone(skip_reason(parsed_file()))

    def test_binary_is_rejected(self):
        item = parse_unified_diff(
            "diff --git a/data.bin b/data.bin\nBinary files a/data.bin and b/data.bin differ\n"
        ).files[0]
        self.assertEqual(skip_reason(item), "binary file")

    def test_image_is_rejected(self):
        self.assertIn("non-reviewable", skip_reason(parsed_file("image.png")))

    def test_lock_file_is_rejected(self):
        self.assertEqual(skip_reason(parsed_file("package-lock.json")), "dependency lock file")

    def test_minified_asset_is_rejected(self):
        self.assertEqual(skip_reason(parsed_file("public/app.min.js")), "minified asset")

    def test_vendor_and_generated_paths_are_rejected(self):
        for path in ("vendor/lib.py", "src/generated/model.py", "build/output.js"):
            with self.subTest(path=path):
                self.assertEqual(skip_reason(parsed_file(path)), "vendor or generated output path")

    def test_deleted_only_is_rejected(self):
        item = parse_unified_diff(
            """diff --git a/gone.py b/gone.py
deleted file mode 100644
--- a/gone.py
+++ /dev/null
@@ -1 +0,0 @@
-gone
"""
        ).files[0]
        self.assertEqual(skip_reason(item), "deleted-only file")


if __name__ == "__main__":
    unittest.main()
