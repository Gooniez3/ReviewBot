from __future__ import annotations

import re

from .models import (
    DiffLineKind,
    FindingCandidate,
    FindingValidation,
    ParsedDiff,
    RejectedFinding,
    Severity,
)

WHITESPACE = re.compile(r"\s+")
SEVERITY_ORDER = {
    Severity.CRITICAL: 0,
    Severity.HIGH: 1,
    Severity.MEDIUM: 2,
    Severity.LOW: 3,
}


def _duplicate_key(candidate: FindingCandidate) -> tuple[object, ...]:
    return (
        candidate.path,
        candidate.start_line,
        candidate.end_line,
        candidate.severity,
        candidate.category,
        WHITESPACE.sub(" ", candidate.title).casefold(),
        WHITESPACE.sub(" ", candidate.explanation).casefold(),
        candidate.suggested_fix,
    )


def validate_findings(
    candidates: list[FindingCandidate] | tuple[FindingCandidate, ...],
    parsed_diff: ParsedDiff,
    *,
    reviewable_paths: set[str] | None = None,
) -> FindingValidation:
    files_by_path = {changed_file.path: changed_file for changed_file in parsed_diff.files}
    accepted_by_key: dict[tuple[object, ...], FindingCandidate] = {}
    rejected: list[RejectedFinding] = []

    for candidate in candidates:
        changed_file = files_by_path.get(candidate.path)
        reason = None
        if changed_file is None:
            reason = "path is not present in the parsed diff"
        elif reviewable_paths is not None and candidate.path not in reviewable_paths:
            reason = "file is not reviewable"
        elif candidate.start_line != candidate.end_line:
            reason = "only single-line findings are supported"
        else:
            matching_lines = [
                line
                for hunk in changed_file.hunks
                for line in hunk.lines
                if line.new_line == candidate.start_line
            ]
            if not matching_lines:
                deletion_lines = [
                    line
                    for hunk in changed_file.hunks
                    for line in hunk.lines
                    if line.kind == DiffLineKind.DELETION
                    and line.old_line == candidate.start_line
                ]
                reason = (
                    "line exists only as a deletion"
                    if deletion_lines
                    else "line does not exist on the new side of the diff"
                )
            elif not any(line.kind == DiffLineKind.ADDITION for line in matching_lines):
                reason = "line is not an addition"

        if reason:
            rejected.append(RejectedFinding(candidate=candidate, reason=reason))
            continue

        key = _duplicate_key(candidate)
        existing = accepted_by_key.get(key)
        if existing is None or candidate.confidence > existing.confidence:
            if existing is not None:
                rejected.append(
                    RejectedFinding(candidate=existing, reason="lower-confidence duplicate")
                )
            accepted_by_key[key] = candidate
        else:
            rejected.append(
                RejectedFinding(candidate=candidate, reason="lower-confidence duplicate")
            )

    accepted = sorted(
        accepted_by_key.values(),
        key=lambda finding: (
            SEVERITY_ORDER[finding.severity],
            finding.path,
            finding.start_line,
            finding.title.casefold(),
        ),
    )
    return FindingValidation(accepted=tuple(accepted), rejected=tuple(rejected))
