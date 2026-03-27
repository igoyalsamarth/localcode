"""Tests for repository bootstrap utilities."""

from decimal import Decimal

import pytest

from services.github.repository_bootstrap import (
    get_or_create_default_model,
    get_or_create_coder_agent,
    get_or_create_review_agent,
    upsert_repository_from_github,
    ensure_default_coder_repository_agent,
    ensure_default_review_repository_agent,
)
from services.github.trigger_modes import TRIGGER_MODE_AUTO, TRIGGER_MODE_TAG
from model.tables import (
    User,
    Organization,
    Model,
    Agent,
    Repository,
    RepositoryAgent,
)
from model.enums import AgentType


@pytest.mark.unit
class TestRepositoryBootstrap:
    """Test repository bootstrap functions."""

    def test_get_or_create_default_model_creates_new(self, db_session):
        """Test creating a new default model."""
        model = get_or_create_default_model(db_session)

        assert model is not None
        assert model.provider == "ollama"
        assert model.name == "kimi-k2.5"
        assert model.input_cost_per_token == Decimal("0.60") / Decimal(1_000_000)
        assert model.output_cost_per_token == Decimal("3.00") / Decimal(1_000_000)

    def test_get_or_create_default_model_returns_existing(self, db_session):
        """Test returning existing default model."""
        model1 = Model(provider="custom", name="custom-model")
        db_session.add(model1)
        db_session.commit()

        model2 = get_or_create_default_model(db_session)

        assert model2.id == model1.id
        assert model2.provider == "custom"

    def test_get_or_create_coder_agent_creates_new(self, db_session):
        """Test creating a new coder agent."""
        user = User(email="test@example.com", auth_provider="github")
        db_session.add(user)
        db_session.flush()

        org = Organization(name="Test Org", owner_user_id=user.id)
        db_session.add(org)
        db_session.flush()

        agent = get_or_create_coder_agent(db_session, org.id)

        assert agent is not None
        assert agent.organization_id == org.id
        assert agent.type == AgentType.code
        assert agent.name == "Code Agent"

    def test_get_or_create_coder_agent_returns_existing(self, db_session):
        """Test returning existing coder agent."""
        user = User(email="test@example.com", auth_provider="github")
        db_session.add(user)
        db_session.flush()

        org = Organization(name="Test Org", owner_user_id=user.id)
        db_session.add(org)
        db_session.flush()

        agent1 = Agent(
            organization_id=org.id,
            name="Existing Code Agent",
            type=AgentType.code,
        )
        db_session.add(agent1)
        db_session.commit()

        agent2 = get_or_create_coder_agent(db_session, org.id)

        assert agent2.id == agent1.id
        assert agent2.name == "Existing Code Agent"

    def test_get_or_create_review_agent_creates_new(self, db_session):
        """Test creating a new review agent."""
        user = User(email="test@example.com", auth_provider="github")
        db_session.add(user)
        db_session.flush()

        org = Organization(name="Test Org", owner_user_id=user.id)
        db_session.add(org)
        db_session.flush()

        agent = get_or_create_review_agent(db_session, org.id)

        assert agent is not None
        assert agent.organization_id == org.id
        assert agent.type == AgentType.review
        assert agent.name == "Review Agent"

    def test_get_or_create_review_agent_returns_existing(self, db_session):
        """Test returning existing review agent."""
        user = User(email="test@example.com", auth_provider="github")
        db_session.add(user)
        db_session.flush()

        org = Organization(name="Test Org", owner_user_id=user.id)
        db_session.add(org)
        db_session.flush()

        agent1 = Agent(
            organization_id=org.id,
            name="Existing Review Agent",
            type=AgentType.review,
        )
        db_session.add(agent1)
        db_session.commit()

        agent2 = get_or_create_review_agent(db_session, org.id)

        assert agent2.id == agent1.id
        assert agent2.name == "Existing Review Agent"

    def test_upsert_repository_from_github_creates_new(self, db_session):
        """Test creating a new repository from GitHub payload."""
        user = User(email="test@example.com", auth_provider="github")
        db_session.add(user)
        db_session.flush()

        org = Organization(name="Test Org", owner_user_id=user.id)
        db_session.add(org)
        db_session.flush()

        github_repo = {
            "id": 12345,
            "name": "test-repo",
            "full_name": "test-owner/test-repo",
            "private": True,
            "default_branch": "main",
        }

        repo = upsert_repository_from_github(db_session, org.id, github_repo)

        assert repo is not None
        assert repo.github_repo_id == 12345
        assert repo.name == "test-repo"
        assert repo.owner == "test-owner"
        assert repo.private is True
        assert repo.default_branch == "main"
        assert repo.active is True

    def test_upsert_repository_from_github_updates_existing(self, db_session):
        """Test updating an existing repository from GitHub payload."""
        user = User(email="test@example.com", auth_provider="github")
        db_session.add(user)
        db_session.flush()

        org = Organization(name="Test Org", owner_user_id=user.id)
        db_session.add(org)
        db_session.flush()

        repo1 = Repository(
            organization_id=org.id,
            github_repo_id=12345,
            name="old-name",
            owner="old-owner",
            default_branch="master",
            private=False,
        )
        db_session.add(repo1)
        db_session.commit()

        github_repo = {
            "id": 12345,
            "name": "new-name",
            "full_name": "new-owner/new-name",
            "private": True,
            "default_branch": "main",
        }

        repo2 = upsert_repository_from_github(db_session, org.id, github_repo)

        assert repo2.id == repo1.id
        assert repo2.name == "new-name"
        assert repo2.owner == "new-owner"
        assert repo2.private is True
        assert repo2.default_branch == "main"

    def test_upsert_repository_from_github_missing_id_raises(self, db_session):
        """Test that missing repository ID raises ValueError."""
        user = User(email="test@example.com", auth_provider="github")
        db_session.add(user)
        db_session.flush()

        org = Organization(name="Test Org", owner_user_id=user.id)
        db_session.add(org)
        db_session.flush()

        github_repo = {"name": "test-repo"}

        with pytest.raises(ValueError, match="missing id"):
            upsert_repository_from_github(db_session, org.id, github_repo)

    def test_upsert_repository_from_github_missing_name_raises(self, db_session):
        """Test that missing repository name raises ValueError."""
        user = User(email="test@example.com", auth_provider="github")
        db_session.add(user)
        db_session.flush()

        org = Organization(name="Test Org", owner_user_id=user.id)
        db_session.add(org)
        db_session.flush()

        github_repo = {"id": 12345}

        with pytest.raises(ValueError, match="missing name"):
            upsert_repository_from_github(db_session, org.id, github_repo)

    def test_upsert_repository_from_github_with_fallback_owner(self, db_session):
        """Test repository creation with fallback owner."""
        user = User(email="test@example.com", auth_provider="github")
        db_session.add(user)
        db_session.flush()

        org = Organization(name="Test Org", owner_user_id=user.id)
        db_session.add(org)
        db_session.flush()

        github_repo = {
            "id": 12345,
            "name": "test-repo",
            "private": False,
        }

        repo = upsert_repository_from_github(
            db_session,
            org.id,
            github_repo,
            account_login_fallback="fallback-owner",
        )

        assert repo.owner == "fallback-owner"

    def test_ensure_default_coder_repository_agent_creates_new(self, db_session):
        """Test creating default coder repository agent."""
        user = User(email="test@example.com", auth_provider="github")
        db_session.add(user)
        db_session.flush()

        org = Organization(name="Test Org", owner_user_id=user.id)
        db_session.add(org)
        db_session.flush()

        repo = Repository(
            organization_id=org.id,
            github_repo_id=12345,
            name="test-repo",
            owner="test-owner",
            default_branch="main",
        )
        db_session.add(repo)
        db_session.flush()

        ensure_default_coder_repository_agent(db_session, repo)
        db_session.commit()

        repo_agent = (
            db_session.query(RepositoryAgent).filter_by(repository_id=repo.id).first()
        )

        assert repo_agent is not None
        assert repo_agent.enabled is True
        assert repo_agent.config_json == {"mode": TRIGGER_MODE_AUTO}
        assert repo_agent.agent.type == AgentType.code

    def test_ensure_default_coder_repository_agent_skips_existing(self, db_session):
        """Test that existing coder repository agent is not duplicated."""
        user = User(email="test@example.com", auth_provider="github")
        db_session.add(user)
        db_session.flush()

        org = Organization(name="Test Org", owner_user_id=user.id)
        db_session.add(org)
        db_session.flush()

        agent = Agent(
            organization_id=org.id,
            name="Code Agent",
            type=AgentType.code,
        )
        db_session.add(agent)
        db_session.flush()

        model = Model(provider="openai", name="gpt-4")
        db_session.add(model)
        db_session.flush()

        repo = Repository(
            organization_id=org.id,
            github_repo_id=12345,
            name="test-repo",
            owner="test-owner",
            default_branch="main",
        )
        db_session.add(repo)
        db_session.flush()

        repo_agent1 = RepositoryAgent(
            repository_id=repo.id,
            agent_id=agent.id,
            model_id=model.id,
            enabled=False,
            config_json={"mode": "manual"},
        )
        db_session.add(repo_agent1)
        db_session.commit()

        ensure_default_coder_repository_agent(db_session, repo)
        db_session.commit()

        count = (
            db_session.query(RepositoryAgent).filter_by(repository_id=repo.id).count()
        )

        assert count == 1

        repo_agent2 = (
            db_session.query(RepositoryAgent).filter_by(repository_id=repo.id).first()
        )
        assert repo_agent2.enabled is False
        assert repo_agent2.config_json == {"mode": "manual"}

    def test_ensure_default_review_repository_agent_creates_new(self, db_session):
        """Test creating default review repository agent."""
        user = User(email="test@example.com", auth_provider="github")
        db_session.add(user)
        db_session.flush()

        org = Organization(name="Test Org", owner_user_id=user.id)
        db_session.add(org)
        db_session.flush()

        repo = Repository(
            organization_id=org.id,
            github_repo_id=12345,
            name="test-repo",
            owner="test-owner",
            default_branch="main",
        )
        db_session.add(repo)
        db_session.flush()

        ensure_default_review_repository_agent(db_session, repo)
        db_session.commit()

        repo_agent = (
            db_session.query(RepositoryAgent).filter_by(repository_id=repo.id).first()
        )

        assert repo_agent is not None
        assert repo_agent.enabled is True
        assert repo_agent.config_json == {"mode": TRIGGER_MODE_AUTO}
        assert repo_agent.agent.type == AgentType.review

    def test_ensure_default_review_repository_agent_skips_existing(self, db_session):
        """Test that existing review repository agent is not duplicated."""
        user = User(email="test@example.com", auth_provider="github")
        db_session.add(user)
        db_session.flush()

        org = Organization(name="Test Org", owner_user_id=user.id)
        db_session.add(org)
        db_session.flush()

        agent = Agent(
            organization_id=org.id,
            name="Review Agent",
            type=AgentType.review,
        )
        db_session.add(agent)
        db_session.flush()

        model = Model(provider="openai", name="gpt-4")
        db_session.add(model)
        db_session.flush()

        repo = Repository(
            organization_id=org.id,
            github_repo_id=12345,
            name="test-repo",
            owner="test-owner",
            default_branch="main",
        )
        db_session.add(repo)
        db_session.flush()

        repo_agent1 = RepositoryAgent(
            repository_id=repo.id,
            agent_id=agent.id,
            model_id=model.id,
            enabled=False,
            config_json={"mode": "manual"},
        )
        db_session.add(repo_agent1)
        db_session.commit()

        ensure_default_review_repository_agent(db_session, repo)
        db_session.commit()

        count = (
            db_session.query(RepositoryAgent).filter_by(repository_id=repo.id).count()
        )

        assert count == 1

        repo_agent2 = (
            db_session.query(RepositoryAgent).filter_by(repository_id=repo.id).first()
        )
        assert repo_agent2.enabled is False
        assert repo_agent2.config_json == {"mode": "manual"}

    def test_constants_values(self):
        """Test that constants have expected values."""
        assert TRIGGER_MODE_AUTO == "auto"
        assert TRIGGER_MODE_TAG == "tag"
