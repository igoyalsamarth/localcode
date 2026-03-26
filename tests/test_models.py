"""Tests for SQLAlchemy ORM models."""

import pytest
from decimal import Decimal

from model.tables import (
    User,
    Organization,
    OrganizationMember,
    Repository,
    GitHubInstallation,
    Model,
    Agent,
    Subscription,
)
from model.enums import (
    MemberRole,
    AgentType,
    SubscriptionStatus,
    BillingCycle,
)


@pytest.mark.unit
class TestModels:
    """Test ORM model creation and relationships."""

    def test_user_model_creation(self, db_session):
        """Test User model creation."""
        user = User(
            email="test@example.com",
            username="testuser",
            name="Test User",
            github_user_id=12345,
            github_login="testuser",
            auth_provider="github",
        )
        db_session.add(user)
        db_session.commit()

        assert user.id is not None
        assert user.email == "test@example.com"
        assert user.github_user_id == 12345
        assert user.created_at is not None

    def test_organization_model_creation(self, db_session):
        """Test Organization model creation."""
        user = User(
            email="test@example.com",
            auth_provider="github",
        )
        db_session.add(user)
        db_session.flush()

        org = Organization(
            name="Test Org",
            owner_user_id=user.id,
            github_installation_id=12345,
        )
        db_session.add(org)
        db_session.commit()

        assert org.id is not None
        assert org.name == "Test Org"
        assert org.owner_user_id == user.id
        assert org.created_at is not None

    def test_organization_member_model_creation(self, db_session):
        """Test OrganizationMember model creation."""
        user = User(email="test@example.com", auth_provider="github")
        db_session.add(user)
        db_session.flush()

        org = Organization(name="Test Org", owner_user_id=user.id)
        db_session.add(org)
        db_session.flush()

        member = OrganizationMember(
            organization_id=org.id,
            user_id=user.id,
            role=MemberRole.owner,
        )
        db_session.add(member)
        db_session.commit()

        assert member.id is not None
        assert member.role == MemberRole.owner

    def test_repository_model_creation(self, db_session):
        """Test Repository model creation."""
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
            private=True,
            default_branch="main",
        )
        db_session.add(repo)
        db_session.commit()

        assert repo.id is not None
        assert repo.name == "test-repo"
        assert repo.private is True

    def test_github_installation_model_creation(self, db_session):
        """Test GitHubInstallation model creation."""
        user = User(email="test@example.com", auth_provider="github")
        db_session.add(user)
        db_session.flush()

        org = Organization(name="Test Org", owner_user_id=user.id)
        db_session.add(org)
        db_session.flush()

        installation = GitHubInstallation(
            organization_id=org.id,
            github_installation_id=12345,
            account_name="test-account",
        )
        db_session.add(installation)
        db_session.commit()

        assert installation.id is not None
        assert installation.github_installation_id == 12345

    def test_model_creation(self, db_session):
        """Test Model (ML model) creation."""
        model = Model(
            provider="openai",
            name="gpt-4",
            input_cost_per_token=Decimal("0.00003"),
            output_cost_per_token=Decimal("0.00006"),
        )
        db_session.add(model)
        db_session.commit()

        assert model.id is not None
        assert model.provider == "openai"
        assert model.input_cost_per_token == Decimal("0.00003")

    def test_agent_model_creation(self, db_session):
        """Test Agent model creation."""
        user = User(email="test@example.com", auth_provider="github")
        db_session.add(user)
        db_session.flush()

        org = Organization(name="Test Org", owner_user_id=user.id)
        db_session.add(org)
        db_session.flush()

        agent = Agent(
            organization_id=org.id,
            name="Test Agent",
            type=AgentType.code,
            price_monthly=Decimal("99.99"),
        )
        db_session.add(agent)
        db_session.commit()

        assert agent.id is not None
        assert agent.type == AgentType.code

    def test_subscription_model_creation(self, db_session):
        """Test Subscription model creation."""
        user = User(email="test@example.com", auth_provider="github")
        db_session.add(user)
        db_session.flush()

        org = Organization(name="Test Org", owner_user_id=user.id)
        db_session.add(org)
        db_session.flush()

        subscription = Subscription(
            organization_id=org.id,
            status=SubscriptionStatus.active,
            billing_cycle=BillingCycle.monthly,
        )
        db_session.add(subscription)
        db_session.commit()

        assert subscription.id is not None
        assert subscription.status == SubscriptionStatus.active

    def test_user_organization_relationship(self, db_session):
        """Test User-Organization relationship."""
        user = User(email="test@example.com", auth_provider="github")
        db_session.add(user)
        db_session.flush()

        org = Organization(name="Test Org", owner_user_id=user.id)
        db_session.add(org)
        db_session.commit()

        assert org.owner.id == user.id
        assert len(user.owned_organizations) == 1
        assert user.owned_organizations[0].id == org.id
