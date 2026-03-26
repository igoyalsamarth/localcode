"""Tests for Greagent GitHub label constants."""

import pytest

from services.github.greagent_labels import (
    CODE,
    IN_PROGRESS,
    DONE,
    ERROR,
    REVIEW,
    REVIEWED,
)


@pytest.mark.unit
class TestGreagentLabels:
    """Test Greagent label constants."""

    def test_code_label(self):
        """Test CODE label constant."""
        assert CODE == "greagent:code"

    def test_in_progress_label(self):
        """Test IN_PROGRESS label constant."""
        assert IN_PROGRESS == "greagent:in-progress"

    def test_done_label(self):
        """Test DONE label constant."""
        assert DONE == "greagent:done"

    def test_error_label(self):
        """Test ERROR label constant."""
        assert ERROR == "greagent:error"

    def test_review_label(self):
        """Test REVIEW label constant."""
        assert REVIEW == "greagent:review"

    def test_reviewed_label(self):
        """Test REVIEWED label constant."""
        assert REVIEWED == "greagent:reviewed"

    def test_all_labels_are_strings(self):
        """Test all labels are strings."""
        assert isinstance(CODE, str)
        assert isinstance(IN_PROGRESS, str)
        assert isinstance(DONE, str)
        assert isinstance(ERROR, str)
        assert isinstance(REVIEW, str)
        assert isinstance(REVIEWED, str)

    def test_labels_have_greagent_prefix(self):
        """Test all labels have greagent prefix."""
        assert CODE.startswith("greagent:")
        assert IN_PROGRESS.startswith("greagent:")
        assert DONE.startswith("greagent:")
        assert ERROR.startswith("greagent:")
        assert REVIEW.startswith("greagent:")
        assert REVIEWED.startswith("greagent:")
