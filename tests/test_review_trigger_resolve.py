"""Tests for ``resolve_review_pr_work`` (DB + webhook routing, no GitHub API)."""

import pytest

from model.enums import AgentType
from model.tables import Agent, Model, Organization, Repository, RepositoryAgent, User
from services.github.review_trigger import resolve_review_pr_work
from services.github.trigger_modes import TRIGGER_MODE_AUTO, TRIGGER_MODE_TAG


def _pr_payload(*, action: str, repo_id: int = 42, label_name: str | None = None):
    data = {
        "action": action,
        "pull_request": {
            "number": 5,
            "title": "PR",
            "body": "",
            "base": {"ref": "main"},
            "head": {"ref": "f", "sha": "deadbeef"},
        },
        "repository": {
            "id": repo_id,
            "name": "r",
            "full_name": "o/r",
            "owner": {"login": "o"},
        },
    }
    if label_name is not None:
        data["label"] = {"name": label_name}
    return data


@pytest.mark.unit
class TestResolveReviewPrWork:
    def _seed(self, db_session, *, mode: str = TRIGGER_MODE_TAG, enabled: bool = True):
        user = User(email="u@e.com", auth_provider="github")
        db_session.add(user)
        db_session.flush()
        org = Organization(name="O", owner_user_id=user.id)
        db_session.add(org)
        db_session.flush()
        repo = Repository(
            organization_id=org.id,
            github_repo_id=42,
            name="r",
            owner="o",
            default_branch="main",
        )
        db_session.add(repo)
        db_session.flush()
        model = Model(provider="openai", name="gpt-4")
        db_session.add(model)
        db_session.flush()
        agent = Agent(
            organization_id=org.id, name="Review Agent", type=AgentType.review
        )
        db_session.add(agent)
        db_session.flush()
        ra = RepositoryAgent(
            repository_id=repo.id,
            agent_id=agent.id,
            model_id=model.id,
            enabled=enabled,
            config_json={"mode": mode},
        )
        db_session.add(ra)
        db_session.commit()

    def test_wrong_action_returns_none(self, db_session):
        self._seed(db_session)
        assert resolve_review_pr_work(db_session, _pr_payload(action="closed")) is None

    def test_no_repository_agent_returns_none(self, db_session):
        user = User(email="u@e.com", auth_provider="github")
        db_session.add(user)
        db_session.flush()
        org = Organization(name="O", owner_user_id=user.id)
        db_session.add(org)
        db_session.flush()
        db_session.add(
            Repository(
                organization_id=org.id,
                github_repo_id=42,
                name="r",
                owner="o",
                default_branch="main",
            )
        )
        db_session.commit()
        assert resolve_review_pr_work(db_session, _pr_payload(action="opened")) is None

    def test_disabled_returns_none(self, db_session):
        self._seed(db_session, enabled=False)
        assert resolve_review_pr_work(db_session, _pr_payload(action="opened")) is None

    def test_tag_mode_opened_returns_none(self, db_session):
        self._seed(db_session, mode=TRIGGER_MODE_TAG)
        assert resolve_review_pr_work(db_session, _pr_payload(action="opened")) is None

    def test_tag_mode_review_label_returns_work(self, db_session):
        self._seed(db_session, mode=TRIGGER_MODE_TAG)
        p = _pr_payload(action="labeled", label_name="greagent:review")
        work = resolve_review_pr_work(db_session, p)
        assert work is not None
        assert work.pr_number == 5
        assert work.head_sha == "deadbeef"

    def test_auto_mode_opened_returns_work(self, db_session):
        self._seed(db_session, mode=TRIGGER_MODE_AUTO)
        work = resolve_review_pr_work(db_session, _pr_payload(action="opened"))
        assert work is not None
        assert work.pr_number == 5

    def test_auto_mode_labeled_review_label_returns_work(self, db_session):
        self._seed(db_session, mode=TRIGGER_MODE_AUTO)
        p = _pr_payload(action="labeled", label_name="greagent:review")
        work = resolve_review_pr_work(db_session, p)
        assert work is not None
        assert work.pr_number == 5
