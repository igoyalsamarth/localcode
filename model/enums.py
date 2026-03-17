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


class ReviewStatus(StrEnum):
    queued = "queued"
    running = "running"
    done = "done"
    failed = "failed"


class TriggeredBy(StrEnum):
    user = "user"
    webhook = "webhook"
    tag = "tag"


class ReviewFileStatus(StrEnum):
    pending = "pending"
    processing = "processing"
    done = "done"
    failed = "failed"


class CommentSeverity(StrEnum):
    info = "info"
    warning = "warning"
    error = "error"


class SubscriptionStatus(StrEnum):
    active = "active"
    cancelled = "cancelled"
    past_due = "past_due"


class BillingCycle(StrEnum):
    monthly = "monthly"
    yearly = "yearly"
