"""Tests for PR payload parsing."""

import pytest

from services.github.pr_payload import PROpenedForReview


@pytest.mark.unit
class TestPRPayload:
    """Test PR webhook payload parsing."""

    def test_from_github_pr_event_valid(self, sample_github_pr_webhook):
        """Test parsing valid PR webhook."""
        pr = PROpenedForReview.from_github_pr_event(sample_github_pr_webhook)
        
        assert pr is not None
        assert pr.owner == "test-owner"
        assert pr.repo_name == "test-repo"
        assert pr.full_name == "test-owner/test-repo"
        assert pr.repo_url == "https://github.com/test-owner/test-repo"
        assert pr.pr_number == 123
        assert pr.pr_title == "Test PR"
        assert pr.pr_body == "This is a test PR"
        assert pr.base_branch == "main"
        assert pr.head_branch == "feature-branch"
        assert pr.head_sha == "abc123def456"
        assert pr.github_installation_id == 12345

    def test_from_github_pr_event_missing_owner(self, sample_github_pr_webhook):
        """Test parsing PR webhook with missing owner."""
        sample_github_pr_webhook["repository"]["owner"] = {}
        pr = PROpenedForReview.from_github_pr_event(sample_github_pr_webhook)
        assert pr is None

    def test_from_github_pr_event_missing_repo_name(self, sample_github_pr_webhook):
        """Test parsing PR webhook with missing repo name."""
        del sample_github_pr_webhook["repository"]["name"]
        pr = PROpenedForReview.from_github_pr_event(sample_github_pr_webhook)
        assert pr is None

    def test_from_github_pr_event_missing_pr_number(self, sample_github_pr_webhook):
        """Test parsing PR webhook with missing PR number."""
        del sample_github_pr_webhook["pull_request"]["number"]
        pr = PROpenedForReview.from_github_pr_event(sample_github_pr_webhook)
        assert pr is None

    def test_from_github_pr_event_missing_base_branch(self, sample_github_pr_webhook):
        """Test parsing PR webhook with missing base branch."""
        del sample_github_pr_webhook["pull_request"]["base"]["ref"]
        pr = PROpenedForReview.from_github_pr_event(sample_github_pr_webhook)
        assert pr is None

    def test_from_github_pr_event_missing_head_sha(self, sample_github_pr_webhook):
        """Test parsing PR webhook with missing head SHA."""
        del sample_github_pr_webhook["pull_request"]["head"]["sha"]
        pr = PROpenedForReview.from_github_pr_event(sample_github_pr_webhook)
        assert pr is None

    def test_from_github_pr_event_empty_body(self, sample_github_pr_webhook):
        """Test parsing PR webhook with empty body."""
        sample_github_pr_webhook["pull_request"]["body"] = None
        pr = PROpenedForReview.from_github_pr_event(sample_github_pr_webhook)
        
        assert pr is not None
        assert pr.pr_body == ""

    def test_from_github_pr_event_no_full_name(self, sample_github_pr_webhook):
        """Test parsing PR webhook without full_name (constructs from owner/repo)."""
        del sample_github_pr_webhook["repository"]["full_name"]
        pr = PROpenedForReview.from_github_pr_event(sample_github_pr_webhook)
        
        assert pr is not None
        assert pr.full_name == "test-owner/test-repo"

    def test_from_github_pr_event_no_installation_id(self, sample_github_pr_webhook):
        """Test parsing PR webhook without installation ID."""
        del sample_github_pr_webhook["installation"]
        pr = PROpenedForReview.from_github_pr_event(sample_github_pr_webhook)
        
        assert pr is not None
        assert pr.github_installation_id is None

    def test_from_github_pr_event_invalid_installation_id(self, sample_github_pr_webhook):
        """Test parsing PR webhook with invalid installation ID."""
        sample_github_pr_webhook["installation"]["id"] = "not_a_number"
        pr = PROpenedForReview.from_github_pr_event(sample_github_pr_webhook)
        
        assert pr is not None
        assert pr.github_installation_id is None

    def test_pr_opened_for_review_model_validation(self):
        """Test PROpenedForReview model validation."""
        pr = PROpenedForReview(
            owner="owner",
            repo_name="repo",
            full_name="owner/repo",
            repo_url="https://github.com/owner/repo",
            pr_number=1,
            pr_title="Title",
            base_branch="main",
            head_branch="feature",
            head_sha="abc123",
        )
        
        assert pr.owner == "owner"
        assert pr.pr_number == 1
        assert pr.github_installation_id is None

    def test_pr_opened_for_review_with_installation_id(self):
        """Test PROpenedForReview with installation ID."""
        pr = PROpenedForReview(
            owner="owner",
            repo_name="repo",
            full_name="owner/repo",
            repo_url="https://github.com/owner/repo",
            pr_number=1,
            pr_title="Title",
            base_branch="main",
            head_branch="feature",
            head_sha="abc123",
            github_installation_id=99999,
        )
        
        assert pr.github_installation_id == 99999
