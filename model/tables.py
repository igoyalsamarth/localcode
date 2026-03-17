"""SQLAlchemy ORM models. Shared enums in model.enums."""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.client import Base
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


def uuid4_default() -> uuid.UUID:
    return uuid.uuid4()


# ---------------------------------------------------------------------------
# Users & Organizations
# ---------------------------------------------------------------------------


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid4_default,
    )
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    github_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True, unique=True, index=True)
    github_login: Mapped[str | None] = mapped_column(String(255), nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    auth_provider: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    owned_organizations: Mapped[list["Organization"]] = relationship(
        "Organization", back_populates="owner", foreign_keys="Organization.owner_user_id"
    )
    organization_memberships: Mapped[list["OrganizationMember"]] = relationship(
        "OrganizationMember", back_populates="user"
    )


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid4_default,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    github_installation_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    owner: Mapped["User"] = relationship("User", back_populates="owned_organizations")
    members: Mapped[list["OrganizationMember"]] = relationship(
        "OrganizationMember", back_populates="organization"
    )
    github_installations: Mapped[list["GitHubInstallation"]] = relationship(
        "GitHubInstallation", back_populates="organization"
    )
    repositories: Mapped[list["Repository"]] = relationship(
        "Repository", back_populates="organization"
    )
    agents: Mapped[list["Agent"]] = relationship("Agent", back_populates="organization")
    model_keys: Mapped[list["OrganizationModelKey"]] = relationship(
        "OrganizationModelKey", back_populates="organization"
    )
    subscriptions: Mapped[list["Subscription"]] = relationship(
        "Subscription", back_populates="organization"
    )


class OrganizationMember(Base):
    __tablename__ = "organization_members"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid4_default,
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[MemberRole] = mapped_column(
        Enum(MemberRole),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    organization: Mapped["Organization"] = relationship(
        "Organization", back_populates="members"
    )
    user: Mapped["User"] = relationship(
        "User", back_populates="organization_memberships"
    )

    __table_args__ = (
        Index("ix_organization_members_org_user", "organization_id", "user_id", unique=True),
    )


# ---------------------------------------------------------------------------
# GitHub
# ---------------------------------------------------------------------------


class GitHubInstallation(Base):
    __tablename__ = "github_installations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid4_default,
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    github_installation_id: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        unique=True,
        index=True,
    )
    account_name: Mapped[str] = mapped_column(String(255), nullable=False)
    access_token_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    organization: Mapped["Organization"] = relationship(
        "Organization", back_populates="github_installations"
    )


class Repository(Base):
    __tablename__ = "repositories"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid4_default,
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    github_repo_id: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    owner: Mapped[str] = mapped_column(String(255), nullable=False)
    private: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    default_branch: Mapped[str] = mapped_column(String(255), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    organization: Mapped["Organization"] = relationship(
        "Organization", back_populates="repositories"
    )
    repository_agents: Mapped[list["RepositoryAgent"]] = relationship(
        "RepositoryAgent", back_populates="repository"
    )
    pull_requests: Mapped[list["PullRequest"]] = relationship(
        "PullRequest", back_populates="repository"
    )
    review_runs: Mapped[list["ReviewRun"]] = relationship(
        "ReviewRun", back_populates="repository"
    )

    __table_args__ = (
        Index("ix_repositories_org_github_repo", "organization_id", "github_repo_id", unique=True),
    )


# ---------------------------------------------------------------------------
# Agents & Models
# ---------------------------------------------------------------------------


class Model(Base):
    """ML model catalog (e.g. gpt-4, claude-3)."""

    __tablename__ = "models"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid4_default,
    )
    provider: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    input_cost_per_token: Mapped[Decimal] = mapped_column(Numeric(18, 12), default=0)
    output_cost_per_token: Mapped[Decimal] = mapped_column(Numeric(18, 12), default=0)

    repository_agents: Mapped[list["RepositoryAgent"]] = relationship(
        "RepositoryAgent", back_populates="model"
    )
    review_runs: Mapped[list["ReviewRun"]] = relationship(
        "ReviewRun", back_populates="model"
    )
    token_usage: Mapped[list["TokenUsage"]] = relationship(
        "TokenUsage", back_populates="model"
    )


class Agent(Base):
    __tablename__ = "agents"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid4_default,
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    type: Mapped[AgentType] = mapped_column(Enum(AgentType), nullable=False)
    price_monthly: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    organization: Mapped["Organization"] = relationship(
        "Organization", back_populates="agents"
    )
    repository_agents: Mapped[list["RepositoryAgent"]] = relationship(
        "RepositoryAgent", back_populates="agent"
    )
    review_runs: Mapped[list["ReviewRun"]] = relationship(
        "ReviewRun", back_populates="agent"
    )
    subscription_agents: Mapped[list["SubscriptionAgent"]] = relationship(
        "SubscriptionAgent", back_populates="agent"
    )


class RepositoryAgent(Base):
    __tablename__ = "repository_agents"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid4_default,
    )
    repository_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("repositories.id", ondelete="CASCADE"),
        nullable=False,
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
    )
    model_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("models.id", ondelete="RESTRICT"),
        nullable=False,
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    config_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    repository: Mapped["Repository"] = relationship(
        "Repository", back_populates="repository_agents"
    )
    agent: Mapped["Agent"] = relationship("Agent", back_populates="repository_agents")
    model: Mapped["Model"] = relationship("Model", back_populates="repository_agents")


class OrganizationModelKey(Base):
    __tablename__ = "organization_model_keys"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid4_default,
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    encrypted_api_key: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    organization: Mapped["Organization"] = relationship(
        "Organization", back_populates="model_keys"
    )

    __table_args__ = (
        Index("ix_org_model_keys_org_provider", "organization_id", "provider", unique=True),
    )


# ---------------------------------------------------------------------------
# Pull Requests & Reviews
# ---------------------------------------------------------------------------


class PullRequest(Base):
    __tablename__ = "pull_requests"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid4_default,
    )
    repository_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("repositories.id", ondelete="CASCADE"),
        nullable=False,
    )
    github_pr_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    author: Mapped[str] = mapped_column(String(255), nullable=False)
    base_branch: Mapped[str] = mapped_column(String(255), nullable=False)
    head_branch: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    repository: Mapped["Repository"] = relationship(
        "Repository", back_populates="pull_requests"
    )
    review_runs: Mapped[list["ReviewRun"]] = relationship(
        "ReviewRun", back_populates="pull_request"
    )


class ReviewRun(Base):
    __tablename__ = "review_runs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid4_default,
    )
    pull_request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("pull_requests.id", ondelete="CASCADE"),
        nullable=False,
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
    )
    repository_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("repositories.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[ReviewStatus] = mapped_column(
        Enum(ReviewStatus),
        nullable=False,
        default=ReviewStatus.queued,
    )
    triggered_by: Mapped[TriggeredBy] = mapped_column(
        Enum(TriggeredBy),
        nullable=False,
    )
    model_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("models.id", ondelete="RESTRICT"),
        nullable=False,
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    pull_request: Mapped["PullRequest"] = relationship(
        "PullRequest", back_populates="review_runs"
    )
    agent: Mapped["Agent"] = relationship("Agent", back_populates="review_runs")
    repository: Mapped["Repository"] = relationship(
        "Repository", back_populates="review_runs"
    )
    model: Mapped["Model"] = relationship("Model", back_populates="review_runs")
    review_files: Mapped[list["ReviewFile"]] = relationship(
        "ReviewFile", back_populates="review_run"
    )
    review_comments: Mapped[list["ReviewComment"]] = relationship(
        "ReviewComment", back_populates="review_run"
    )
    token_usage: Mapped[list["TokenUsage"]] = relationship(
        "TokenUsage", back_populates="review_run"
    )


class ReviewFile(Base):
    __tablename__ = "review_files"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid4_default,
    )
    review_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("review_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    file_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    additions: Mapped[int] = mapped_column(Integer, default=0)
    deletions: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[ReviewFileStatus] = mapped_column(
        Enum(ReviewFileStatus),
        nullable=False,
        default=ReviewFileStatus.pending,
    )

    review_run: Mapped["ReviewRun"] = relationship(
        "ReviewRun", back_populates="review_files"
    )


class ReviewComment(Base):
    __tablename__ = "review_comments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid4_default,
    )
    review_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("review_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    file_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    line_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    comment: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[CommentSeverity] = mapped_column(
        Enum(CommentSeverity),
        nullable=False,
        default=CommentSeverity.info,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    review_run: Mapped["ReviewRun"] = relationship(
        "ReviewRun", back_populates="review_comments"
    )


class TokenUsage(Base):
    __tablename__ = "token_usage"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid4_default,
    )
    review_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("review_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    model_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("models.id", ondelete="RESTRICT"),
        nullable=False,
    )
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost: Mapped[Decimal] = mapped_column(Numeric(18, 8), default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    review_run: Mapped["ReviewRun"] = relationship(
        "ReviewRun", back_populates="token_usage"
    )
    model: Mapped["Model"] = relationship("Model", back_populates="token_usage")


# ---------------------------------------------------------------------------
# Subscriptions
# ---------------------------------------------------------------------------


class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid4_default,
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[SubscriptionStatus] = mapped_column(
        Enum(SubscriptionStatus),
        nullable=False,
    )
    billing_cycle: Mapped[BillingCycle] = mapped_column(
        Enum(BillingCycle),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    organization: Mapped["Organization"] = relationship(
        "Organization", back_populates="subscriptions"
    )
    subscription_agents: Mapped[list["SubscriptionAgent"]] = relationship(
        "SubscriptionAgent", back_populates="subscription"
    )


class SubscriptionAgent(Base):
    __tablename__ = "subscription_agents"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid4_default,
    )
    subscription_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("subscriptions.id", ondelete="CASCADE"),
        nullable=False,
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
    )
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    subscription: Mapped["Subscription"] = relationship(
        "Subscription", back_populates="subscription_agents"
    )
    agent: Mapped["Agent"] = relationship("Agent", back_populates="subscription_agents")


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------


class GitHubEvent(Base):
    __tablename__ = "github_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid4_default,
    )
    installation_id: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        index=True,
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    payload_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    processed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
