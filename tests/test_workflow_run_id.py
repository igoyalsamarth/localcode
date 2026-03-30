"""Tests for stable GitHub workflow run_id strings."""

import pytest

from services.github.workflow_run_id import (
    github_issue_workflow_run_id,
    github_pr_workflow_run_id,
)


@pytest.mark.unit
class TestWorkflowRunId:
    def test_issue_format(self):
        assert (
            github_issue_workflow_run_id("acme/app", 42)
            == "github:acme/app#issue-42"
        )

    def test_pr_format(self):
        assert github_pr_workflow_run_id("acme/app", 7) == "github:acme/app#pr-7"
