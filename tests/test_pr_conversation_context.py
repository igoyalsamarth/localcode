"""Tests for PR comment fetching / formatting for LLM context."""

from unittest.mock import patch

import pytest

from services.github.pr_conversation_context import (
    fetch_pr_conversation_context_for_llm,
    format_pr_comments_for_llm,
)


@pytest.mark.unit
class TestFormatPrCommentsForLlm:
    def test_empty_returns_empty_string(self):
        assert format_pr_comments_for_llm([], []) == ""

    def test_skips_empty_bodies(self):
        issue = [
            {"user": {"login": "a"}, "created_at": "2024-01-01", "body": "   "},
            {"user": {"login": "b"}, "created_at": "2024-01-02", "body": "Please fix tests"},
        ]
        out = format_pr_comments_for_llm(issue, [])
        assert "Please fix tests" in out
        assert "@b" in out
        assert "Conversation comments" in out

    def test_review_comments_include_path_and_diff_excerpt(self):
        review = [
            {
                "user": {"login": "r1"},
                "created_at": "2024-01-03",
                "path": "src/x.ts",
                "line": 10,
                "body": "Nit: rename",
                "diff_hunk": "@@ -1,3 +1,3 @@\n-old\n+new",
            }
        ]
        out = format_pr_comments_for_llm([], review)
        assert "Inline review comments" in out
        assert "src/x.ts" in out
        assert "line 10" in out
        assert "Nit: rename" in out
        assert "diff" in out.lower()

    def test_truncation_keeps_suffix_of_oversized_single_comment(self):
        long_body = "x" * 5000
        issue = [{"user": {"login": "u"}, "created_at": "t", "body": long_body}]
        out = format_pr_comments_for_llm(issue, [], max_chars=200)
        assert "Older conversation" in out or "omitted" in out.lower()
        assert out.rstrip().endswith("x")

    def test_truncation_prefers_latest_comment_when_multiple(self):
        issue = [
            {
                "user": {"login": "a"},
                "created_at": "t1",
                "body": "OLD_THREAD_SHOULD_DROP" + "x" * 400,
            },
            {"user": {"login": "b"}, "created_at": "t2", "body": "KEEP_LATEST"},
        ]
        out = format_pr_comments_for_llm(issue, [], max_chars=400)
        assert "KEEP_LATEST" in out
        assert "OLD_THREAD_SHOULD_DROP" not in out

    def test_review_comments_not_truncated_when_conversation_is(self):
        long_conv = "x" * 4000
        issue = [{"user": {"login": "u"}, "created_at": "t", "body": long_conv}]
        huge_diff = "D" * 3000
        review = [
            {
                "user": {"login": "r"},
                "created_at": "t",
                "path": "a.ts",
                "line": 1,
                "body": "FULL_REVIEW_BODY_INTACT",
                "diff_hunk": huge_diff,
            }
        ]
        out = format_pr_comments_for_llm(issue, review, max_chars=250)
        assert "FULL_REVIEW_BODY_INTACT" in out
        assert huge_diff in out
        assert "Older conversation" in out or "omitted" in out.lower()
        assert len(out) > 250

    def test_fetch_wires_lists_and_format(self):
        with (
            patch(
                "services.github.pr_conversation_context.list_pr_issue_comments",
                return_value=[
                    {"user": {"login": "u"}, "created_at": "t", "body": "hello"},
                ],
            ),
            patch(
                "services.github.pr_conversation_context.list_pr_review_comments",
                return_value=[],
            ),
        ):
            s = fetch_pr_conversation_context_for_llm("o", "r", 1, "tok")
        assert "hello" in s

    def test_fetch_returns_empty_on_request_error(self):
        with (
            patch(
                "services.github.pr_conversation_context.list_pr_issue_comments",
                side_effect=RuntimeError("network"),
            ),
        ):
            s = fetch_pr_conversation_context_for_llm("o", "r", 1, "tok")
        assert s == ""
