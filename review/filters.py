from __future__ import annotations

from pathlib import PurePosixPath

from .models import ChangedFile, FileStatus, SkippedFile

NON_REVIEWABLE_SUFFIXES = {
    ".7z",
    ".a",
    ".avi",
    ".bin",
    ".bmp",
    ".bz2",
    ".class",
    ".dll",
    ".dmg",
    ".doc",
    ".docx",
    ".eot",
    ".exe",
    ".gif",
    ".gz",
    ".ico",
    ".jar",
    ".jpeg",
    ".jpg",
    ".mov",
    ".mp3",
    ".mp4",
    ".msi",
    ".o",
    ".otf",
    ".pdf",
    ".png",
    ".rar",
    ".so",
    ".tar",
    ".tgz",
    ".ttf",
    ".webm",
    ".webp",
    ".woff",
    ".woff2",
    ".xls",
    ".xlsx",
    ".xz",
    ".zip",
}

LOCK_FILES = {
    "bun.lock",
    "bun.lockb",
    "cargo.lock",
    "composer.lock",
    "gemfile.lock",
    "go.sum",
    "package-lock.json",
    "packages.lock.json",
    "pipfile.lock",
    "pnpm-lock.yaml",
    "poetry.lock",
    "npm-shrinkwrap.json",
    "uv.lock",
    "yarn.lock",
}

GENERATED_PATH_PARTS = {
    ".next",
    "build",
    "coverage",
    "dist",
    "generated",
    "node_modules",
    "third_party",
    "vendor",
}

GENERATED_MARKERS = ("@generated", "code generated", "do not edit")


def skip_reason(changed_file: ChangedFile) -> str | None:
    path = PurePosixPath(changed_file.path)
    lowercase_path = changed_file.path.lower()
    lowercase_parts = {part.lower() for part in path.parts}

    if changed_file.is_combined:
        return "combined merge diff is unsupported"
    if changed_file.parse_error:
        return f"malformed diff: {changed_file.parse_error}"
    if changed_file.is_binary:
        return "binary file"
    if changed_file.status == FileStatus.DELETED:
        return "deleted-only file"
    if path.suffix.lower() in NON_REVIEWABLE_SUFFIXES:
        return "non-reviewable binary or document type"
    if path.name.lower() in LOCK_FILES:
        return "dependency lock file"
    if lowercase_path.endswith((".min.js", ".min.css", ".min.map")):
        return "minified asset"
    if lowercase_parts & GENERATED_PATH_PARTS:
        return "vendor or generated output path"
    if not changed_file.hunks or changed_file.additions == 0:
        return "no reviewable added patch lines"

    sample = "\n".join(
        line.content.lower()
        for hunk in changed_file.hunks[:2]
        for line in hunk.lines[:20]
    )
    if any(marker in sample for marker in GENERATED_MARKERS):
        return "generated file marker"
    return None


def partition_files(
    files: tuple[ChangedFile, ...],
) -> tuple[list[ChangedFile], list[SkippedFile]]:
    reviewable: list[ChangedFile] = []
    skipped: list[SkippedFile] = []
    for changed_file in files:
        reason = skip_reason(changed_file)
        if reason:
            skipped.append(SkippedFile(path=changed_file.path, reason=reason))
        else:
            reviewable.append(changed_file)
    return reviewable, skipped
