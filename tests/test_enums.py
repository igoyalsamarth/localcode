"""Tests for model enums."""

import pytest

from model.enums import (
    MemberRole,
    AgentType,
    ReviewStatus,
    TriggeredBy,
    ReviewFileStatus,
    CommentSeverity,
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

    def test_review_status_values(self):
        """Test ReviewStatus enum values."""
        assert ReviewStatus.queued == "queued"
        assert ReviewStatus.running == "running"
        assert ReviewStatus.done == "done"
        assert ReviewStatus.failed == "failed"
        
        assert len(ReviewStatus) == 4

    def test_triggered_by_values(self):
        """Test TriggeredBy enum values."""
        assert TriggeredBy.user == "user"
        assert TriggeredBy.webhook == "webhook"
        assert TriggeredBy.tag == "tag"
        
        assert len(TriggeredBy) == 3

    def test_review_file_status_values(self):
        """Test ReviewFileStatus enum values."""
        assert ReviewFileStatus.pending == "pending"
        assert ReviewFileStatus.processing == "processing"
        assert ReviewFileStatus.done == "done"
        assert ReviewFileStatus.failed == "failed"
        
        assert len(ReviewFileStatus) == 4

    def test_comment_severity_values(self):
        """Test CommentSeverity enum values."""
        assert CommentSeverity.info == "info"
        assert CommentSeverity.warning == "warning"
        assert CommentSeverity.error == "error"
        
        assert len(CommentSeverity) == 3

    def test_subscription_status_values(self):
        """Test SubscriptionStatus enum values."""
        assert SubscriptionStatus.active == "active"
        assert SubscriptionStatus.cancelled == "cancelled"
        assert SubscriptionStatus.past_due == "past_due"
        
        assert len(SubscriptionStatus) == 3

    def test_billing_cycle_values(self):
        """Test BillingCycle enum values."""
        assert BillingCycle.monthly == "monthly"
        assert BillingCycle.yearly == "yearly"
        
        assert len(BillingCycle) == 2

    def test_enums_are_string_enums(self):
        """Test all enums inherit from StrEnum."""
        from enum import StrEnum
        
        assert issubclass(MemberRole, StrEnum)
        assert issubclass(AgentType, StrEnum)
        assert issubclass(ReviewStatus, StrEnum)
        assert issubclass(TriggeredBy, StrEnum)
        assert issubclass(ReviewFileStatus, StrEnum)
        assert issubclass(CommentSeverity, StrEnum)
        assert issubclass(SubscriptionStatus, StrEnum)
        assert issubclass(BillingCycle, StrEnum)

    def test_enum_string_comparison(self):
        """Test enums can be compared with strings."""
        assert MemberRole.owner == "owner"
        assert AgentType.code == "code"
        assert ReviewStatus.done == "done"

    def test_enum_iteration(self):
        """Test enums can be iterated."""
        roles = list(MemberRole)
        assert len(roles) == 3
        assert MemberRole.owner in roles
        assert MemberRole.admin in roles
        assert MemberRole.member in roles
