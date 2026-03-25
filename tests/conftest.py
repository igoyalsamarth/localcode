"""Pytest configuration and shared fixtures."""

import os
import sys
import pytest
from unittest.mock import MagicMock, patch
from sqlalchemy import create_engine, text, JSON
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

# Monkey-patch JSONB to use JSON for SQLite before importing models
from sqlalchemy.dialects.postgresql import JSONB as _JSONB

class JSONBForSQLite(JSON):
    """JSONB type that works with SQLite by using JSON."""
    __visit_name__ = "JSON"

# Replace JSONB in the postgresql module
sys.modules['sqlalchemy.dialects.postgresql'].JSONB = JSONBForSQLite

from db.client import Base


@pytest.fixture(scope="session")
def test_db_url():
    """Return SQLite in-memory database URL for testing."""
    return "sqlite:///:memory:"


@pytest.fixture(scope="function")
def db_engine(test_db_url):
    """Create a fresh database engine for each test."""
    engine = create_engine(
        test_db_url,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        echo=False,
    )
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture(scope="function")
def db_session(db_engine) -> Session:
    """Create a database session for testing."""
    SessionLocal = sessionmaker(bind=db_engine, autocommit=False, autoflush=False)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def mock_env():
    """Mock environment variables for testing."""
    with patch.dict(os.environ, {
        "DATABASE_URL": "postgresql://test:test@localhost:5432/test",
        "GITHUB_WEBHOOK_SECRET": "test_secret",
        "GITHUB_CLIENT_ID": "test_client_id",
        "GITHUB_CLIENT_SECRET": "test_client_secret",
        "GITHUB_APP_CLIENT_ID": "test_app_client_id",
        "GITHUB_APP_CLIENT_SECRET": "test_app_client_secret",
        "GITHUB_APP_ID": "12345",
        "GITHUB_APP_SLUG": "test-app",
        "GITHUB_APP_PRIVATE_KEY": "test_key",
        "MODEL": "test-model",
        "OLLAMA_BASE_URL": "http://localhost:11434",
        "RABBITMQ_URL": "amqp://guest:guest@localhost:5672/",
        "LOG_LEVEL": "INFO",
    }, clear=False):
        yield


@pytest.fixture
def sample_github_pr_webhook():
    """Sample GitHub pull_request webhook payload."""
    return {
        "action": "opened",
        "pull_request": {
            "number": 123,
            "title": "Test PR",
            "body": "This is a test PR",
            "base": {
                "ref": "main",
            },
            "head": {
                "ref": "feature-branch",
                "sha": "abc123def456",
            },
        },
        "repository": {
            "name": "test-repo",
            "full_name": "test-owner/test-repo",
            "owner": {
                "login": "test-owner",
            },
        },
        "installation": {
            "id": 12345,
        },
    }


@pytest.fixture
def sample_github_issue_webhook():
    """Sample GitHub issues webhook payload."""
    return {
        "action": "opened",
        "issue": {
            "number": 456,
            "title": "Test Issue",
            "body": "This is a test issue",
        },
        "repository": {
            "name": "test-repo",
            "full_name": "test-owner/test-repo",
            "owner": {
                "login": "test-owner",
            },
        },
        "installation": {
            "id": 12345,
        },
    }


@pytest.fixture
def sample_github_labeled_issue_webhook():
    """Sample GitHub issues labeled webhook payload."""
    return {
        "action": "labeled",
        "issue": {
            "number": 789,
            "title": "Labeled Issue",
            "body": "This issue has a label",
        },
        "label": {
            "name": "greagent:code",
        },
        "repository": {
            "name": "test-repo",
            "full_name": "test-owner/test-repo",
            "owner": {
                "login": "test-owner",
            },
        },
        "installation": {
            "id": 12345,
        },
    }
