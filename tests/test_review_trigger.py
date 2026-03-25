"""Tests for review trigger constants and helpers."""

import pytest

from services.github.review_trigger import (
    REVIEW_MODE_TAG,
    REVIEW_MODE_AUTO,
)


@pytest.mark.unit
class TestReviewTrigger:
    """Test review trigger constants."""

    def test_review_mode_tag_constant(self):
        """Test REVIEW_MODE_TAG constant value."""
        assert REVIEW_MODE_TAG == "tag"

    def test_review_mode_auto_constant(self):
        """Test REVIEW_MODE_AUTO constant value."""
        assert REVIEW_MODE_AUTO == "auto"

    def test_review_modes_are_strings(self):
        """Test review mode constants are strings."""
        assert isinstance(REVIEW_MODE_TAG, str)
        assert isinstance(REVIEW_MODE_AUTO, str)

    def test_review_modes_are_different(self):
        """Test review mode constants are different."""
        assert REVIEW_MODE_TAG != REVIEW_MODE_AUTO

    def test_review_mode_tag_is_lowercase(self):
        """Test REVIEW_MODE_TAG is lowercase."""
        assert REVIEW_MODE_TAG == REVIEW_MODE_TAG.lower()

    def test_review_mode_auto_is_lowercase(self):
        """Test REVIEW_MODE_AUTO is lowercase."""
        assert REVIEW_MODE_AUTO == REVIEW_MODE_AUTO.lower()
