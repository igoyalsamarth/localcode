"""Tests for ``workflow_usage`` persistence (patched DB session, no LangGraph)."""

from contextlib import contextmanager
from decimal import Decimal
from unittest.mock import patch

import pytest
from sqlalchemy import select

from agents.usage_callback import AgentLlmUsageCallbackHandler
from model.enums import GitHubWorkflowKind
from model.tables import AgentWorkflowUsage, Model, Organization, Repository, User
from services.github.issue_payload import IssueOpenedForCoder
from services.github.workflow_usage import record_issue_workflow_usage


@pytest.mark.unit
class TestWorkflowUsageRecord:
    @staticmethod
    def _fake_session_scope(session):
        @contextmanager
        def cm():
            try:
                yield session
                session.commit()
            except Exception:
                session.rollback()
                raise

        return cm

    def test_record_issue_usage_inserts_row(self, db_session):
        user = User(email="u@e.com", auth_provider="github")
        db_session.add(user)
        db_session.flush()
        org = Organization(name="O", owner_user_id=user.id)
        db_session.add(org)
        db_session.flush()
        repo = Repository(
            organization_id=org.id,
            github_repo_id=1,
            name="r",
            owner="o",
            default_branch="main",
        )
        db_session.add(repo)
        db_session.flush()
        m = Model(
            provider="ollama",
            name="m1",
            input_cost_per_token=Decimal("1"),
            output_cost_per_token=Decimal("2"),
        )
        db_session.add(m)
        db_session.commit()

        issue = IssueOpenedForCoder(
            owner="o",
            repo_name="r",
            full_name="o/r",
            repo_url="https://github.com/o/r",
            issue_number=9,
            issue_title="t",
            issue_body="",
            github_installation_id=None,
        )
        cb = AgentLlmUsageCallbackHandler()
        cb.usage_metadata["m1"] = {
            "input_tokens": 3,
            "output_tokens": 4,
            "total_tokens": 7,
        }

        with patch(
            "services.github.workflow_usage.session_scope",
            self._fake_session_scope(db_session),
        ):
            record_issue_workflow_usage(
                issue,
                "github:o/r#issue-9",
                cb,
                provider="ollama",
            )

        row = db_session.execute(select(AgentWorkflowUsage)).scalar_one()
        assert row.workflow == GitHubWorkflowKind.code
        assert row.github_item_number == 9
        assert row.input_tokens == 3
        assert row.output_tokens == 4
        assert row.organization_id == org.id
        assert row.repository_id == repo.id
