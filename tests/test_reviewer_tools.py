"""Tests for PR inline review tool (GitHub API mocked)."""

import os
from unittest.mock import patch

import pytest

from agents.reviewer_tools import add_inline_review_comment


@pytest.mark.unit
class TestAddInlineReviewComment:
    def test_missing_env_reports_error(self):
        for k in list(os.environ.keys()):
            if k.startswith("GITHUB_PR_"):
                os.environ.pop(k, None)
        os.environ.pop("GH_TOKEN", None)

        result = add_inline_review_comment.invoke(
            {
                "path": "src/a.ts",
                "line": 10,
                "body": "nit",
                "start_line": None,
                "side": "RIGHT",
                "start_side": None,
            }
        )
        assert "Error" in result
        assert "GITHUB_PR_OWNER" in result or "Missing" in result

    @patch("agents.reviewer_tools.create_pr_review_comment")
    def test_success_returns_message(self, mock_create):
        mock_create.return_value = {"html_url": "https://github.com/o/r/pull/1#discussion-1"}

        env = {
            "GITHUB_PR_OWNER": "o",
            "GITHUB_PR_REPO": "r",
            "GITHUB_PR_NUMBER": "1",
            "GITHUB_PR_HEAD_SHA": "abc",
            "GH_TOKEN": "tok",
        }
        with patch.dict(os.environ, env, clear=False):
            result = add_inline_review_comment.invoke(
                {
                    "path": "README.md",
                    "line": 2,
                    "body": "Nice",
                    "start_line": None,
                    "side": "RIGHT",
                    "start_side": None,
                }
            )

        assert "Review comment added" in result
        assert "README.md" in result
        mock_create.assert_called_once()
        call_kw = mock_create.call_args.kwargs
        assert call_kw["owner"] == "o"
        assert call_kw["repo"] == "r"
        assert call_kw["pr_number"] == 1
        assert call_kw["commit_id"] == "abc"
