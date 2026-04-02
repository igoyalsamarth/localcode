"""Tests for ``resolve_coder_pr_work`` (DB + PR webhook routing, no GitHub API)."""

import pytest

from model.enums import AgentType
from model.tables import Agent, Model, Repository, RepositoryAgent
from services.github.coder_trigger import resolve_coder_pr_work
from tests.db_seed import seed_user, seed_workspace


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
class TestResolveCoderPrWork:
    def _seed(self, db_session, *, enabled: bool = True):
        user = seed_user(db_session)
        org = seed_workspace(db_session, user, name="O")
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
        agent = Agent(organization_id=org.id, name="Code Agent", type=AgentType.code)
        db_session.add(agent)
        db_session.flush()
        ra = RepositoryAgent(
            repository_id=repo.id,
            agent_id=agent.id,
            model_id=model.id,
            enabled=enabled,
            config_json={"mode": "auto"},
        )
        db_session.add(ra)
        db_session.commit()

    def test_opened_returns_none(self, db_session):
        self._seed(db_session)
        assert resolve_coder_pr_work(db_session, _pr_payload(action="opened")) is None

    def test_labeled_wrong_label_returns_none(self, db_session):
        self._seed(db_session)
        p = _pr_payload(action="labeled", label_name="greagent:review")
        assert resolve_coder_pr_work(db_session, p) is None

    def test_labeled_coder_tag_returns_work(self, db_session):
        self._seed(db_session)
        p = _pr_payload(action="labeled", label_name="greagent:code")
        work = resolve_coder_pr_work(db_session, p)
        assert work is not None
        assert work.pr_number == 5
        assert work.full_name == "o/r"

    def test_disabled_returns_none(self, db_session):
        self._seed(db_session, enabled=False)
        p = _pr_payload(action="labeled", label_name="greagent:code")
        assert resolve_coder_pr_work(db_session, p) is None
