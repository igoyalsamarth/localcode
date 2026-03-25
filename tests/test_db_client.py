"""Tests for database client utilities."""

import pytest
from unittest.mock import patch, MagicMock

from db.client import (
    get_psycopg_conninfo,
    _url_for_async,
    Base,
)


@pytest.mark.unit
class TestDatabaseClient:
    """Test database client utilities."""

    def test_get_psycopg_conninfo_postgresql(self):
        """Test psycopg conninfo with postgresql:// URL."""
        test_url = "postgresql://user:pass@localhost/db"
        with patch("db.client.get_database_url", return_value=test_url):
            conninfo = get_psycopg_conninfo()
            assert conninfo == test_url

    def test_get_psycopg_conninfo_postgres(self):
        """Test psycopg conninfo with postgres:// URL."""
        test_url = "postgres://user:pass@localhost/db"
        with patch("db.client.get_database_url", return_value=test_url):
            conninfo = get_psycopg_conninfo()
            assert conninfo == test_url

    def test_get_psycopg_conninfo_psycopg2(self):
        """Test psycopg conninfo converts psycopg2 driver."""
        test_url = "postgresql+psycopg2://user:pass@localhost/db"
        with patch("db.client.get_database_url", return_value=test_url):
            conninfo = get_psycopg_conninfo()
            assert conninfo == "postgresql://user:pass@localhost/db"

    def test_get_psycopg_conninfo_asyncpg(self):
        """Test psycopg conninfo converts asyncpg driver."""
        test_url = "postgresql+asyncpg://user:pass@localhost/db"
        with patch("db.client.get_database_url", return_value=test_url):
            conninfo = get_psycopg_conninfo()
            assert conninfo == "postgresql://user:pass@localhost/db"

    def test_get_psycopg_conninfo_sqlite_raises(self):
        """Test psycopg conninfo raises for SQLite."""
        test_url = "sqlite:///test.db"
        with patch("db.client.get_database_url", return_value=test_url):
            with pytest.raises(RuntimeError, match="requires PostgreSQL"):
                get_psycopg_conninfo()

    def test_get_psycopg_conninfo_invalid_raises(self):
        """Test psycopg conninfo raises for invalid URL."""
        test_url = "invalid://url"
        with patch("db.client.get_database_url", return_value=test_url):
            with pytest.raises(RuntimeError, match="must be a PostgreSQL URI"):
                get_psycopg_conninfo()

    def test_url_for_async_postgresql(self):
        """Test async URL conversion for postgresql://."""
        url = "postgresql://user:pass@localhost/db"
        async_url = _url_for_async(url)
        assert async_url == "postgresql+asyncpg://user:pass@localhost/db"

    def test_url_for_async_psycopg2(self):
        """Test async URL conversion for psycopg2."""
        url = "postgresql+psycopg2://user:pass@localhost/db"
        async_url = _url_for_async(url)
        assert async_url == "postgresql+asyncpg://user:pass@localhost/db"

    def test_url_for_async_already_asyncpg(self):
        """Test async URL conversion for already asyncpg."""
        url = "postgresql+asyncpg://user:pass@localhost/db"
        async_url = _url_for_async(url)
        assert async_url == url

    def test_url_for_async_other(self):
        """Test async URL conversion for other URLs."""
        url = "sqlite:///test.db"
        async_url = _url_for_async(url)
        assert async_url == url

    def test_base_declarative_base(self):
        """Test Base is a declarative base."""
        assert hasattr(Base, "metadata")
        assert hasattr(Base, "registry")

    def test_session_scope_commits_on_success(self, db_engine):
        """Test session_scope commits on success."""
        from db.client import session_scope
        from sqlalchemy.orm import sessionmaker
        
        SessionLocal = sessionmaker(bind=db_engine)
        
        with patch("db.client.get_session_factory", return_value=SessionLocal):
            with session_scope() as session:
                assert session is not None
                assert session.is_active

    def test_session_scope_rolls_back_on_error(self, db_engine):
        """Test session_scope rolls back on error."""
        from db.client import session_scope
        from sqlalchemy.orm import sessionmaker
        
        SessionLocal = sessionmaker(bind=db_engine)
        
        with patch("db.client.get_session_factory", return_value=SessionLocal):
            with pytest.raises(ValueError):
                with session_scope() as session:
                    raise ValueError("Test error")
