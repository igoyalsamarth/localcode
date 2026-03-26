"""Shared enums for domain models. Used by both ORM and Pydantic schemas."""

from enum import StrEnum


class MemberRole(StrEnum):
    owner = "owner"
    admin = "admin"
    member = "member"


class AgentType(StrEnum):
    review = "review"
    code = "code"
    security = "security"


class GitHubWorkflowKind(StrEnum):
    """Which GitHub deep-agent workflow produced a token-usage row (issues vs PRs)."""

    code = "code"
    review = "review"


class SubscriptionStatus(StrEnum):
    active = "active"
    cancelled = "cancelled"
    past_due = "past_due"


class BillingCycle(StrEnum):
    monthly = "monthly"
    yearly = "yearly"
