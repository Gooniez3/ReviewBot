from __future__ import annotations

from ..models import (
    DiffLineKind,
    FindingCandidate,
    FindingCategory,
    ProviderResult,
    ProviderReviewInput,
    Severity,
)


class FakeReviewProvider:
    """Deterministic, local-only provider for dry-run development and tests."""

    name = "fake"
    model_name = "deterministic-dry-run-fixture-v1"

    def __init__(
        self, candidates: tuple[FindingCandidate, ...] | None = None
    ) -> None:
        self._configured_candidates = candidates

    def review(self, review_input: ProviderReviewInput) -> ProviderResult:
        if self._configured_candidates is not None:
            return ProviderResult(candidates=self._configured_candidates)

        candidates: list[FindingCandidate] = []
        for changed_file in review_input.reviewable_files:
            first_addition = next(
                (
                    line
                    for hunk in changed_file.hunks
                    for line in hunk.lines
                    if line.kind == DiffLineKind.ADDITION
                ),
                None,
            )
            if first_addition is None or first_addition.new_line is None:
                continue
            candidates.append(
                FindingCandidate(
                    path=changed_file.path,
                    start_line=first_addition.new_line,
                    end_line=first_addition.new_line,
                    severity=Severity.LOW,
                    category=FindingCategory.MAINTAINABILITY,
                    title="Dry-run fixture: synthetic finding",
                    explanation=(
                        "This is deterministic test data from FakeReviewProvider, "
                        "not a detected defect."
                    ),
                    suggested_fix=None,
                    confidence=0.5,
                )
            )
        return ProviderResult(candidates=tuple(candidates))
