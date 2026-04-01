"""Tests for Issue payload parsing."""

import pytest

from services.github.issue_payload import IssueOpenedForCoder


@pytest.mark.unit
class TestIssuePayload:
    """Test Issue webhook payload parsing."""

    def test_from_github_issues_event_valid(self, sample_github_issue_webhook):
        """Test parsing valid issue webhook."""
        issue = IssueOpenedForCoder.from_github_issues_event(sample_github_issue_webhook)
        
        assert issue is not None
        assert issue.owner == "test-owner"
        assert issue.repo_name == "test-repo"
        assert issue.full_name == "test-owner/test-repo"
        assert issue.repo_url == "https://github.com/test-owner/test-repo"
        assert issue.issue_number == 456
        assert issue.issue_title == "Test Issue"
        assert issue.issue_body == "This is a test issue"
        assert issue.github_installation_id == 12345
        assert issue.github_repo_id == 987_654_321

    def test_from_github_issues_event_missing_repository_id(self, sample_github_issue_webhook):
        """repository.id is required for per-repo agent locking."""
        del sample_github_issue_webhook["repository"]["id"]
        issue = IssueOpenedForCoder.from_github_issues_event(sample_github_issue_webhook)
        assert issue is None

    def test_from_github_issues_event_missing_owner(self, sample_github_issue_webhook):
        """Test parsing issue webhook with missing owner."""
        sample_github_issue_webhook["repository"]["owner"] = {}
        issue = IssueOpenedForCoder.from_github_issues_event(sample_github_issue_webhook)
        assert issue is None

    def test_from_github_issues_event_missing_repo_name(self, sample_github_issue_webhook):
        """Test parsing issue webhook with missing repo name."""
        del sample_github_issue_webhook["repository"]["name"]
        issue = IssueOpenedForCoder.from_github_issues_event(sample_github_issue_webhook)
        assert issue is None

    def test_from_github_issues_event_missing_issue_number(self, sample_github_issue_webhook):
        """Test parsing issue webhook with missing issue number."""
        del sample_github_issue_webhook["issue"]["number"]
        issue = IssueOpenedForCoder.from_github_issues_event(sample_github_issue_webhook)
        assert issue is None

    def test_from_github_issues_event_missing_issue_title(self, sample_github_issue_webhook):
        """Test parsing issue webhook with missing issue title."""
        del sample_github_issue_webhook["issue"]["title"]
        issue = IssueOpenedForCoder.from_github_issues_event(sample_github_issue_webhook)
        assert issue is None

    def test_from_github_issues_event_empty_body(self, sample_github_issue_webhook):
        """Test parsing issue webhook with empty body."""
        sample_github_issue_webhook["issue"]["body"] = None
        issue = IssueOpenedForCoder.from_github_issues_event(sample_github_issue_webhook)
        
        assert issue is not None
        assert issue.issue_body == ""

    def test_from_github_issues_event_no_full_name(self, sample_github_issue_webhook):
        """Test parsing issue webhook without full_name."""
        del sample_github_issue_webhook["repository"]["full_name"]
        issue = IssueOpenedForCoder.from_github_issues_event(sample_github_issue_webhook)
        
        assert issue is not None
        assert issue.full_name == "test-owner/test-repo"

    def test_from_github_issues_event_no_installation_id(self, sample_github_issue_webhook):
        """Test parsing issue webhook without installation ID."""
        del sample_github_issue_webhook["installation"]
        issue = IssueOpenedForCoder.from_github_issues_event(sample_github_issue_webhook)
        
        assert issue is not None
        assert issue.github_installation_id is None

    def test_from_github_issues_event_invalid_installation_id(self, sample_github_issue_webhook):
        """Test parsing issue webhook with invalid installation ID."""
        sample_github_issue_webhook["installation"]["id"] = "not_a_number"
        issue = IssueOpenedForCoder.from_github_issues_event(sample_github_issue_webhook)
        
        assert issue is not None
        assert issue.github_installation_id is None

    def test_from_issues_webhook_labeled_valid(self, sample_github_labeled_issue_webhook):
        """Test parsing labeled issue webhook with correct label."""
        issue = IssueOpenedForCoder.from_issues_webhook(sample_github_labeled_issue_webhook)
        
        assert issue is not None
        assert issue.issue_number == 789
        assert issue.issue_title == "Labeled Issue"

    def test_from_issues_webhook_labeled_wrong_label(self, sample_github_labeled_issue_webhook):
        """Test parsing labeled issue webhook with wrong label."""
        sample_github_labeled_issue_webhook["label"]["name"] = "bug"
        issue = IssueOpenedForCoder.from_issues_webhook(sample_github_labeled_issue_webhook)
        assert issue is None

    def test_from_issues_webhook_wrong_action(self, sample_github_issue_webhook):
        """Test parsing issue webhook with wrong action."""
        sample_github_issue_webhook["action"] = "closed"
        issue = IssueOpenedForCoder.from_issues_webhook(sample_github_issue_webhook)
        assert issue is None

    def test_from_issues_webhook_no_label(self, sample_github_issue_webhook):
        """Test parsing issue webhook without label."""
        sample_github_issue_webhook["action"] = "labeled"
        issue = IssueOpenedForCoder.from_issues_webhook(sample_github_issue_webhook)
        assert issue is None

    def test_issue_opened_for_coder_model_validation(self):
        """Test IssueOpenedForCoder model validation."""
        issue = IssueOpenedForCoder(
            owner="owner",
            repo_name="repo",
            full_name="owner/repo",
            repo_url="https://github.com/owner/repo",
            github_repo_id=42,
            issue_number=1,
            issue_title="Title",
        )
        
        assert issue.owner == "owner"
        assert issue.issue_number == 1
        assert issue.github_installation_id is None

    def test_issue_opened_for_coder_with_installation_id(self):
        """Test IssueOpenedForCoder with installation ID."""
        issue = IssueOpenedForCoder(
            owner="owner",
            repo_name="repo",
            full_name="owner/repo",
            repo_url="https://github.com/owner/repo",
            github_repo_id=42,
            issue_number=1,
            issue_title="Title",
            github_installation_id=99999,
        )
        
        assert issue.github_installation_id == 99999
