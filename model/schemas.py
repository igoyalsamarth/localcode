"""
Pydantic schemas mirroring ORM models. Use model_config(from_attributes=True)
for ORM -> schema conversion. Shared enums in model.enums.
"""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from model.enums import (
    AgentType,
    BillingCycle,
    CommentSeverity,
    MemberRole,
    ReviewFileStatus,
    ReviewStatus,
    SubscriptionStatus,
    TriggeredBy,
)


def _orm_config() -> ConfigDict:
    return ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# Users & Organizations
# ---------------------------------------------------------------------------


class UserBase(BaseModel):
    email: str
    name: str | None = None
    github_user_id: int | None = None
    github_login: str | None = None
    avatar_url: str | None = None
    auth_provider: str


class UserCreate(UserBase):
    pass


class User(UserBase):
    model_config = _orm_config()

    id: UUID
    created_at: datetime | None = None


class OrganizationBase(BaseModel):
    name: str
    owner_user_id: UUID
    github_installation_id: int | None = None


class OrganizationCreate(OrganizationBase):
    pass


class Organization(OrganizationBase):
    model_config = _orm_config()

    id: UUID
    created_at: datetime | None = None


class OrganizationMemberBase(BaseModel):
    organization_id: UUID
    user_id: UUID
    role: MemberRole


class OrganizationMemberCreate(OrganizationMemberBase):
    pass


class OrganizationMember(OrganizationMemberBase):
    model_config = _orm_config()

    id: UUID
    created_at: datetime | None = None


# ---------------------------------------------------------------------------
# GitHub
# ---------------------------------------------------------------------------


class GitHubInstallationBase(BaseModel):
    organization_id: UUID
    github_installation_id: int
    account_name: str
    access_token_encrypted: str | None = None


class GitHubInstallationCreate(GitHubInstallationBase):
    pass


class GitHubInstallation(GitHubInstallationBase):
    model_config = _orm_config()

    id: UUID
    created_at: datetime | None = None


class RepositoryBase(BaseModel):
    organization_id: UUID
    github_repo_id: int
    name: str
    owner: str
    private: bool = False
    default_branch: str
    active: bool = True


class RepositoryCreate(RepositoryBase):
    pass


class Repository(RepositoryBase):
    model_config = _orm_config()

    id: UUID
    created_at: datetime | None = None


# ---------------------------------------------------------------------------
# Agents & Models
# ---------------------------------------------------------------------------


class ModelBase(BaseModel):
    provider: str
    name: str
    input_cost_per_token: Decimal = Decimal("0")
    output_cost_per_token: Decimal = Decimal("0")


class ModelCreate(ModelBase):
    pass


class Model(ModelBase):
    model_config = _orm_config()

    id: UUID


class AgentBase(BaseModel):
    organization_id: UUID
    name: str
    type: AgentType
    price_monthly: Decimal | None = None


class AgentCreate(AgentBase):
    pass


class Agent(AgentBase):
    model_config = _orm_config()

    id: UUID
    created_at: datetime | None = None


class RepositoryAgentBase(BaseModel):
    repository_id: UUID
    agent_id: UUID
    model_id: UUID
    enabled: bool = True
    config_json: dict | None = None


class RepositoryAgentCreate(RepositoryAgentBase):
    pass


class RepositoryAgent(RepositoryAgentBase):
    model_config = _orm_config()

    id: UUID
    created_at: datetime | None = None


class OrganizationModelKeyBase(BaseModel):
    organization_id: UUID
    provider: str
    encrypted_api_key: str
    is_active: bool = True


class OrganizationModelKeyCreate(OrganizationModelKeyBase):
    pass


class OrganizationModelKey(OrganizationModelKeyBase):
    model_config = _orm_config()

    id: UUID
    created_at: datetime | None = None


# ---------------------------------------------------------------------------
# Pull Requests & Reviews
# ---------------------------------------------------------------------------


class PullRequestBase(BaseModel):
    repository_id: UUID
    github_pr_id: int
    number: int
    title: str
    author: str
    base_branch: str
    head_branch: str


class PullRequestCreate(PullRequestBase):
    pass


class PullRequest(PullRequestBase):
    model_config = _orm_config()

    id: UUID
    created_at: datetime | None = None


class ReviewRunBase(BaseModel):
    pull_request_id: UUID
    agent_id: UUID
    repository_id: UUID
    status: ReviewStatus = ReviewStatus.queued
    triggered_by: TriggeredBy
    model_id: UUID
    started_at: datetime | None = None
    completed_at: datetime | None = None


class ReviewRunCreate(ReviewRunBase):
    pass


class ReviewRun(ReviewRunBase):
    model_config = _orm_config()

    id: UUID


class ReviewFileBase(BaseModel):
    review_run_id: UUID
    file_path: str
    additions: int = 0
    deletions: int = 0
    status: ReviewFileStatus = ReviewFileStatus.pending


class ReviewFileCreate(ReviewFileBase):
    pass


class ReviewFile(ReviewFileBase):
    model_config = _orm_config()

    id: UUID


class ReviewCommentBase(BaseModel):
    review_run_id: UUID
    file_path: str
    line_number: int | None = None
    comment: str
    severity: CommentSeverity = CommentSeverity.info


class ReviewCommentCreate(ReviewCommentBase):
    pass


class ReviewComment(ReviewCommentBase):
    model_config = _orm_config()

    id: UUID
    created_at: datetime | None = None


class TokenUsageBase(BaseModel):
    review_run_id: UUID
    organization_id: UUID
    model_id: UUID
    input_tokens: int = 0
    output_tokens: int = 0
    cost: Decimal = Decimal("0")


class TokenUsageCreate(TokenUsageBase):
    pass


class TokenUsage(TokenUsageBase):
    model_config = _orm_config()

    id: UUID
    created_at: datetime | None = None


# ---------------------------------------------------------------------------
# Subscriptions
# ---------------------------------------------------------------------------


class SubscriptionBase(BaseModel):
    organization_id: UUID
    status: SubscriptionStatus
    billing_cycle: BillingCycle


class SubscriptionCreate(SubscriptionBase):
    pass


class Subscription(SubscriptionBase):
    model_config = _orm_config()

    id: UUID
    created_at: datetime | None = None


class SubscriptionAgentBase(BaseModel):
    subscription_id: UUID
    agent_id: UUID
    price: Decimal
    active: bool = True


class SubscriptionAgentCreate(SubscriptionAgentBase):
    pass


class SubscriptionAgent(SubscriptionAgentBase):
    model_config = _orm_config()

    id: UUID
    created_at: datetime | None = None


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------


class GitHubEventBase(BaseModel):
    installation_id: int
    event_type: str
    payload_json: dict
    processed: bool = False


class GitHubEventCreate(GitHubEventBase):
    pass


class GitHubEvent(GitHubEventBase):
    model_config = _orm_config()

    id: UUID
    created_at: datetime | None = None
