from __future__ import annotations

from .models import (
    DryRunReview,
    FindingValidation,
    ProviderPolicy,
    ProviderResult,
    ProviderReviewInput,
    RejectedFinding,
    ReviewPreparation,
)
from .providers.base import ReviewProvider
from .validation import validate_findings

DEFAULT_PROVIDER_POLICY = ProviderPolicy()


def _provider_identity(provider: ReviewProvider) -> tuple[str, str | None]:
    try:
        name = provider.name
        model_name = provider.model_name
    except Exception:
        return type(provider).__name__, None
    if not isinstance(name, str) or not name.strip():
        name = type(provider).__name__
    if model_name is not None and not isinstance(model_name, str):
        model_name = None
    return name[:100], model_name[:200] if model_name else None


def _failed_review(
    provider_name: str, model_name: str | None, error_code: str
) -> DryRunReview:
    return DryRunReview(
        provider_name=provider_name,
        model_name=model_name,
        provider_available=False,
        validation=FindingValidation(),
        provider_errors=(error_code,),
    )


def run_dry_review(
    preparation: ReviewPreparation,
    provider: ReviewProvider,
    policy: ProviderPolicy = DEFAULT_PROVIDER_POLICY,
) -> DryRunReview:
    """Run an untrusted provider, then enforce deterministic Phase 1 validation."""

    provider_name, model_name = _provider_identity(provider)
    review_input = ProviderReviewInput(
        reviewable_files=preparation.reviewable_files,
        chunks=preparation.chunks,
    )
    try:
        provider_result = provider.review(review_input)
    except Exception as exc:
        # Deliberately retain only the exception class, never its potentially
        # sensitive message, provider response, prompt, or source input.
        return _failed_review(
            provider_name,
            model_name,
            f"provider_exception:{type(exc).__name__}",
        )

    if not isinstance(provider_result, ProviderResult):
        return _failed_review(
            provider_name, model_name, "malformed_provider_result"
        )

    candidates = provider_result.candidates
    retained = candidates[: policy.max_candidates]
    capped = candidates[policy.max_candidates :]
    reviewable_paths = {
        changed_file.path for changed_file in preparation.reviewable_files
    }
    validation = validate_findings(
        retained,
        preparation.parsed_diff,
        reviewable_paths=reviewable_paths,
    )

    accepted = validation.accepted[: policy.max_accepted_findings]
    accepted_overflow = validation.accepted[policy.max_accepted_findings :]
    rejected = list(validation.rejected)
    rejected.extend(
        RejectedFinding(
            candidate=candidate,
            reason="accepted finding cap exceeded",
        )
        for candidate in accepted_overflow
    )
    rejected.extend(
        RejectedFinding(candidate=candidate, reason="provider candidate cap exceeded")
        for candidate in capped
    )

    return DryRunReview(
        provider_name=provider_name,
        model_name=model_name,
        candidates=candidates,
        validation=FindingValidation(
            accepted=accepted,
            rejected=tuple(rejected),
        ),
        provider_errors=provider_result.errors,
    )
