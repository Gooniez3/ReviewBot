from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..models import ProviderResult, ProviderReviewInput


@runtime_checkable
class ReviewProvider(Protocol):
    """GitHub-agnostic provider boundary.

    A future hosted provider will receive raw, untrusted text or JSON from its
    API. Parsing belongs inside that adapter, which must enforce response byte
    and item limits. Malformed output must not cross this boundary: only strict
    ProviderResult and FindingCandidate domain objects may be returned.
    """

    @property
    def name(self) -> str: ...

    @property
    def model_name(self) -> str | None: ...

    def review(self, review_input: ProviderReviewInput) -> ProviderResult: ...
