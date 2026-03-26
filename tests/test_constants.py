"""Tests for constants and configuration."""

import os
import pytest
from unittest.mock import patch

from constants import (
    AGENT_LLM_PROVIDER,
    OLLAMA_BASE_URL,
    daytona_sandbox_enabled,
    daytona_sandbox_home,
    get_agent_model_name,
    get_database_url,
    git_identity_from_env,
    get_rabbitmq_url,
    get_log_level,
    get_sql_echo,
)


@pytest.mark.unit
class TestConstants:
    """Test configuration constants."""

    def test_get_agent_model_name_default(self):
        """Test default agent model name."""
        with patch.dict(os.environ, {}, clear=True):
            model = get_agent_model_name()
            assert model == "kimi-k2.5:cloud"

    def test_get_agent_model_name_custom(self):
        """Test custom model name from env."""
        with patch.dict(os.environ, {"MODEL": "custom-model"}, clear=True):
            model = get_agent_model_name()
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

    def test_daytona_sandbox_enabled_no_key(self):
        """Test Daytona disabled when no API key."""
        with patch.dict(os.environ, {}, clear=True):
            assert daytona_sandbox_enabled() is False

    def test_daytona_sandbox_enabled_with_key(self):
        """Test Daytona enabled with API key."""
        with patch.dict(os.environ, {"DAYTONA_API_KEY": "test_key"}, clear=True):
            assert daytona_sandbox_enabled() is True

    def test_daytona_sandbox_enabled_agent_flag_disabled(self):
        with patch.dict(
            os.environ,
            {"DAYTONA_API_KEY": "test_key", "DAYTONA_AGENT_ENABLED": "false"},
            clear=True,
        ):
            assert daytona_sandbox_enabled() is False

    def test_daytona_sandbox_home_default(self):
        """Test default Daytona home."""
        with patch.dict(os.environ, {}, clear=True):
            home = daytona_sandbox_home()
            assert home == "/home/daytona"

    def test_daytona_sandbox_home_custom(self):
        """Test custom Daytona home via ``DAYTONA_AGENT_HOME``."""
        with patch.dict(
            os.environ, {"DAYTONA_AGENT_HOME": "/custom/home"}, clear=True
        ):
            home = daytona_sandbox_home()
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

    def test_agent_llm_provider(self):
        """Test agent LLM provider constant."""
        assert isinstance(AGENT_LLM_PROVIDER, str)

    def test_ollama_base_url(self):
        """Test Ollama base URL constant."""
        assert isinstance(OLLAMA_BASE_URL, str)
        assert OLLAMA_BASE_URL.startswith("http")

    def test_github_rest_api_version(self):
        """Test GitHub REST API version constant."""
        from constants import GITHUB_REST_API_VERSION

        assert isinstance(GITHUB_REST_API_VERSION, str)
        assert len(GITHUB_REST_API_VERSION) > 0

    def test_github_client_id_constant(self):
        """Test GitHub client ID constant exists."""
        from constants import GITHUB_CLIENT_ID

        assert isinstance(GITHUB_CLIENT_ID, str)

    def test_github_redirect_uri_constant(self):
        """Test GitHub redirect URI constant exists."""
        from constants import GITHUB_REDIRECT_URI

        assert isinstance(GITHUB_REDIRECT_URI, str)
        assert "callback" in GITHUB_REDIRECT_URI.lower()

    def test_client_url_constant(self):
        """Test client URL constant exists."""
        from constants import CLIENT_URL

        assert isinstance(CLIENT_URL, str)
        assert CLIENT_URL.startswith("http")

    def test_github_webhook_secret_constant(self):
        """Test GitHub webhook secret constant exists."""
        from constants import GITHUB_WEBHOOK_SECRET

        assert isinstance(GITHUB_WEBHOOK_SECRET, str)

    def test_daytona_install_gh_cli_constant(self):
        """Test Daytona install GH CLI constant."""
        from constants import DAYTONA_INSTALL_GH_CLI

        assert isinstance(DAYTONA_INSTALL_GH_CLI, str)

    def test_github_cli_version_constant(self):
        """Test GitHub CLI version constant."""
        from constants import GITHUB_CLI_VERSION

        assert isinstance(GITHUB_CLI_VERSION, str)
        assert len(GITHUB_CLI_VERSION) > 0

    def test_git_author_name_constant(self):
        """Test GIT_AUTHOR_NAME constant exists."""
        from constants import GIT_AUTHOR_NAME

        assert isinstance(GIT_AUTHOR_NAME, str)

    def test_git_author_email_constant(self):
        """Test GIT_AUTHOR_EMAIL constant exists."""
        from constants import GIT_AUTHOR_EMAIL

        assert isinstance(GIT_AUTHOR_EMAIL, str)

    def test_git_committer_name_constant(self):
        """Test GIT_COMMITTER_NAME constant exists."""
        from constants import GIT_COMMITTER_NAME

        assert isinstance(GIT_COMMITTER_NAME, str)

    def test_git_committer_email_constant(self):
        """Test GIT_COMMITTER_EMAIL constant exists."""
        from constants import GIT_COMMITTER_EMAIL

        assert isinstance(GIT_COMMITTER_EMAIL, str)

    def test_github_app_constants_exist(self):
        """Test GitHub App constants exist."""
        from constants import (
            GITHUB_APP_CLIENT_ID,
            GITHUB_APP_CLIENT_SECRET,
            GITHUB_APP_ID,
            GITHUB_APP_SLUG,
            GITHUB_APP_PRIVATE_KEY,
        )

        assert isinstance(GITHUB_APP_CLIENT_ID, str)
        assert isinstance(GITHUB_APP_CLIENT_SECRET, str)
        assert isinstance(GITHUB_APP_ID, str)
        assert isinstance(GITHUB_APP_SLUG, str)
        assert isinstance(GITHUB_APP_PRIVATE_KEY, str)
