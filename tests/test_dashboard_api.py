"""Tests for ``GET /dashboard``."""

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from api.jwt_session import create_session_token
from model.enums import AgentType, GitHubWorkflowKind, MemberRole
from model.tables import (
    Agent,
    AgentWorkflowUsage,
    Model,
    Organization,
    OrganizationMember,
    Repository,
    RepositoryAgent,
    User,
)
from services.github.workflow_run_id import (
    github_issue_workflow_run_id,
    github_pr_workflow_run_id,
)


@pytest.fixture
def dashboard_client():
    from app import app

    return TestClient(app)


@pytest.mark.unit
class TestDashboardAPI:
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
    def _seed_dashboard_data(db_session):
        owner = User(email="dash-owner@example.com", username="dashowner", auth_provider="github")
        db_session.add(owner)
        db_session.flush()
        member_user = User(
            email="dash-member@example.com", username="dashmember", auth_provider="github"
        )
        db_session.add(member_user)
        db_session.flush()

        org = Organization(
            name="Dash Org",
            is_personal=False,
            created_by_user_id=owner.id,
            owner_user_id=owner.id,
        )
        db_session.add(org)
        db_session.flush()

        db_session.add(
            OrganizationMember(
                organization_id=org.id, user_id=owner.id, role=MemberRole.admin
            )
        )
        db_session.add(
            OrganizationMember(
                organization_id=org.id, user_id=member_user.id, role=MemberRole.user
            )
        )

        model = Model(provider="openai", name="gpt-4")
        db_session.add(model)
        db_session.flush()

        repo = Repository(
            organization_id=org.id,
            github_repo_id=99_001,
            name="svc",
            owner="acme",
            default_branch="main",
        )
        db_session.add(repo)
        db_session.flush()

        agent_code = Agent(
            organization_id=org.id,
            name="Code Agent",
            type=AgentType.code,
        )
        agent_review = Agent(
            organization_id=org.id,
            name="Review Agent",
            type=AgentType.review,
        )
        db_session.add_all([agent_code, agent_review])
        db_session.flush()

        db_session.add(
            RepositoryAgent(
                repository_id=repo.id,
                agent_id=agent_code.id,
                model_id=model.id,
                enabled=True,
            )
        )
        db_session.add(
            RepositoryAgent(
                repository_id=repo.id,
                agent_id=agent_review.id,
                model_id=model.id,
                enabled=False,
            )
        )

        now = datetime.now(timezone.utc)
        old = now - timedelta(hours=48)

        def usage_row(workflow: GitHubWorkflowKind, item: int, created_at: datetime):
            rid = (
                github_issue_workflow_run_id("acme/svc", item)
                if workflow == GitHubWorkflowKind.code
                else github_pr_workflow_run_id("acme/svc", item)
            )
            return AgentWorkflowUsage(
                workflow=workflow,
                organization_id=org.id,
                repository_id=repo.id,
                github_full_name="acme/svc",
                github_item_number=item,
                run_id=rid,
                provider="ollama",
                model_name="m1",
                input_tokens=1,
                output_tokens=1,
                total_tokens=2,
                cost=Decimal("0"),
                created_at=created_at,
            )

        db_session.add(usage_row(GitHubWorkflowKind.code, 1, old))
        db_session.add(usage_row(GitHubWorkflowKind.review, 2, now - timedelta(seconds=2)))
        db_session.add(usage_row(GitHubWorkflowKind.code, 3, now))

        db_session.commit()
        return owner, org

    def test_dashboard_stats(
        self, dashboard_client, db_session, mock_env
    ):
        owner, _org = self._seed_dashboard_data(db_session)
        token = create_session_token(
            user_id=owner.id,
            org_id=_org.id,
            github_login=None,
        )

        with patch(
            "api.dashboard.session_scope",
            self._patched_session_scope(db_session),
        ):
            r = dashboard_client.get(
                "/dashboard",
                headers={"Authorization": f"Bearer {token}"},
            )

        assert r.status_code == 200
        data = r.json()
        assert data["activeAgentsCount"] == 1
        assert data["teamMemberCount"] == 2
        assert data["activityLast24Hours"] == 2
        assert len(data["recentActivity"]) == 3
        assert data["workspaceRole"] == "admin"
        assert data["recentActivity"][0]["workflow"] == "code"
        assert data["recentActivity"][0]["itemNumber"] == 3
        assert data["recentActivity"][0]["githubFullName"] == "acme/svc"
        assert data["recentActivity"][1]["itemNumber"] == 2

    def test_dashboard_requires_auth(self, dashboard_client, mock_env):
        r = dashboard_client.get("/dashboard")
        assert r.status_code == 401
