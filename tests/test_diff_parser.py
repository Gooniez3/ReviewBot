import unittest

from review.diff_parser import parse_unified_diff
from review.models import DiffLineKind, FileStatus


BASIC_DIFF = """diff --git a/app.py b/app.py
index 1111111..2222222 100644
--- a/app.py
+++ b/app.py
@@ -1,3 +1,3 @@
 one
-old
+new
 three
"""


class DiffParserTests(unittest.TestCase):
    def test_basic_modification_and_exact_line_mapping(self):
        parsed = parse_unified_diff(BASIC_DIFF)

        self.assertEqual(parsed.errors, ())
        changed_file = parsed.files[0]
        self.assertEqual(changed_file.path, "app.py")
        self.assertEqual(changed_file.status, FileStatus.MODIFIED)
        self.assertIsNone(changed_file.parse_error)
        coordinates = [
            (line.kind, line.old_line, line.new_line, line.content)
            for line in changed_file.hunks[0].lines
        ]
        self.assertEqual(
            coordinates,
            [
                (DiffLineKind.CONTEXT, 1, 1, "one"),
                (DiffLineKind.DELETION, 2, None, "old"),
                (DiffLineKind.ADDITION, None, 2, "new"),
                (DiffLineKind.CONTEXT, 3, 3, "three"),
            ],
        )

    def test_multiple_files_and_multiple_hunks(self):
        second = """diff --git a/lib.py b/lib.py
--- a/lib.py
+++ b/lib.py
@@ -1 +1 @@
-a
+b
@@ -10 +10 @@
-c
+d
"""
        parsed = parse_unified_diff(BASIC_DIFF + second)

        self.assertEqual([item.path for item in parsed.files], ["app.py", "lib.py"])
        self.assertEqual(len(parsed.files[1].hunks), 2)
        self.assertEqual(parsed.files[1].hunks[1].lines[1].new_line, 10)

    def test_new_file_and_zero_length_range(self):
        parsed = parse_unified_diff(
            """diff --git a/new.py b/new.py
new file mode 100644
--- /dev/null
+++ b/new.py
@@ -0,0 +1,2 @@
+one
+two
"""
        )

        changed_file = parsed.files[0]
        self.assertEqual(changed_file.status, FileStatus.ADDED)
        self.assertIsNone(changed_file.old_path)
        self.assertEqual(
            [(line.old_line, line.new_line) for line in changed_file.hunks[0].lines],
            [(None, 1), (None, 2)],
        )

    def test_deleted_file(self):
        parsed = parse_unified_diff(
            """diff --git a/gone.py b/gone.py
deleted file mode 100644
--- a/gone.py
+++ /dev/null
@@ -4,2 +0,0 @@
-one
-two
"""
        )

        changed_file = parsed.files[0]
        self.assertEqual(changed_file.status, FileStatus.DELETED)
        self.assertIsNone(changed_file.new_path)
        self.assertEqual(
            [(line.old_line, line.new_line) for line in changed_file.hunks[0].lines],
            [(4, None), (5, None)],
        )

    def test_rename_with_changes_and_rename_only(self):
        changed = """diff --git a/old.py b/new.py
similarity index 80%
rename from old.py
rename to new.py
--- a/old.py
+++ b/new.py
@@ -1 +1 @@
-old
+new
"""
        rename_only = """diff --git a/a.txt b/b.txt
similarity index 100%
rename from a.txt
rename to b.txt
"""
        parsed = parse_unified_diff(changed + rename_only)

        self.assertEqual(parsed.files[0].status, FileStatus.RENAMED)
        self.assertEqual(parsed.files[0].old_path, "old.py")
        self.assertEqual(parsed.files[0].path, "new.py")
        self.assertEqual(parsed.files[1].status, FileStatus.RENAMED)
        self.assertEqual(parsed.files[1].hunks, ())

    def test_path_containing_spaces(self):
        parsed = parse_unified_diff(
            """diff --git a/folder/file name.py b/folder/file name.py
--- a/folder/file name.py
+++ b/folder/file name.py
@@ -1 +1 @@
-old
+new
"""
        )
        self.assertEqual(parsed.files[0].path, "folder/file name.py")

    def test_omitted_hunk_counts(self):
        parsed = parse_unified_diff(
            """diff --git a/a.py b/a.py
--- a/a.py
+++ b/a.py
@@ -4 +7 @@
-old
+new
"""
        )
        hunk = parsed.files[0].hunks[0]
        self.assertEqual((hunk.old_count, hunk.new_count), (1, 1))
        self.assertEqual((hunk.lines[0].old_line, hunk.lines[1].new_line), (4, 7))

    def test_no_newline_marker_and_content_beginning_with_diff_markers(self):
        parsed = parse_unified_diff(
            """diff --git a/a.txt b/a.txt
--- a/a.txt
+++ b/a.txt
@@ -1 +1 @@
--old starts with minus
\\ No newline at end of file
++new starts with plus
\\ No newline at end of file
"""
        )
        lines = parsed.files[0].hunks[0].lines
        self.assertEqual(lines[0].content, "-old starts with minus")
        self.assertEqual(lines[1].content, "+new starts with plus")
        self.assertIsNone(parsed.files[0].parse_error)

    def test_binary_diff(self):
        parsed = parse_unified_diff(
            """diff --git a/logo.png b/logo.png
index 1111111..2222222 100644
Binary files a/logo.png and b/logo.png differ
"""
        )
        self.assertTrue(parsed.files[0].is_binary)

    def test_crlf_input(self):
        parsed = parse_unified_diff(BASIC_DIFF.replace("\n", "\r\n"))
        self.assertIsNone(parsed.files[0].parse_error)
        self.assertEqual(parsed.files[0].additions, 1)

    def test_truncated_hunk_is_explicitly_malformed(self):
        parsed = parse_unified_diff(
            """diff --git a/a.py b/a.py
--- a/a.py
+++ b/a.py
@@ -1,2 +1,2 @@
-old
+new
"""
        )
        self.assertIn("truncated or malformed hunk", parsed.files[0].parse_error)

    def test_diff_content_whitespace_is_preserved(self):
        parsed = parse_unified_diff(
            "diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n"
            "@@ -0,0 +1 @@\n+  indented  \n"
        )
        self.assertEqual(parsed.files[0].hunks[0].lines[0].content, "  indented  ")


if __name__ == "__main__":
    unittest.main()
