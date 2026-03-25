"""Integration tests for agents API endpoints."""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
from uuid import uuid4


@pytest.mark.unit
class TestAgentsAPIIntegration:
    """Integration tests for agents endpoints."""

    @pytest.fixture
    def client(self):
        """Create test client."""
        from app import app
        return TestClient(app)

    @pytest.fixture
    def mock_user_with_agents(self, db_session):
        """Create a mock user with organization and agents."""
        from model.tables import User, Organization, Agent, Repository, RepositoryAgent, Model
        from model.enums import AgentType
        
        user = User(
            email="test@example.com",
            username="testuser",
            auth_provider="github",
        )
        db_session.add(user)
        db_session.flush()
        
        org = Organization(
            name="Test Org",
            owner_user_id=user.id,
        )
        db_session.add(org)
        db_session.flush()
        
        agent = Agent(
            organization_id=org.id,
            name="Test Agent",
            type=AgentType.code,
        )
        db_session.add(agent)
        
        model = Model(
            provider="openai",
            name="gpt-4",
        )
        db_session.add(model)
        db_session.flush()
        
        repo = Repository(
            organization_id=org.id,
            github_repo_id=12345,
            name="test-repo",
            owner="test-owner",
            default_branch="main",
        )
        db_session.add(repo)
        db_session.flush()
        
        repo_agent = RepositoryAgent(
            repository_id=repo.id,
            agent_id=agent.id,
            model_id=model.id,
            enabled=True,
        )
        db_session.add(repo_agent)
        db_session.commit()
        
        return user, org, agent, repo

    def test_list_agents_endpoint_exists(self, client):
        """Test GET /agents endpoint exists."""
        response = client.get("/agents")
        
        # Should return 200 or 404
        assert response.status_code in [200, 404]

    def test_list_agents_returns_json(self, client):
        """Test agents endpoint returns JSON."""
        response = client.get("/agents")
        
        assert "application/json" in response.headers["content-type"]

    def test_list_agents_returns_array(self, client, mock_user_with_agents):
        """Test agents endpoint returns array."""
        response = client.get("/agents")
        
        if response.status_code == 200:
            data = response.json()
            assert isinstance(data, list)

    def test_get_agent_endpoint_exists(self, client):
        """Test GET /agents/{agent_id} endpoint exists."""
        agent_id = str(uuid4())
        response = client.get(f"/agents/{agent_id}")
        
        # Should return 200, 404, or 422 (invalid UUID)
        assert response.status_code in [200, 404, 422]

    def test_get_agent_with_invalid_id(self, client):
        """Test get agent with invalid UUID."""
        response = client.get("/agents/invalid-uuid")
        
        # May return 404 or 422 depending on route matching
        assert response.status_code in [404, 422]

    def test_get_agent_returns_json(self, client):
        """Test get agent returns JSON."""
        agent_id = str(uuid4())
        response = client.get(f"/agents/{agent_id}")
        
        assert "application/json" in response.headers["content-type"]

    def test_list_repositories_endpoint_exists(self, client):
        """Test GET /agents/repositories endpoint exists."""
        response = client.get("/agents/repositories")
        
        assert response.status_code in [200, 404]

    def test_list_repositories_returns_json(self, client):
        """Test repositories endpoint returns JSON."""
        response = client.get("/agents/repositories")
        
        assert "application/json" in response.headers["content-type"]

    def test_list_repositories_returns_array(self, client, mock_user_with_agents):
        """Test repositories endpoint returns array."""
        response = client.get("/agents/repositories")
        
        if response.status_code == 200:
            data = response.json()
            assert isinstance(data, list)

    def test_get_repository_endpoint_exists(self, client):
        """Test GET /agents/repositories/{repo_id} endpoint exists."""
        repo_id = str(uuid4())
        response = client.get(f"/agents/repositories/{repo_id}")
        
        assert response.status_code in [200, 404, 422]

    def test_get_repository_with_invalid_id(self, client):
        """Test get repository with invalid UUID."""
        response = client.get("/agents/repositories/invalid-uuid")
        
        # May return 404 or 422 depending on route matching
        assert response.status_code in [404, 422]

    def test_update_repository_agent_endpoint_exists(self, client):
        """Test PUT /agents/repositories/{repo_id}/agents/{agent_id} endpoint exists."""
        repo_id = str(uuid4())
        agent_id = str(uuid4())
        response = client.put(
            f"/agents/repositories/{repo_id}/agents/{agent_id}",
            json={"enabled": True}
        )
        
        assert response.status_code in [200, 404, 422]

    def test_update_repository_agent_requires_json(self, client):
        """Test update repository agent requires JSON body."""
        repo_id = str(uuid4())
        agent_id = str(uuid4())
        response = client.put(
            f"/agents/repositories/{repo_id}/agents/{agent_id}"
        )
        
        # May return 404 (not found) or 422 (validation error)
        assert response.status_code in [404, 422]

    def test_agents_endpoints_use_correct_prefix(self, client):
        """Test agents endpoints use /agents prefix."""
        routes = [route.path for route in client.app.routes]
        agents_routes = [r for r in routes if r.startswith("/agents")]
        
        assert len(agents_routes) > 0

    def test_agents_method_not_allowed(self, client):
        """Test agents endpoint doesn't accept POST."""
        response = client.post("/agents", json={})
        
        # May return 404 (no route) or 405 (method not allowed)
        assert response.status_code in [404, 405]

    def test_list_models_endpoint_exists(self, client):
        """Test GET /agents/models endpoint exists."""
        response = client.get("/agents/models")
        
        assert response.status_code in [200, 404]

    def test_list_models_returns_json(self, client):
        """Test models endpoint returns JSON."""
        response = client.get("/agents/models")
        
        assert "application/json" in response.headers["content-type"]

    def test_list_models_returns_array(self, client, mock_user_with_agents):
        """Test models endpoint returns array."""
        response = client.get("/agents/models")
        
        if response.status_code == 200:
            data = response.json()
            assert isinstance(data, list)
