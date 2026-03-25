"""Tests for constants and configuration."""

import os
import pytest
from unittest.mock import patch

from constants import (
    get_coder_model_name,
    get_database_url,
    daytona_coder_enabled,
    daytona_coder_home,
    git_identity_from_env,
    get_rabbitmq_url,
    get_log_level,
    get_sql_echo,
    CODER_LLM_PROVIDER,
    OLLAMA_BASE_URL,
)


@pytest.mark.unit
class TestConstants:
    """Test configuration constants."""

    def test_get_coder_model_name_default(self):
        """Test default coder model name."""
        with patch.dict(os.environ, {}, clear=True):
            model = get_coder_model_name()
            assert model == "kimi-k2.5:cloud"

    def test_get_coder_model_name_custom(self):
        """Test custom coder model name from env."""
        with patch.dict(os.environ, {"MODEL": "custom-model"}, clear=True):
            model = get_coder_model_name()
            assert model == "custom-model"

    def test_get_database_url_missing(self):
        """Test database URL raises error when not set."""
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(RuntimeError, match="DATABASE_URL is not set"):
                get_database_url()

    def test_get_database_url_set(self):
        """Test database URL when set."""
        test_url = "postgresql://user:pass@localhost/db"
        with patch.dict(os.environ, {"DATABASE_URL": test_url}, clear=True):
            url = get_database_url()
            assert url == test_url

    def test_daytona_coder_enabled_no_key(self):
        """Test Daytona coder disabled when no API key."""
        with patch.dict(os.environ, {}, clear=True):
            assert daytona_coder_enabled() is False

    def test_daytona_coder_enabled_with_key(self):
        """Test Daytona coder enabled with API key."""
        with patch.dict(os.environ, {"DAYTONA_API_KEY": "test_key"}, clear=True):
            assert daytona_coder_enabled() is True

    def test_daytona_coder_enabled_explicitly_disabled(self):
        """Test Daytona coder explicitly disabled."""
        with patch.dict(
            os.environ,
            {"DAYTONA_API_KEY": "test_key", "DAYTONA_CODER_ENABLED": "false"},
            clear=True,
        ):
            assert daytona_coder_enabled() is False

    def test_daytona_coder_home_default(self):
        """Test default Daytona home."""
        with patch.dict(os.environ, {}, clear=True):
            home = daytona_coder_home()
            assert home == "/home/daytona"

    def test_daytona_coder_home_custom(self):
        """Test custom Daytona home."""
        with patch.dict(os.environ, {"DAYTONA_CODER_HOME": "/custom/home"}, clear=True):
            home = daytona_coder_home()
            assert home == "/custom/home"

    def test_git_identity_from_env_not_set(self):
        """Test git identity returns None when not set."""
        with patch.dict(os.environ, {}, clear=True):
            identity = git_identity_from_env()
            assert identity is None

    def test_git_identity_from_env_author_only(self):
        """Test git identity with author only."""
        with patch("constants.GIT_AUTHOR_NAME", "Test Author"):
            with patch("constants.GIT_AUTHOR_EMAIL", "author@test.com"):
                with patch("constants.GIT_COMMITTER_NAME", ""):
                    with patch("constants.GIT_COMMITTER_EMAIL", ""):
                        identity = git_identity_from_env()
                        assert identity is not None
                        author, committer = identity
                        assert author == ("Test Author", "author@test.com")
                        assert committer == ("Test Author", "author@test.com")

    def test_git_identity_from_env_author_and_committer(self):
        """Test git identity with separate author and committer."""
        with patch("constants.GIT_AUTHOR_NAME", "Test Author"):
            with patch("constants.GIT_AUTHOR_EMAIL", "author@test.com"):
                with patch("constants.GIT_COMMITTER_NAME", "Test Committer"):
                    with patch("constants.GIT_COMMITTER_EMAIL", "committer@test.com"):
                        identity = git_identity_from_env()
                        assert identity is not None
                        author, committer = identity
                        assert author == ("Test Author", "author@test.com")
                        assert committer == ("Test Committer", "committer@test.com")

    def test_get_rabbitmq_url_default(self):
        """Test default RabbitMQ URL."""
        with patch.dict(os.environ, {}, clear=True):
            url = get_rabbitmq_url()
            assert url == "amqp://guest:guest@localhost:5672/"

    def test_get_rabbitmq_url_custom(self):
        """Test custom RabbitMQ URL."""
        test_url = "amqp://user:pass@rabbitmq:5672/vhost"
        with patch.dict(os.environ, {"RABBITMQ_URL": test_url}, clear=True):
            url = get_rabbitmq_url()
            assert url == test_url

    def test_get_log_level_default(self):
        """Test default log level."""
        with patch.dict(os.environ, {}, clear=True):
            level = get_log_level()
            assert level == "INFO"

    def test_get_log_level_custom(self):
        """Test custom log level."""
        with patch.dict(os.environ, {"LOG_LEVEL": "debug"}, clear=True):
            level = get_log_level()
            assert level == "DEBUG"

    def test_get_sql_echo_default(self):
        """Test SQL echo disabled by default."""
        with patch.dict(os.environ, {}, clear=True):
            echo = get_sql_echo()
            assert echo is False

    def test_get_sql_echo_enabled(self):
        """Test SQL echo enabled."""
        with patch.dict(os.environ, {"SQL_ECHO": "true"}, clear=True):
            echo = get_sql_echo()
            assert echo is True

    def test_coder_llm_provider(self):
        """Test coder LLM provider constant."""
        assert isinstance(CODER_LLM_PROVIDER, str)

    def test_ollama_base_url(self):
        """Test Ollama base URL constant."""
        assert isinstance(OLLAMA_BASE_URL, str)
        assert OLLAMA_BASE_URL.startswith("http")
