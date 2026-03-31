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
    GitHubWorkflowKind,
    MemberRole,
    SubscriptionStatus,
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
    username: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True, index=True)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    bio: Mapped[str | None] = mapped_column(String(160), nullable=True)
    github_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True, unique=True, index=True)
    github_login: Mapped[str | None] = mapped_column(String(255), nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    auth_provider: Mapped[str] = mapped_column(String(64), nullable=False)
    onboarded: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
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
    dodo_customer_id: Mapped[str | None] = mapped_column(
        String(128), unique=True, nullable=True, index=True
    )
    wallet_balance_usd: Mapped[Decimal] = mapped_column(
        Numeric(18, 8), nullable=False, default=Decimal("0")
    )
    promotional_balance_usd: Mapped[Decimal] = mapped_column(
        Numeric(18, 8), nullable=False, default=Decimal("0")
    )
    promotional_balance_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
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
        # VARCHAR, not PostgreSQL CREATE TYPE — avoids races when many workers call create_all().
        Enum(MemberRole, native_enum=False, length=16),
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
    account_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    account_avatar_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    permissions: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
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
    agent_workflow_usage: Mapped[list["AgentWorkflowUsage"]] = relationship(
        "AgentWorkflowUsage", back_populates="model"
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
    type: Mapped[AgentType] = mapped_column(
        Enum(AgentType, native_enum=False, length=16),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    organization: Mapped["Organization"] = relationship(
        "Organization", back_populates="agents"
    )
    repository_agents: Mapped[list["RepositoryAgent"]] = relationship(
        "RepositoryAgent", back_populates="agent"
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


# ---------------------------------------------------------------------------
# GitHub deep-agent usage (billing / analytics)
# ---------------------------------------------------------------------------


class AgentWorkflowUsage(Base):
    """
    Token usage for one GitHub deep-agent run (issue coding or PR review).

    ``workflow`` distinguishes rows for the frontend and analytics. ``github_item_number``
    is the GitHub issue number when ``workflow`` is ``code``, or the PR number when it is
    ``review``.
    """

    __tablename__ = "agent_workflow_usage"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid4_default,
    )
    workflow: Mapped[GitHubWorkflowKind] = mapped_column(
        Enum(GitHubWorkflowKind, native_enum=False, length=16),
        nullable=False,
        index=True,
    )
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    repository_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("repositories.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    github_full_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    github_item_number: Mapped[int] = mapped_column(Integer, nullable=False)
    run_id: Mapped[str] = mapped_column(
        String(512),
        nullable=False,
        index=True,
        doc=(
            "Stable workflow key (repo + issue or PR). Re-runs share the same value; "
            "row ``id`` is unique per execution."
        ),
    )
    provider: Mapped[str] = mapped_column(String(64), nullable=False, default="ollama")
    model_name: Mapped[str] = mapped_column(
        String(256),
        nullable=False,
        doc="Primary model id for billing (comma-separated if multiple)",
    )
    model_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("models.id", ondelete="SET NULL"),
        nullable=True,
    )
    input_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    usage_by_model: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    cost: Mapped[Decimal] = mapped_column(
        Numeric(18, 8),
        default=0,
        nullable=False,
        doc="Billed amount (USD): same as wallet debit formula on token-derived LLM cost.",
    )
    credits_charged_usd: Mapped[Decimal] = mapped_column(
        Numeric(18, 8),
        nullable=False,
        default=Decimal("0"),
        doc="Actually debited from the org wallet (0 if no organization on the row).",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    organization: Mapped["Organization | None"] = relationship()
    repository: Mapped["Repository | None"] = relationship()
    model: Mapped["Model | None"] = relationship("Model", back_populates="agent_workflow_usage")


# ---------------------------------------------------------------------------
# Subscriptions (Dodo-backed; rows appear when checkout completes / webhooks fire)
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
        index=True,
    )
    dodo_subscription_id: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    dodo_product_id: Mapped[str] = mapped_column(String(128), nullable=False)
    dodo_quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[SubscriptionStatus] = mapped_column(
        Enum(SubscriptionStatus, native_enum=False, length=24),
        nullable=False,
    )
    billing_cycle: Mapped[BillingCycle] = mapped_column(
        Enum(BillingCycle, native_enum=False, length=16),
        nullable=False,
    )
    current_period_end: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    organization: Mapped["Organization"] = relationship(
        "Organization", back_populates="subscriptions"
    )


# ---------------------------------------------------------------------------
# Dodo webhook idempotency (Standard Webhooks ``webhook-id``)
# ---------------------------------------------------------------------------


class BillingWebhookDelivery(Base):
    __tablename__ = "billing_webhook_deliveries"

    webhook_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(96), nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
