"""Tests for the local reviewer pipeline helpers."""

from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from agents.github_reviewer import run_agent_on_pr
from services.github.pr_payload import PROpenedForReview
from services.github.reviewer_local import (
    PullRequestFileDiff,
    ReviewDecision,
    ReviewInlineComment,
    _extract_json_payload,
    build_repository_snapshot,
    build_review_prompt,
    collect_relevant_context,
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
    @patch("services.github.reviewer_local.get_github_deep_agent_llm")
    def test_generate_review_decision_uses_structured_output(
        self,
        mock_get_llm,
        mock_create_agent,
    ):
        mock_get_llm.return_value = Mock()
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
            [],
            {"issue_comments": [], "review_comments": []},
        )

        assert mock_create_agent.call_count == 1
        kwargs = mock_create_agent.call_args.kwargs
        assert kwargs["response_format"].schema is ReviewDecision
        agent.invoke.assert_called_once()
        assert decision.summary == "ok"

    def test_build_review_prompt_excludes_repository_snapshot(self):
        pr = _sample_pr()
        prompt = build_review_prompt(
            pr,
            [
                PullRequestFileDiff(
                    path="a.py",
                    status="modified",
                    patch="@@ -1,1 +1,1 @@\n-old\n+new\n",
                    previous_filename=None,
                    language="python",
                    hunks=parse_patch("@@ -1,1 +1,1 @@\n-old\n+new\n"),
                )
            ],
            [
                {
                    "kind": "repo_context",
                    "path": "a.py",
                    "name": "foo",
                    "line_range": [3, 4],
                    "calls": ["bar"],
                    "imports_used": ["Request"],
                    "code": "def foo():\n    return 1",
                }
            ],
            {"issue_comments": [], "review_comments": []},
        )

        assert "Repository snapshot JSON path" not in prompt
        assert "Repository symbol snapshot" not in prompt
        assert "Relevant extracted code context" in prompt
        assert '"code": "def foo():\\n    return 1"' in prompt
        assert '"name": "foo"' not in prompt
        assert '"line_range"' not in prompt
        assert '"calls"' not in prompt
        assert '"imports_used"' not in prompt


@pytest.mark.unit
class TestRepositorySnapshot:
    def test_snapshot_uses_symbol_only_payload(self, tmp_path):
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        (repo_dir / "sample.py").write_text(
            "from db import get_engine\n\n"
            "def health_check():\n"
            "    engine = get_engine()\n"
            "    return engine\n",
            encoding="utf-8",
        )

        snapshot = build_repository_snapshot(repo_dir)

        file_entry = snapshot.file_inventory[0]
        assert "symbols" in file_entry
        assert "ast" not in file_entry
        assert file_entry["symbols"]["functions"][0]["name"] == "health_check"
        assert file_entry["symbols"]["imports"][0]["imported_names"] == ["get_engine"]

    def test_collect_relevant_context_includes_imported_function(self, tmp_path):
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        db_dir = repo_dir / "db"
        db_dir.mkdir()
        (db_dir / "__init__.py").write_text(
            "from .client import get_engine\n",
            encoding="utf-8",
        )
        (db_dir / "client.py").write_text(
            "def get_engine():\n"
            "    return 'engine'\n",
            encoding="utf-8",
        )
        (repo_dir / "health.py").write_text(
            "from db import get_engine\n\n"
            "def health_check():\n"
            "    engine = get_engine()\n"
            "    return {'status': 'ok', 'engine': engine}\n",
            encoding="utf-8",
        )

        snapshot = build_repository_snapshot(repo_dir)
        diffs = [
            PullRequestFileDiff(
                path="health.py",
                status="modified",
                patch=(
                    "@@ -1,4 +1,5 @@\n"
                    " from db import get_engine\n"
                    " \n"
                    " def health_check():\n"
                    "     engine = get_engine()\n"
                    "+    version = 'v2'\n"
                    "     return {'status': 'ok', 'engine': engine}\n"
                ),
                previous_filename=None,
                language="python",
                hunks=parse_patch(
                    "@@ -1,4 +1,5 @@\n"
                    " from db import get_engine\n"
                    " \n"
                    " def health_check():\n"
                    "     engine = get_engine()\n"
                    "+    version = 'v2'\n"
                    "     return {'status': 'ok', 'engine': engine}\n"
                ),
            )
        ]

        context = collect_relevant_context(snapshot, diffs)

        assert any(
            piece.get("kind") == "repo_context"
            and piece.get("name") == "health_check"
            for piece in context
        )
        assert any(
            piece.get("kind") == "imported_reference"
            and piece.get("name") == "get_engine"
            and piece.get("path") == "db/client.py"
            for piece in context
        )

    def test_collect_relevant_context_includes_typescript_import(self, tmp_path):
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        (repo_dir / "version.ts").write_text(
            "export function getVersion() {\n"
            "  return 'v2';\n"
            "}\n",
            encoding="utf-8",
        )
        (repo_dir / "health.ts").write_text(
            'import { getVersion } from "./version"\n\n'
            "export function healthRoute() {\n"
            "  return { status: 'ok', version: getVersion() }\n"
            "}\n",
            encoding="utf-8",
        )

        snapshot = build_repository_snapshot(repo_dir)
        diffs = [
            PullRequestFileDiff(
                path="health.ts",
                status="modified",
                patch=(
                    "@@ -1,3 +1,4 @@\n"
                    ' import { getVersion } from "./version"\n'
                    " \n"
                    " export function healthRoute() {\n"
                    "+  const route = '/health'\n"
                    "   return { status: 'ok', version: getVersion() }\n"
                    " }\n"
                ),
                previous_filename=None,
                language="typescript",
                hunks=parse_patch(
                    "@@ -1,3 +1,4 @@\n"
                    ' import { getVersion } from "./version"\n'
                    " \n"
                    " export function healthRoute() {\n"
                    "+  const route = '/health'\n"
                    "   return { status: 'ok', version: getVersion() }\n"
                    " }\n"
                ),
            )
        ]

        context = collect_relevant_context(snapshot, diffs)

        assert any(
            piece.get("kind") == "repo_context"
            and piece.get("name") == "healthRoute"
            for piece in context
        )
        assert any(
            piece.get("name") == "getVersion"
            and piece.get("path") == "version.ts"
            for piece in context
        )

    def test_collect_relevant_context_includes_go_package_call(self, tmp_path):
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        db_dir = repo_dir / "db"
        db_dir.mkdir()
        (db_dir / "db.go").write_text(
            "package db\n\n"
            "func GetEngine() string {\n"
            '    return "engine"\n'
            "}\n",
            encoding="utf-8",
        )
        (repo_dir / "health.go").write_text(
            "package api\n\n"
            'import "app/db"\n\n'
            "func Health() string {\n"
            "    return db.GetEngine()\n"
            "}\n",
            encoding="utf-8",
        )

        snapshot = build_repository_snapshot(repo_dir)
        diffs = [
            PullRequestFileDiff(
                path="health.go",
                status="modified",
                patch=(
                    "@@ -3,3 +3,4 @@\n"
                    ' import "app/db"\n'
                    " \n"
                    " func Health() string {\n"
                    "+    version := \"v2\"\n"
                    "     return db.GetEngine()\n"
                    " }\n"
                ),
                previous_filename=None,
                language="go",
                hunks=parse_patch(
                    "@@ -3,3 +3,4 @@\n"
                    ' import "app/db"\n'
                    " \n"
                    " func Health() string {\n"
                    "+    version := \"v2\"\n"
                    "     return db.GetEngine()\n"
                    " }\n"
                ),
            )
        ]

        context = collect_relevant_context(snapshot, diffs)

        assert any(
            piece.get("kind") == "repo_context"
            and piece.get("name") == "Health"
            for piece in context
        )
        assert any(
            piece.get("name") == "GetEngine"
            and piece.get("path") == "db/db.go"
            for piece in context
        )


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
                    body="valid",
                    side="RIGHT",
                ),
                ReviewInlineComment(
                    path="src/a.py",
                    line=999,
                    body="invalid",
                    side="RIGHT",
                ),
            ],
        )

        publish_review(pr, "tok", decision, file_diffs)

        mock_inline.assert_called_once()
        assert mock_inline.call_args.kwargs["line"] == 2
        mock_comment.assert_called_once()
        mock_submit.assert_called_once()


@pytest.mark.unit
class TestRunAgentOnPr:
    @patch("agents.github_reviewer.record_pr_workflow_usage")
    @patch("agents.github_reviewer.publish_review")
    @patch("agents.github_reviewer.generate_review_decision")
    @patch("agents.github_reviewer.fetch_previous_comments")
    @patch("agents.github_reviewer.collect_relevant_context")
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
        mock_collect_context,
        mock_fetch_comments,
        mock_generate,
        mock_publish,
        mock_record_usage,
    ):
        pr = _sample_pr()
        llm = Mock()
        llm.callbacks = None
        mock_get_llm.return_value = llm
        mock_clone.return_value = Path("/tmp/repo")
        mock_snapshot.return_value = Mock()
        mock_fetch_diffs.return_value = []
        mock_collect_context.return_value = []
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
        mock_collect_context.assert_called_once()
        mock_fetch_comments.assert_called_once_with(pr.owner, pr.repo_name, pr.pr_number, "tok")
        mock_generate.assert_called_once()
        mock_publish.assert_called_once_with(pr, "tok", mock_generate.return_value, [])
        mock_record_usage.assert_called_once()
        assert llm.callbacks is None
