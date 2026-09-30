from __future__ import annotations

import ast
import re
import shlex
from dataclasses import dataclass, field

from .models import ChangedFile, DiffLine, DiffLineKind, FileStatus, Hunk, ParsedDiff

HUNK_HEADER = re.compile(
    r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(?:.*)$"
)


@dataclass
class _HunkBuilder:
    header: str
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    old_line: int
    new_line: int
    lines: list[DiffLine] = field(default_factory=list)
    old_seen: int = 0
    new_seen: int = 0

    def add(self, raw_line: str) -> bool:
        if raw_line.startswith("\\ No newline at end of file"):
            return True
        if not raw_line or raw_line[0] not in {" ", "+", "-"}:
            return False

        prefix, content = raw_line[0], raw_line[1:]
        if prefix == " ":
            self.lines.append(
                DiffLine(
                    kind=DiffLineKind.CONTEXT,
                    content=content,
                    old_line=self.old_line,
                    new_line=self.new_line,
                )
            )
            self.old_line += 1
            self.new_line += 1
            self.old_seen += 1
            self.new_seen += 1
        elif prefix == "+":
            self.lines.append(
                DiffLine(
                    kind=DiffLineKind.ADDITION,
                    content=content,
                    new_line=self.new_line,
                )
            )
            self.new_line += 1
            self.new_seen += 1
        else:
            self.lines.append(
                DiffLine(
                    kind=DiffLineKind.DELETION,
                    content=content,
                    old_line=self.old_line,
                )
            )
            self.old_line += 1
            self.old_seen += 1
        return True

    def build(self) -> tuple[Hunk, str | None]:
        error = None
        if self.old_seen != self.old_count or self.new_seen != self.new_count:
            error = (
                f"truncated or malformed hunk {self.header!r}: expected "
                f"-{self.old_count}/+{self.new_count} lines, saw "
                f"-{self.old_seen}/+{self.new_seen}"
            )
        return (
            Hunk(
                header=self.header,
                old_start=self.old_start,
                old_count=self.old_count,
                new_start=self.new_start,
                new_count=self.new_count,
                lines=tuple(self.lines),
            ),
            error,
        )


@dataclass
class _FileBuilder:
    old_path: str | None
    new_path: str | None
    status: FileStatus = FileStatus.MODIFIED
    is_binary: bool = False
    is_combined: bool = False
    errors: list[str] = field(default_factory=list)
    hunks: list[Hunk] = field(default_factory=list)
    current_hunk: _HunkBuilder | None = None

    def finish_hunk(self) -> None:
        if self.current_hunk is None:
            return
        hunk, error = self.current_hunk.build()
        self.hunks.append(hunk)
        if error:
            self.errors.append(error)
        self.current_hunk = None

    def build(self, fallback_index: int) -> ChangedFile:
        self.finish_hunk()
        if self.status == FileStatus.MODIFIED:
            if self.old_path is None and self.new_path is not None:
                self.status = FileStatus.ADDED
            elif self.new_path is None and self.old_path is not None:
                self.status = FileStatus.DELETED
        path = self.new_path or self.old_path or f"<unknown-file-{fallback_index}>"
        return ChangedFile(
            path=path,
            old_path=self.old_path,
            new_path=self.new_path,
            status=self.status,
            is_binary=self.is_binary,
            is_combined=self.is_combined,
            parse_error="; ".join(self.errors) or None,
            hunks=tuple(self.hunks),
        )


def _decode_path(value: str) -> str | None:
    value = value.strip()
    if value == "/dev/null":
        return None
    if value.startswith('"'):
        try:
            value = ast.literal_eval(value)
        except (SyntaxError, ValueError):
            value = value.strip('"')
    if value.startswith(("a/", "b/")):
        value = value[2:]
    return value


def _paths_from_diff_header(line: str) -> tuple[str | None, str | None]:
    payload = line[len("diff --git ") :]
    try:
        parts = shlex.split(payload, posix=True)
    except ValueError:
        parts = []
    if len(parts) == 2:
        return _decode_path(parts[0]), _decode_path(parts[1])

    split_at = payload.rfind(" b/")
    if split_at != -1:
        return _decode_path(payload[:split_at]), _decode_path(payload[split_at + 1 :])
    return None, None


def parse_unified_diff(diff_text: str) -> ParsedDiff:
    normalized = diff_text.replace("\r\n", "\n").replace("\r", "\n")
    raw_bytes = len(diff_text.encode("utf-8"))
    files: list[ChangedFile] = []
    global_errors: list[str] = []
    current: _FileBuilder | None = None

    def finish_file() -> None:
        nonlocal current
        if current is not None:
            files.append(current.build(len(files) + 1))
            current = None

    # Avoid manufacturing an empty hunk record merely because the diff ends
    # with its customary newline. Meaningful empty additions/deletions are
    # still represented by the literal diff lines "+" and "-".
    for line_number, line in enumerate(normalized.splitlines(), start=1):
        if line.startswith("diff --git "):
            finish_file()
            old_path, new_path = _paths_from_diff_header(line)
            current = _FileBuilder(old_path=old_path, new_path=new_path)
            continue

        if line.startswith(("diff --cc ", "diff --combined ")):
            finish_file()
            path = _decode_path(line.split(" ", 2)[-1])
            current = _FileBuilder(
                old_path=path,
                new_path=path,
                is_combined=True,
                errors=["combined merge diffs are unsupported"],
            )
            continue

        if current is None:
            if line.strip():
                global_errors.append(f"line {line_number}: content outside a file diff")
            continue

        if current.current_hunk is not None:
            if line.startswith("@@ "):
                current.finish_hunk()
            elif line.startswith("@@@"):
                current.finish_hunk()
                current.is_combined = True
                current.errors.append("combined merge diffs are unsupported")
                continue
            elif current.current_hunk.add(line):
                continue
            else:
                current.finish_hunk()
                current.errors.append(
                    f"line {line_number}: unexpected content ended a hunk"
                )

        if line.startswith("@@@"):
            current.is_combined = True
            current.errors.append("combined merge diffs are unsupported")
        elif line.startswith("@@ "):
            match = HUNK_HEADER.match(line)
            if not match:
                current.errors.append(f"line {line_number}: malformed hunk header")
                continue
            old_start, old_count, new_start, new_count = match.groups()
            old_count_value = 1 if old_count is None else int(old_count)
            new_count_value = 1 if new_count is None else int(new_count)
            current.current_hunk = _HunkBuilder(
                header=line,
                old_start=int(old_start),
                old_count=old_count_value,
                new_start=int(new_start),
                new_count=new_count_value,
                old_line=int(old_start),
                new_line=int(new_start),
            )
        elif line.startswith("--- "):
            current.old_path = _decode_path(line[4:])
        elif line.startswith("+++ "):
            current.new_path = _decode_path(line[4:])
        elif line.startswith("new file mode "):
            current.status = FileStatus.ADDED
        elif line.startswith("deleted file mode "):
            current.status = FileStatus.DELETED
        elif line.startswith("rename from "):
            current.old_path = _decode_path(line[len("rename from ") :])
            current.status = FileStatus.RENAMED
        elif line.startswith("rename to "):
            current.new_path = _decode_path(line[len("rename to ") :])
            current.status = FileStatus.RENAMED
        elif line.startswith("Binary files ") or line == "GIT binary patch":
            current.is_binary = True

    finish_file()
    return ParsedDiff(files=tuple(files), errors=tuple(global_errors), raw_bytes=raw_bytes)
