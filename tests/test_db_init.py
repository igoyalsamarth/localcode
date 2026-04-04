"""Tests for database initialization utilities."""

import pytest
from unittest.mock import patch, MagicMock


@pytest.mark.unit
class TestDatabaseInit:
    """Test database initialization functions."""

    def test_register_models_imports_tables(self):
        """Test register_models imports model tables."""
        from db import register_models
        
        # Should not raise any errors
        register_models()
        
        # Verify models are registered in Base.metadata
        from db import Base
        table_names = [table.name for table in Base.metadata.tables.values()]
        
        # Check for some expected tables
        assert "users" in table_names or len(table_names) > 0

    def test_create_tables_calls_create_all(self, mock_env):
        """Test create_tables calls Base.metadata.create_all."""
        from db import create_tables, Base

        mock_engine = MagicMock()
        mock_engine.dialect.name = "postgresql"
        mock_conn = MagicMock()
        mock_begin_cm = MagicMock()
        mock_begin_cm.__enter__.return_value = None
        mock_begin_cm.__exit__.return_value = None
        mock_conn.begin.return_value = mock_begin_cm
        mock_engine.connect.return_value = mock_conn

        with patch("db.get_engine", return_value=mock_engine):
            with patch.object(Base.metadata, "create_all") as mock_create_all:
                create_tables()

                mock_create_all.assert_called_once()
                call_args = mock_create_all.call_args
                assert call_args.kwargs.get("bind") is mock_conn

    def test_create_tables_registers_models_first(self, mock_env):
        """Test create_tables registers models before creating tables."""
        from db import create_tables

        mock_engine = MagicMock()
        mock_engine.dialect.name = "postgresql"
        mock_conn = MagicMock()
        mock_begin_cm = MagicMock()
        mock_begin_cm.__enter__.return_value = None
        mock_begin_cm.__exit__.return_value = None
        mock_conn.begin.return_value = mock_begin_cm
        mock_engine.connect.return_value = mock_conn

        with patch("db.register_models") as mock_register:
            with patch("db.get_engine", return_value=mock_engine):
                with patch("db.Base.metadata.create_all"):
                    create_tables()

                    mock_register.assert_called_once()

    def test_create_tables_rejects_non_postgresql(self, mock_env):
        """Production schema bootstrap is PostgreSQL-only (no SQLite / dual-path DDL)."""
        from db import create_tables

        mock_engine = MagicMock()
        mock_engine.dialect.name = "sqlite"

        with patch("db.get_engine", return_value=mock_engine):
            with pytest.raises(RuntimeError, match="PostgreSQL"):
                create_tables()

    def test_exports_base(self):
        """Test that Base is exported."""
        from db import Base
        
        assert Base is not None
        assert hasattr(Base, "metadata")

    def test_exports_session_scope(self):
        """Test that session_scope is exported."""
        from db import session_scope
        
        assert session_scope is not None
        assert callable(session_scope)

    def test_exports_get_engine(self):
        """Test that get_engine is exported."""
        from db import get_engine
        
        assert get_engine is not None
        assert callable(get_engine)

    def test_exports_get_session_factory(self):
        """Test that get_session_factory is exported."""
        from db import get_session_factory
        
        assert get_session_factory is not None
        assert callable(get_session_factory)

    def test_exports_get_async_engine(self):
        """Test that get_async_engine is exported."""
        from db import get_async_engine
        
        assert get_async_engine is not None
        assert callable(get_async_engine)

    def test_exports_get_async_session_factory(self):
        """Test that get_async_session_factory is exported."""
        from db import get_async_session_factory
        
        assert get_async_session_factory is not None
        assert callable(get_async_session_factory)

    def test_exports_get_database_url(self):
        """Test that get_database_url is exported."""
        from db import get_database_url
        
        assert get_database_url is not None
        assert callable(get_database_url)

    def test_exports_get_psycopg_conninfo(self):
        """Test that get_psycopg_conninfo is exported."""
        from db import get_psycopg_conninfo
        
        assert get_psycopg_conninfo is not None
        assert callable(get_psycopg_conninfo)

    def test_all_exports_defined(self):
        """Test that __all__ contains expected exports."""
        from db import __all__
        
        expected = [
            "Base",
            "session_scope",
            "get_engine",
            "get_session_factory",
            "get_async_engine",
            "get_async_session_factory",
            "get_database_url",
            "get_psycopg_conninfo",
            "register_models",
            "create_tables",
        ]
        
        for item in expected:
            assert item in __all__
