"""Tests for ``prepare_pr_for_review_work`` (PR label state before enqueue)."""

from unittest.mock import patch

import pytest

from services.github.greagent_labels import ERROR, REVIEW, REVIEWED, REVIEWING
from services.github.pr_payload import PROpenedForReview
from services.github.review_workflow import prepare_pr_for_review_work


def _sample_work(**kwargs) -> PROpenedForReview:
    base = dict(
        owner="o",
        repo_name="r",
        full_name="o/r",
        repo_url="https://github.com/o/r",
        github_repo_id=1001,
        pr_number=7,
        pr_title="T",
        pr_body="",
        base_branch="main",
        head_branch="f",
        head_sha="abc",
        github_installation_id=99,
    )
    base.update(kwargs)
    return PROpenedForReview(**base)


@pytest.mark.unit
class TestPreparePrForReviewWork:
    @patch("services.github.review_workflow.add_pr_labels")
    @patch("services.github.review_workflow.remove_pr_label")
    @patch("services.github.review_workflow.ensure_repo_label_exists")
    @patch("services.github.review_workflow.get_installation_token_for_repo")
    def test_auto_prepare_clears_stale_labels_and_sets_reviewing(
        self,
        mock_tok,
        mock_ensure_label,
        mock_remove,
        mock_add,
    ):
        mock_tok.return_value = "tok"
        work = _sample_work()

        prepare_pr_for_review_work(work)

        mock_tok.assert_called_once_with(
            work.owner,
            work.repo_name,
            github_installation_id=work.github_installation_id,
        )
        assert mock_ensure_label.call_count == 4
        assert mock_remove.call_args_list == [
            ((work.owner, work.repo_name, work.pr_number, ERROR, "tok"),),
            ((work.owner, work.repo_name, work.pr_number, REVIEWED, "tok"),),
            ((work.owner, work.repo_name, work.pr_number, REVIEW, "tok"),),
        ]
        mock_add.assert_called_once_with(
            work.owner,
            work.repo_name,
            work.pr_number,
            "tok",
            [REVIEWING],
        )
