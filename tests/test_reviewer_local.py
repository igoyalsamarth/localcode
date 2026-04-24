"""Tests for the local reviewer pipeline helpers."""

import json
import re
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from agents.github_reviewer import run_agent_on_pr
from services.github.pr_payload import PROpenedForReview
from services.github.reviewer_local import (
    PullRequestFileDiff,
    ReviewDecision,
    ReviewInlineComment,
    _GITHUB_REVIEW_SYSTEM_MESSAGE,
    _extract_json_payload,
    _is_test_file,
    build_review_user_message,
    generate_review_decision,
    parse_patch,
    publish_review,
)


def _sample_pr() -> PROpenedForReview:
    return PROpenedForReview(
        owner="o",
        repo_name="r",
        full_name="o/r",
        repo_url="https://github.com/o/r",
        github_repo_id=123,
        pr_number=9,
        pr_title="Improve reviewer",
        pr_body="Body",
        base_branch="main",
        head_branch="feat/reviewer",
        head_sha="abc123",
        github_installation_id=7,
    )


@pytest.mark.unit
class TestParsePatch:
    def test_parse_patch_tracks_old_and_new_lines(self):
        patch = """@@ -10,4 +10,5 @@ def sample():
 context_a = 1
-old_value = 2
+new_value = 3
 keep_value = 4
"""
        hunks = parse_patch(patch)

        assert len(hunks) == 1
        hunk = hunks[0]
        assert hunk.old_start == 10
        assert hunk.new_start == 10
        assert hunk.added_new_lines == [11]
        assert hunk.deleted_old_lines == [11]
        assert 10 in hunk.right_commentable_lines
        assert 10 in hunk.left_commentable_lines

    def test_new_file_lines_for_repo_context_ignores_unchanged_context(self):
        """Import-style hunks: only added lines should drive symbol extraction."""
        patch = """@@ -1,3 +1,4 @@
 import a
+import zod
 import b
 import c
"""
        hunks = parse_patch(patch)
        assert len(hunks) == 1
        hunk = hunks[0]
        assert hunk.added_new_lines == [2]
        assert hunk.new_file_lines_for_repo_context == [2]
        # modified_new_lines would include 1,3,4,5 (all context+add) — not used for context
        assert set(hunk.modified_new_lines) == {1, 2, 3, 4}


@pytest.mark.unit
class TestReviewerPayloadParsing:
    def test_extract_json_payload_supports_fenced_blocks(self):
        payload = """```json
{"summary":"ok","review_event":"COMMENT","review_body":"body","pr_comment_body":"comment","inline_comments":[]}
```"""

        parsed = _extract_json_payload(payload)

        assert parsed["summary"] == "ok"
        assert parsed["review_event"] == "COMMENT"

    @patch("services.github.reviewer_local.create_agent")
    def test_generate_review_decision_uses_structured_output(
        self,
        mock_create_agent,
    ):
        agent = Mock()
        mock_create_agent.return_value = agent
        agent.invoke.return_value = {
            "structured_response": ReviewDecision(
                summary="ok",
                review_event="COMMENT",
                review_body="body",
                pr_comment_body="comment",
                inline_comments=[],
            )
        }

        decision = generate_review_decision(
            _sample_pr(),
            [],
            {"issue_comments": [], "review_comments": []},
        )

        assert mock_create_agent.call_count == 1
        kwargs = mock_create_agent.call_args.kwargs
        assert kwargs["system_prompt"] == _GITHUB_REVIEW_SYSTEM_MESSAGE
        assert kwargs["response_format"].schema is ReviewDecision
        agent.invoke.assert_called_once()
        invoke_in = agent.invoke.call_args[0][0]
        assert len(invoke_in["messages"]) == 1
        assert invoke_in["messages"][0]["role"] == "user"
        assert decision.summary == "ok"

    def test_build_review_user_message_excludes_repository_snapshot(self):
        pr = _sample_pr()
        review_blocks = [
            {
                "path": "a.py",
                "status": "modified",
                "language": "python",
                "hunks": [
                    {
                        "hunk_header": "@@ -1,1 +1,1 @@",
                        "right_code": "new",
                        "left_code": "old",
                        "commentable_right_lines": [1],
                        "extra_context": [
                            {
                                "kind": "repo_context",
                                "path": "a.py",
                                "hunk_header": None,
                                "name": "foo",
                                "code": "def foo():\n    return 1",
                            }
                        ],
                    }
                ],
            }
        ]
        user = build_review_user_message(
            pr, review_blocks, {"issue_comments": [], "review_comments": []}
        )

        assert "Repository snapshot JSON path" not in user
        assert "Repository symbol snapshot" not in user
        assert "Changed files" in user
        assert "extra_context" in user
        assert "minified" in user.lower()
        assert '"code":"def foo():\\n    return 1"' in user
        assert '"name":"foo"' in user
        assert '"line_range"' not in user
        assert '"calls"' not in user
        assert '"imports_used"' not in user

    def test_build_review_user_message_json_fenced_blocks_are_minified(self):
        """Changed files and prior comments use compact JSON (no indent whitespace)."""
        pr = _sample_pr()
        review_blocks = [{"path": "x.py", "status": "modified", "language": "python", "hunks": []}]
        prev = {"issue_comments": [], "review_comments": []}
        user = build_review_user_message(pr, review_blocks, prev)

        blocks = re.findall(r"```json\n(.*?)\n```", user, re.DOTALL)
        assert len(blocks) == 2
        files_json, comments_json = blocks
        assert json.loads(files_json) == review_blocks
        assert json.loads(comments_json) == prev
        assert "\n " not in files_json
        assert files_json == json.dumps(review_blocks, separators=(",", ":"), ensure_ascii=False)

    def test_build_review_user_message_includes_decorators_for_tests(self):
        pr = _sample_pr()
        review_blocks = [
            {
                "path": "test_a.py",
                "status": "modified",
                "language": "python",
                "hunks": [
                    {
                        "hunk_header": "@@ -1,1 +1,1 @@",
                        "right_code": "new",
                        "left_code": "old",
                        "commentable_right_lines": [1],
                        "extra_context": [],
                    }
                ],
                "file_level_context": [
                    {
                        "kind": "repo_context",
                        "path": "test_a.py",
                        "hunk_header": None,
                        "name": "test_something",
                        "code": "def test_something():\n    pass",
                        "decorators": [
                            "@mock.patch('time.sleep')",
                            "@pytest.fixture",
                        ],
                    }
                ],
            }
        ]
        user = build_review_user_message(
            pr, review_blocks, {"issue_comments": [], "review_comments": []}
        )

        assert "Changed files" in user
        assert "file_level_context" in user
        assert '"decorators"' in user
        assert "@mock.patch" in user
        assert "@pytest.fixture" in user
        assert "o/r" in user


@pytest.mark.unit
class TestTestFileDetection:
    def test_is_test_file_detects_python_test_files(self):
        assert _is_test_file("test_foo.py")
        assert _is_test_file("tests/test_bar.py")
        assert _is_test_file("src/foo_test.py")
        assert _is_test_file("tests/conftest.py")

    def test_is_test_file_detects_javascript_test_files(self):
        assert _is_test_file("component.spec.js")
        assert _is_test_file("component.spec.ts")
        assert _is_test_file("__tests__/component.test.js")

    def test_is_test_file_rejects_non_test_files(self):
        assert not _is_test_file("src/utils.py")
        assert not _is_test_file("main.py")
        assert not _is_test_file("components/Button.tsx")


@pytest.mark.unit
class TestPublishReview:
    @patch("services.github.reviewer_local.submit_pr_review")
    @patch("services.github.reviewer_local.comment_on_pr")
    @patch("services.github.reviewer_local.create_pr_review_comment")
    def test_publish_review_skips_invalid_inline_comments(
        self,
        mock_inline,
        mock_comment,
        mock_submit,
    ):
        pr = _sample_pr()
        file_diffs = [
            PullRequestFileDiff(
                path="src/a.py",
                status="modified",
                patch="@@ -1,1 +1,2 @@\n line1\n+line2\n",
                previous_filename=None,
                language="python",
                hunks=parse_patch("@@ -1,1 +1,2 @@\n line1\n+line2\n"),
            )
        ]
        decision = ReviewDecision(
            summary="summary",
            review_event="COMMENT",
            review_body="review body",
            pr_comment_body="pr body",
            inline_comments=[
                ReviewInlineComment(
                    path="src/a.py",
                    line=2,
                    severity="minor_bug",
                    body="valid",
                    side="RIGHT",
                ),
                ReviewInlineComment(
                    path="src/a.py",
                    line=999,
                    severity="nitpick",
                    body="invalid",
                    side="RIGHT",
                ),
            ],
        )

        publish_review(pr, "tok", decision, file_diffs)

        mock_inline.assert_called_once()
        assert mock_inline.call_args.kwargs["line"] == 2
        assert "**[Minor bug]**" in mock_inline.call_args.kwargs["body"]
        assert "valid" in mock_inline.call_args.kwargs["body"]
        mock_comment.assert_called_once()
        mock_submit.assert_called_once()


@pytest.mark.unit
class TestRunAgentOnPr:
    @patch("agents.github_reviewer.remove_reviewer_clone")
    @patch("agents.github_reviewer.record_pr_workflow_usage")
    @patch("agents.github_reviewer.publish_review")
    @patch("agents.github_reviewer.generate_review_decision")
    @patch("agents.github_reviewer.fetch_previous_comments")
    @patch("agents.github_reviewer.build_review_file_blocks")
    @patch("agents.github_reviewer.fetch_pr_file_diffs")
    @patch("agents.github_reviewer.build_repository_snapshot")
    @patch("agents.github_reviewer.clone_or_prepare_repo")
    @patch("agents.github_reviewer.get_github_deep_agent_llm")
    def test_run_agent_on_pr_uses_local_pipeline(
        self,
        mock_get_llm,
        mock_clone,
        mock_snapshot,
        mock_fetch_diffs,
        mock_file_blocks,
        mock_fetch_comments,
        mock_generate,
        mock_publish,
        mock_record_usage,
        mock_remove_clone,
    ):
        pr = _sample_pr()
        llm = Mock()
        llm.callbacks = None
        mock_get_llm.return_value = llm
        mock_clone.return_value = Path("/tmp/repo")
        mock_snapshot.return_value = Mock()
        mock_fetch_diffs.return_value = []
        mock_file_blocks.return_value = []
        mock_fetch_comments.return_value = {"issue_comments": [], "review_comments": []}
        mock_generate.return_value = ReviewDecision(
            summary="ok",
            review_event="APPROVE",
            review_body="LGTM",
            pr_comment_body="summary",
            inline_comments=[],
        )

        run_agent_on_pr(pr, access_token="tok")

        mock_clone.assert_called_once_with(pr, "tok")
        mock_snapshot.assert_called_once()
        mock_fetch_diffs.assert_called_once_with(pr.owner, pr.repo_name, pr.pr_number, "tok")
        mock_file_blocks.assert_called_once()
        mock_fetch_comments.assert_called_once_with(pr.owner, pr.repo_name, pr.pr_number, "tok")
        mock_generate.assert_called_once()
        mock_publish.assert_called_once_with(pr, "tok", mock_generate.return_value, [])
        mock_record_usage.assert_called_once()
        mock_remove_clone.assert_called_once_with(pr)
        assert llm.callbacks is None
