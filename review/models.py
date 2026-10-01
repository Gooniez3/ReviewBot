from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class DiffLineKind(str, Enum):
    CONTEXT = "context"
    ADDITION = "addition"
    DELETION = "deletion"


class FileStatus(str, Enum):
    MODIFIED = "modified"
    ADDED = "added"
    DELETED = "deleted"
    RENAMED = "renamed"
    UNKNOWN = "unknown"


class Severity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class FindingCategory(str, Enum):
    CORRECTNESS = "correctness"
    SECURITY = "security"
    RELIABILITY = "reliability"
    CONCURRENCY = "concurrency"
    DATA_LOSS = "data_loss"
    API_MISUSE = "api_misuse"
    PERFORMANCE = "performance"
    MAINTAINABILITY = "maintainability"


class DiffLine(StrictModel):
    kind: DiffLineKind
    content: str
    old_line: int | None = Field(default=None, ge=1)
    new_line: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_coordinates(self) -> DiffLine:
        if self.kind == DiffLineKind.CONTEXT:
            valid = self.old_line is not None and self.new_line is not None
        elif self.kind == DiffLineKind.ADDITION:
            valid = self.old_line is None and self.new_line is not None
        else:
            valid = self.old_line is not None and self.new_line is None
        if not valid:
            raise ValueError(f"invalid coordinates for {self.kind.value} line")
        return self


class Hunk(StrictModel):
    header: str
    old_start: int = Field(ge=0)
    old_count: int = Field(ge=0)
    new_start: int = Field(ge=0)
    new_count: int = Field(ge=0)
    lines: tuple[DiffLine, ...] = ()


class ChangedFile(StrictModel):
    path: str
    old_path: str | None = None
    new_path: str | None = None
    status: FileStatus = FileStatus.UNKNOWN
    is_binary: bool = False
    is_combined: bool = False
    parse_error: str | None = None
    hunks: tuple[Hunk, ...] = ()

    @property
    def additions(self) -> int:
        return sum(
            line.kind == DiffLineKind.ADDITION
            for hunk in self.hunks
            for line in hunk.lines
        )

    @property
    def deletions(self) -> int:
        return sum(
            line.kind == DiffLineKind.DELETION
            for hunk in self.hunks
            for line in hunk.lines
        )

    @property
    def changed_lines(self) -> int:
        return self.additions + self.deletions


class SkippedFile(StrictModel):
    path: str
    reason: str


class ParsedDiff(StrictModel):
    files: tuple[ChangedFile, ...] = ()
    errors: tuple[str, ...] = ()
    raw_bytes: int = Field(default=0, ge=0)


class FindingCandidate(StrictModel):
    path: str = Field(min_length=1, max_length=500)
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    severity: Severity
    category: FindingCategory
    title: str = Field(min_length=1, max_length=160)
    explanation: str = Field(min_length=1, max_length=2000)
    suggested_fix: str | None = Field(default=None, max_length=2000)
    confidence: float = Field(ge=0.0, le=1.0)

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        if "\\" in value or value.startswith("/"):
            raise ValueError("path must be a repository-relative '/' path")
        if len(value) >= 2 and value[1] == ":":
            raise ValueError("absolute drive paths are not allowed")
        parts = value.split("/")
        if any(part in {"", ".", ".."} for part in parts):
            raise ValueError("path contains an invalid component")
        if any(ord(character) < 32 or ord(character) == 127 for character in value):
            raise ValueError("path contains control characters")
        return value

    @field_validator("title", "explanation")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("text must contain a non-whitespace character")
        return value

    @field_validator("suggested_fix")
    @classmethod
    def validate_optional_text(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("suggested fix must contain a non-whitespace character")
        return value


class RejectedFinding(StrictModel):
    candidate: FindingCandidate
    reason: str


class FindingValidation(StrictModel):
    accepted: tuple[FindingCandidate, ...] = ()
    rejected: tuple[RejectedFinding, ...] = ()


class BudgetPolicy(StrictModel):
    max_raw_diff_bytes: int = Field(default=500_000, ge=1)
    max_files: int = Field(default=100, ge=1)
    max_changed_lines_per_file: int = Field(default=1_000, ge=1)
    max_total_reviewable_lines: int = Field(default=3_000, ge=1)
    max_chunk_chars: int = Field(default=12_000, ge=1)
    max_chunks: int = Field(default=20, ge=1)


class ReviewChunk(StrictModel):
    path: str
    text: str
    hunk_indexes: tuple[int, ...]
    added_lines: int = Field(ge=0)


class ReviewPreparation(StrictModel):
    parsed_diff: ParsedDiff
    reviewable_files: tuple[ChangedFile, ...] = ()
    skipped_files: tuple[SkippedFile, ...] = ()
    chunks: tuple[ReviewChunk, ...] = ()
    hunk_count: int = Field(default=0, ge=0)
    added_reviewable_lines: int = Field(default=0, ge=0)
    budget_exhausted: bool = False
    budget_reasons: tuple[str, ...] = ()


class ProviderReviewInput(StrictModel):
    """Deterministic, GitHub-agnostic input permitted to cross into a provider."""

    reviewable_files: tuple[ChangedFile, ...] = ()
    chunks: tuple[ReviewChunk, ...] = ()


class ProviderResult(StrictModel):
    """Strict domain candidates returned by a provider adapter."""

    candidates: tuple[FindingCandidate, ...] = ()
    errors: tuple[str, ...] = ()


class ProviderPolicy(StrictModel):
    max_candidates: int = Field(default=50, ge=1)
    max_accepted_findings: int = Field(default=20, ge=1)


class DryRunReview(StrictModel):
    provider_name: str = Field(min_length=1, max_length=100)
    model_name: str | None = Field(default=None, max_length=200)
    provider_available: bool = True
    candidates: tuple[FindingCandidate, ...] = ()
    validation: FindingValidation
    provider_errors: tuple[str, ...] = ()
