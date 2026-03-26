"""Tests for shared trigger mode constants used by PR review."""

import pytest

from services.github.trigger_modes import TRIGGER_MODE_AUTO, TRIGGER_MODE_TAG


@pytest.mark.unit
class TestReviewTrigger:
    """Test trigger mode constants (PR review defaults)."""

    def test_trigger_mode_tag_constant(self):
        assert TRIGGER_MODE_TAG == "tag"

    def test_trigger_mode_auto_constant(self):
        assert TRIGGER_MODE_AUTO == "auto"

    def test_trigger_modes_are_strings(self):
        assert isinstance(TRIGGER_MODE_TAG, str)
        assert isinstance(TRIGGER_MODE_AUTO, str)

    def test_trigger_modes_are_different(self):
        assert TRIGGER_MODE_TAG != TRIGGER_MODE_AUTO

    def test_trigger_mode_tag_is_lowercase(self):
        assert TRIGGER_MODE_TAG == TRIGGER_MODE_TAG.lower()

    def test_trigger_mode_auto_is_lowercase(self):
        assert TRIGGER_MODE_AUTO == TRIGGER_MODE_AUTO.lower()
