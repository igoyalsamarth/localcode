"""Tests for ``GET /agents/usage``."""

from contextlib import contextmanager
from decimal import Decimal
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from api.jwt_session import create_session_token
from model.enums import GitHubWorkflowKind
from model.tables import (
    AgentWorkflowUsage,
    Organization,
    Repository,
    User,
)
from services.github.workflow_run_id import (
    github_issue_workflow_run_id,
    github_pr_workflow_run_id,
)


@pytest.fixture
def agents_usage_client():
    from app import app

    return TestClient(app)


@pytest.mark.unit
class TestAgentsWorkflowUsageAPI:
    @staticmethod
    def _patched_session_scope(session):
        @contextmanager
        def cm():
            try:
                yield session
                session.commit()
            except Exception:
                session.rollback()
                raise

        return cm

    @staticmethod
    def _seed_user_org_repo_usage(db_session):
        user = User(
            email="agents-usage@example.com",
            username="agentsusage",
            auth_provider="github",
        )
        db_session.add(user)
        db_session.flush()
        org = Organization(
            name="Agents Usage Org",
            is_personal=False,
            created_by_user_id=user.id,
            owner_user_id=user.id,
        )
        db_session.add(org)
        db_session.flush()
        repo = Repository(
            organization_id=org.id,
            github_repo_id=42_001,
            name="svc",
            owner="acme",
            default_branch="main",
        )
        db_session.add(repo)
        db_session.flush()

        def add_row(workflow: GitHubWorkflowKind, item: int, in_tok: int, out_tok: int):
            rid = (
                github_issue_workflow_run_id("acme/svc", item)
                if workflow == GitHubWorkflowKind.code
                else github_pr_workflow_run_id("acme/svc", item)
            )
            db_session.add(
                AgentWorkflowUsage(
                    workflow=workflow,
                    organization_id=org.id,
                    repository_id=repo.id,
                    github_full_name="acme/svc",
                    github_item_number=item,
                    run_id=rid,
                    provider="ollama",
                    model_name="m1",
                    input_tokens=in_tok,
                    output_tokens=out_tok,
                    total_tokens=in_tok + out_tok,
                    cost=Decimal("0.5"),
                )
            )

        add_row(GitHubWorkflowKind.code, 10, 5, 5)
        add_row(GitHubWorkflowKind.code, 10, 3, 3)
        add_row(GitHubWorkflowKind.review, 7, 2, 2)
        db_session.commit()
        return user, org

    def test_usage_code_filter(
        self, agents_usage_client, db_session, mock_env
    ):
        user, org = self._seed_user_org_repo_usage(db_session)
        token = create_session_token(
            user_id=user.id,
            org_id=org.id,
            github_login=None,
        )

        with patch(
            "api.agents.session_scope",
            self._patched_session_scope(db_session),
        ):
            r = agents_usage_client.get(
                "/agents/usage",
                params={"workflow": "code"},
                headers={"Authorization": f"Bearer {token}"},
            )

        assert r.status_code == 200
        data = r.json()
        assert data["summary"]["runCount"] == 2
        assert len(data["repositories"]) == 1
        row = data["repositories"][0]
        assert row["workflow"] == "code"
        assert row["githubFullName"] == "acme/svc"
        assert row["distinctItemCount"] == 1
        assert len(row["items"]) == 1
        assert row["items"][0]["itemNumber"] == 10
        assert row["items"][0]["workflow"] == "code"

    def test_usage_review_filter(
        self, agents_usage_client, db_session, mock_env
    ):
        user, org = self._seed_user_org_repo_usage(db_session)
        token = create_session_token(
            user_id=user.id,
            org_id=org.id,
            github_login=None,
        )

        with patch(
            "api.agents.session_scope",
            self._patched_session_scope(db_session),
        ):
            r = agents_usage_client.get(
                "/agents/usage",
                params={"workflow": "review"},
                headers={"Authorization": f"Bearer {token}"},
            )

        assert r.status_code == 200
        data = r.json()
        assert data["summary"]["runCount"] == 1
        assert len(data["repositories"]) == 1
        assert data["repositories"][0]["workflow"] == "review"
        assert data["repositories"][0]["items"][0]["itemNumber"] == 7

    def test_usage_unfiltered_both_workflows(
        self, agents_usage_client, db_session, mock_env
    ):
        user, org = self._seed_user_org_repo_usage(db_session)
        token = create_session_token(
            user_id=user.id,
            org_id=org.id,
            github_login=None,
        )

        with patch(
            "api.agents.session_scope",
            self._patched_session_scope(db_session),
        ):
            r = agents_usage_client.get(
                "/agents/usage",
                headers={"Authorization": f"Bearer {token}"},
            )

        assert r.status_code == 200
        data = r.json()
        assert data["summary"]["runCount"] == 3
        workflows = {row["workflow"] for row in data["repositories"]}
        assert workflows == {"code", "review"}
