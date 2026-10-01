"""Review-provider contracts and implementations."""

from .base import ReviewProvider
from .fake import FakeReviewProvider

__all__ = ["FakeReviewProvider", "ReviewProvider"]
