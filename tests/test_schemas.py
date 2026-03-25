"""Tests for Pydantic schemas."""

import pytest
from datetime import datetime
from decimal import Decimal
from uuid import uuid4

from model.schemas import (
    User,
    UserCreate,
    Organization,
    OrganizationCreate,
    Repository,
    RepositoryCreate,
    PullRequest,
    PullRequestCreate,
    ReviewRun,
    ReviewRunCreate,
    OnboardingRequest,
)
from model.enums import (
    AgentType,
    ReviewStatus,
    TriggeredBy,
)


@pytest.mark.unit
class TestSchemas:
    """Test Pydantic schema validation."""

    def test_user_create_schema(self):
        """Test UserCreate schema validation."""
        user_data = {
            "email": "test@example.com",
            "username": "testuser",
            "name": "Test User",
            "bio": "Test bio",
            "github_user_id": 12345,
            "github_login": "testuser",
            "avatar_url": "https://github.com/avatar.png",
            "auth_provider": "github",
            "onboarded": False,
        }
        
        user = UserCreate(**user_data)
        
        assert user.email == "test@example.com"
        assert user.username == "testuser"
        assert user.github_user_id == 12345
        assert user.onboarded is False

    def test_user_schema(self):
        """Test User schema with ID and timestamp."""
        user_id = uuid4()
        created_at = datetime.now()
        
        user_data = {
            "id": user_id,
            "email": "test@example.com",
            "username": "testuser",
            "name": "Test User",
            "auth_provider": "github",
            "created_at": created_at,
        }
        
        user = User(**user_data)
        
        assert user.id == user_id
        assert user.email == "test@example.com"
        assert user.created_at == created_at

    def test_organization_create_schema(self):
        """Test OrganizationCreate schema validation."""
        owner_id = uuid4()
        
        org_data = {
            "name": "Test Org",
            "owner_user_id": owner_id,
            "github_installation_id": 12345,
        }
        
        org = OrganizationCreate(**org_data)
        
        assert org.name == "Test Org"
        assert org.owner_user_id == owner_id
        assert org.github_installation_id == 12345

    def test_organization_schema(self):
        """Test Organization schema with ID and timestamp."""
        org_id = uuid4()
        owner_id = uuid4()
        created_at = datetime.now()
        
        org_data = {
            "id": org_id,
            "name": "Test Org",
            "owner_user_id": owner_id,
            "created_at": created_at,
        }
        
        org = Organization(**org_data)
        
        assert org.id == org_id
        assert org.name == "Test Org"
        assert org.created_at == created_at

    def test_repository_create_schema(self):
        """Test RepositoryCreate schema validation."""
        org_id = uuid4()
        
        repo_data = {
            "organization_id": org_id,
            "github_repo_id": 12345,
            "name": "test-repo",
            "owner": "test-owner",
            "private": True,
            "default_branch": "main",
            "active": True,
        }
        
        repo = RepositoryCreate(**repo_data)
        
        assert repo.name == "test-repo"
        assert repo.owner == "test-owner"
        assert repo.private is True
        assert repo.default_branch == "main"

    def test_pull_request_create_schema(self):
        """Test PullRequestCreate schema validation."""
        repo_id = uuid4()
        
        pr_data = {
            "repository_id": repo_id,
            "github_pr_id": 12345,
            "number": 123,
            "title": "Test PR",
            "author": "testuser",
            "base_branch": "main",
            "head_branch": "feature",
        }
        
        pr = PullRequestCreate(**pr_data)
        
        assert pr.number == 123
        assert pr.title == "Test PR"
        assert pr.base_branch == "main"
        assert pr.head_branch == "feature"

    def test_review_run_create_schema(self):
        """Test ReviewRunCreate schema validation."""
        pr_id = uuid4()
        agent_id = uuid4()
        repo_id = uuid4()
        model_id = uuid4()
        
        review_data = {
            "pull_request_id": pr_id,
            "agent_id": agent_id,
            "repository_id": repo_id,
            "status": ReviewStatus.queued,
            "triggered_by": TriggeredBy.webhook,
            "model_id": model_id,
        }
        
        review = ReviewRunCreate(**review_data)
        
        assert review.status == ReviewStatus.queued
        assert review.triggered_by == TriggeredBy.webhook
        assert review.pull_request_id == pr_id

    def test_review_run_schema_with_timestamps(self):
        """Test ReviewRun schema with timestamps."""
        pr_id = uuid4()
        agent_id = uuid4()
        repo_id = uuid4()
        model_id = uuid4()
        review_id = uuid4()
        started_at = datetime.now()
        
        review_data = {
            "id": review_id,
            "pull_request_id": pr_id,
            "agent_id": agent_id,
            "repository_id": repo_id,
            "status": ReviewStatus.running,
            "triggered_by": TriggeredBy.user,
            "model_id": model_id,
            "started_at": started_at,
        }
        
        review = ReviewRun(**review_data)
        
        assert review.id == review_id
        assert review.status == ReviewStatus.running
        assert review.started_at == started_at
        assert review.completed_at is None

    def test_onboarding_request_schema(self):
        """Test OnboardingRequest schema validation."""
        onboarding_data = {
            "organization": "Test Org",
            "username": "testuser",
            "fullName": "Test User",
            "bio": "Test bio",
        }
        
        onboarding = OnboardingRequest(**onboarding_data)
        
        assert onboarding.organization == "Test Org"
        assert onboarding.username == "testuser"
        assert onboarding.fullName == "Test User"
        assert onboarding.bio == "Test bio"

    def test_onboarding_request_optional_fields(self):
        """Test OnboardingRequest with optional fields."""
        onboarding_data = {
            "organization": "Test Org",
            "username": "testuser",
        }
        
        onboarding = OnboardingRequest(**onboarding_data)
        
        assert onboarding.organization == "Test Org"
        assert onboarding.username == "testuser"
        assert onboarding.fullName is None
        assert onboarding.bio is None

    def test_schema_with_decimal_fields(self):
        """Test schemas with Decimal fields."""
        from model.schemas import ModelCreate
        
        model_data = {
            "provider": "openai",
            "name": "gpt-4",
            "input_cost_per_token": Decimal("0.00003"),
            "output_cost_per_token": Decimal("0.00006"),
        }
        
        model = ModelCreate(**model_data)
        
        assert model.provider == "openai"
        assert model.input_cost_per_token == Decimal("0.00003")
        assert model.output_cost_per_token == Decimal("0.00006")
