from __future__ import annotations

from .diff_parser import parse_unified_diff
from .filters import partition_files
from .models import (
    BudgetPolicy,
    ChangedFile,
    DiffLineKind,
    ParsedDiff,
    ReviewChunk,
    ReviewPreparation,
    SkippedFile,
)

DEFAULT_BUDGET_POLICY = BudgetPolicy()


def _render_hunk(changed_file: ChangedFile, hunk_index: int) -> str:
    hunk = changed_file.hunks[hunk_index]
    prefixes = {
        DiffLineKind.CONTEXT: " ",
        DiffLineKind.ADDITION: "+",
        DiffLineKind.DELETION: "-",
    }
    body = "\n".join(prefixes[line.kind] + line.content for line in hunk.lines)
    return f"{hunk.header}\n{body}" if body else hunk.header


def _chunks_for_file(
    changed_file: ChangedFile, policy: BudgetPolicy
) -> tuple[list[ReviewChunk], str | None]:
    rendered = [_render_hunk(changed_file, index) for index in range(len(changed_file.hunks))]
    if any(len(hunk) > policy.max_chunk_chars for hunk in rendered):
        return [], "a hunk exceeds the review chunk character limit"

    chunks: list[ReviewChunk] = []
    current_parts: list[str] = []
    current_indexes: list[int] = []
    current_added = 0

    def finish_chunk() -> None:
        nonlocal current_parts, current_indexes, current_added
        if current_parts:
            chunks.append(
                ReviewChunk(
                    path=changed_file.path,
                    text="\n".join(current_parts),
                    hunk_indexes=tuple(current_indexes),
                    added_lines=current_added,
                )
            )
        current_parts = []
        current_indexes = []
        current_added = 0

    for index, text in enumerate(rendered):
        separator_size = 1 if current_parts else 0
        if current_parts and len("\n".join(current_parts)) + separator_size + len(text) > policy.max_chunk_chars:
            finish_chunk()
        current_parts.append(text)
        current_indexes.append(index)
        current_added += sum(
            line.kind == DiffLineKind.ADDITION for line in changed_file.hunks[index].lines
        )
    finish_chunk()
    return chunks, None


def prepare_review(
    diff_text: str, policy: BudgetPolicy = DEFAULT_BUDGET_POLICY
) -> ReviewPreparation:
    raw_bytes = len(diff_text.encode("utf-8"))
    if raw_bytes > policy.max_raw_diff_bytes:
        reason = (
            f"raw diff is {raw_bytes} bytes; limit is {policy.max_raw_diff_bytes}"
        )
        return ReviewPreparation(
            parsed_diff=ParsedDiff(raw_bytes=raw_bytes, errors=(reason,)),
            budget_exhausted=True,
            budget_reasons=(reason,),
        )

    parsed = parse_unified_diff(diff_text)
    budget_reasons: list[str] = []
    in_scope_files = parsed.files[: policy.max_files]
    initially_reviewable, skipped = partition_files(in_scope_files)
    for changed_file in parsed.files[policy.max_files :]:
        reason = "file limit exceeded"
        skipped.append(SkippedFile(path=changed_file.path, reason=reason))
        budget_reasons.append(f"{changed_file.path}: {reason}")
    reviewable: list[ChangedFile] = []
    chunks: list[ReviewChunk] = []
    total_reviewable_lines = 0

    for changed_file in initially_reviewable:
        if changed_file.changed_lines > policy.max_changed_lines_per_file:
            reason = "changed-line limit exceeded"
            skipped.append(SkippedFile(path=changed_file.path, reason=reason))
            budget_reasons.append(f"{changed_file.path}: {reason}")
            continue
        if total_reviewable_lines + changed_file.changed_lines > policy.max_total_reviewable_lines:
            reason = "total reviewable-line limit exceeded"
            skipped.append(SkippedFile(path=changed_file.path, reason=reason))
            budget_reasons.append(f"{changed_file.path}: {reason}")
            continue

        file_chunks, chunk_error = _chunks_for_file(changed_file, policy)
        if chunk_error:
            skipped.append(SkippedFile(path=changed_file.path, reason=chunk_error))
            budget_reasons.append(f"{changed_file.path}: {chunk_error}")
            continue
        if len(chunks) + len(file_chunks) > policy.max_chunks:
            reason = "review chunk limit exceeded"
            skipped.append(SkippedFile(path=changed_file.path, reason=reason))
            budget_reasons.append(f"{changed_file.path}: {reason}")
            continue

        reviewable.append(changed_file)
        chunks.extend(file_chunks)
        total_reviewable_lines += changed_file.changed_lines

    return ReviewPreparation(
        parsed_diff=parsed,
        reviewable_files=tuple(reviewable),
        skipped_files=tuple(skipped),
        chunks=tuple(chunks),
        hunk_count=sum(len(changed_file.hunks) for changed_file in reviewable),
        added_reviewable_lines=sum(changed_file.additions for changed_file in reviewable),
        budget_exhausted=bool(budget_reasons),
        budget_reasons=tuple(budget_reasons),
    )
