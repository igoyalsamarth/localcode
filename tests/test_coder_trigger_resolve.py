"""Tests for ``resolve_coder_issue_work`` (DB + webhook routing, no GitHub API)."""

import pytest

from model.enums import AgentType
from model.tables import Agent, Model, Organization, Repository, RepositoryAgent, User
from services.github.coder_trigger import resolve_coder_issue_work
from services.github.trigger_modes import TRIGGER_MODE_AUTO


def _issue_payload(*, action: str, repo_id: int = 99, label_name: str | None = None):
    data = {
        "action": action,
        "issue": {
            "number": 1,
            "title": "Hi",
            "body": "Body",
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
class TestResolveCoderIssueWork:
    def _seed(self, db_session, *, mode: str = TRIGGER_MODE_AUTO, enabled: bool = True):
        user = User(email="u@e.com", auth_provider="github")
        db_session.add(user)
        db_session.flush()
        org = Organization(name="O", owner_user_id=user.id)
        db_session.add(org)
        db_session.flush()
        repo = Repository(
            organization_id=org.id,
            github_repo_id=99,
            name="r",
            owner="o",
            default_branch="main",
        )
        db_session.add(repo)
        db_session.flush()
        model = Model(provider="openai", name="gpt-4")
        db_session.add(model)
        db_session.flush()
        agent = Agent(organization_id=org.id, name="Code Agent", type=AgentType.code)
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
        return repo

    def test_wrong_action_returns_none(self, db_session):
        self._seed(db_session)
        assert resolve_coder_issue_work(db_session, _issue_payload(action="closed")) is None

    def test_missing_repo_id_returns_none(self, db_session):
        self._seed(db_session)
        p = _issue_payload(action="opened")
        del p["repository"]["id"]
        assert resolve_coder_issue_work(db_session, p) is None

    def test_unknown_repository_returns_none(self, db_session):
        self._seed(db_session)
        assert (
            resolve_coder_issue_work(
                db_session, _issue_payload(action="opened", repo_id=404)
            )
            is None
        )

    def test_disabled_agent_returns_none(self, db_session):
        self._seed(db_session, enabled=False)
        assert resolve_coder_issue_work(db_session, _issue_payload(action="opened")) is None

    def test_auto_mode_opened_returns_work(self, db_session):
        self._seed(db_session, mode=TRIGGER_MODE_AUTO)
        work = resolve_coder_issue_work(db_session, _issue_payload(action="opened"))
        assert work is not None
        assert work.issue_number == 1
        assert work.full_name == "o/r"

    def test_label_mode_opened_returns_none(self, db_session):
        self._seed(db_session, mode="label")
        assert resolve_coder_issue_work(db_session, _issue_payload(action="opened")) is None

    def test_label_mode_wrong_label_returns_none(self, db_session):
        self._seed(db_session, mode="label")
        p = _issue_payload(action="labeled", label_name="other")
        assert resolve_coder_issue_work(db_session, p) is None

    def test_label_mode_code_label_returns_work(self, db_session):
        self._seed(db_session, mode="label")
        p = _issue_payload(action="labeled", label_name="greagent:code")
        work = resolve_coder_issue_work(db_session, p)
        assert work is not None
        assert work.issue_number == 1

    def test_auto_mode_labeled_code_label_returns_work(self, db_session):
        self._seed(db_session, mode=TRIGGER_MODE_AUTO)
        p = _issue_payload(action="labeled", label_name="greagent:code")
        work = resolve_coder_issue_work(db_session, p)
        assert work is not None
        assert work.issue_number == 1
