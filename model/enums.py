"""Shared enums for domain models. Used by both ORM and Pydantic schemas."""

from enum import StrEnum


class MemberRole(StrEnum):
    creator = "creator"
    admin = "admin"
    user = "user"


class AgentType(StrEnum):
    review = "review"
    code = "code"
    security = "security"


class GitHubWorkflowKind(StrEnum):
    """Which GitHub deep-agent workflow produced a token-usage row (issues vs PRs)."""

    code = "code"
    review = "review"


class SubscriptionStatus(StrEnum):
    pending = "pending"
    active = "active"
    on_hold = "on_hold"
    cancelled = "cancelled"
    past_due = "past_due"
    failed = "failed"
    expired = "expired"


class BillingCycle(StrEnum):
    daily = "daily"
    weekly = "weekly"
    monthly = "monthly"
    yearly = "yearly"
