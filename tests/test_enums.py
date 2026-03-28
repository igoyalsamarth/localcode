"""Tests for model enums."""

import pytest

from model.enums import (
    MemberRole,
    AgentType,
    GitHubWorkflowKind,
    SubscriptionStatus,
    BillingCycle,
)


@pytest.mark.unit
class TestEnums:
    """Test model enums."""

    def test_member_role_values(self):
        """Test MemberRole enum values."""
        assert MemberRole.owner == "owner"
        assert MemberRole.admin == "admin"
        assert MemberRole.member == "member"

        assert len(MemberRole) == 3

    def test_agent_type_values(self):
        """Test AgentType enum values."""
        assert AgentType.review == "review"
        assert AgentType.code == "code"
        assert AgentType.security == "security"

        assert len(AgentType) == 3

    def test_github_workflow_kind_values(self):
        assert GitHubWorkflowKind.code == "code"
        assert GitHubWorkflowKind.review == "review"
        assert len(GitHubWorkflowKind) == 2

    def test_subscription_status_values(self):
        """Test SubscriptionStatus enum values (Dodo-aligned)."""
        assert SubscriptionStatus.pending == "pending"
        assert SubscriptionStatus.active == "active"
        assert SubscriptionStatus.on_hold == "on_hold"
        assert SubscriptionStatus.cancelled == "cancelled"
        assert SubscriptionStatus.past_due == "past_due"
        assert SubscriptionStatus.failed == "failed"
        assert SubscriptionStatus.expired == "expired"

        assert len(SubscriptionStatus) == 7

    def test_billing_cycle_values(self):
        """Test BillingCycle enum values."""
        assert BillingCycle.daily == "daily"
        assert BillingCycle.weekly == "weekly"
        assert BillingCycle.monthly == "monthly"
        assert BillingCycle.yearly == "yearly"

        assert len(BillingCycle) == 4

    def test_enums_are_string_enums(self):
        """Test all enums inherit from StrEnum."""
        from enum import StrEnum

        assert issubclass(MemberRole, StrEnum)
        assert issubclass(AgentType, StrEnum)
        assert issubclass(GitHubWorkflowKind, StrEnum)
        assert issubclass(SubscriptionStatus, StrEnum)
        assert issubclass(BillingCycle, StrEnum)

    def test_enum_string_comparison(self):
        """Test enums can be compared with strings."""
        assert MemberRole.owner == "owner"
        assert AgentType.code == "code"
        assert GitHubWorkflowKind.review == "review"

    def test_enum_iteration(self):
        """Test enums can be iterated."""
        roles = list(MemberRole)
        assert len(roles) == 3
        assert MemberRole.owner in roles
        assert MemberRole.admin in roles
        assert MemberRole.member in roles
