"""Tests for stable LangGraph thread id helpers."""

import pytest

from agents.checkpoint import (
    github_issue_workflow_thread_id,
    github_pr_workflow_thread_id,
)


@pytest.mark.unit
class TestGithubThreadIds:
    def test_issue_thread_id_format(self):
        assert (
            github_issue_workflow_thread_id("acme/app", 42)
            == "github:acme/app#issue-42"
        )

    def test_pr_thread_id_format(self):
        assert (
            github_pr_workflow_thread_id("acme/app", 7)
            == "github:acme/app#pr-7"
        )
