"""Tests for constants and configuration."""

import os
import pytest
from unittest.mock import patch

from decimal import Decimal

from constants import (
    AGENT_LLM_PROVIDER,
    DEFAULT_DAYTONA_SNAPSHOT,
    OLLAMA_API_KEY,
    OLLAMA_BASE_URL,
    daytona_sandbox_home,
    daytona_sandbox_os_user,
    daytona_sandbox_snapshot,
    daytona_sandbox_user,
    default_catalog_model_spec,
    get_agent_model_name,
    get_axiom_dataset,
    get_axiom_org_id,
    get_axiom_token,
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

    def test_default_catalog_model_spec(self):
        """Default catalog row matches Kimi-class pricing and MODEL/provider env."""
        with patch.dict(
            os.environ,
            {"MODEL": "kimi-k2.5:cloud", "AGENT_LLM_PROVIDER": "ollama"},
            clear=True,
        ):
            prov, name, inp, out = default_catalog_model_spec()
            assert prov == "ollama"
            assert name == "kimi-k2.5:cloud"
            assert inp == Decimal("0.60") / Decimal(1_000_000)
            assert out == Decimal("3.00") / Decimal(1_000_000)

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

    def test_daytona_sandbox_user_default(self):
        with patch.dict(os.environ, {}, clear=True):
            assert daytona_sandbox_user() == "greagents"
        with patch.dict(os.environ, {"DAYTONA_SANDBOX_USER": "  mybot  "}):
            assert daytona_sandbox_user() == "mybot"

    def test_daytona_sandbox_snapshot(self):
        with patch.dict(os.environ, {}, clear=True):
            assert daytona_sandbox_snapshot() == DEFAULT_DAYTONA_SNAPSHOT
        with patch.dict(os.environ, {"DAYTONA_SNAPSHOT": "  my-snap  "}):
            assert daytona_sandbox_snapshot() == "my-snap"
        with patch.dict(os.environ, {"DAYTONA_SNAPSHOT": "none"}):
            assert daytona_sandbox_snapshot() is None
        with patch.dict(os.environ, {"DAYTONA_SNAPSHOT": "-"}):
            assert daytona_sandbox_snapshot() is None
        with patch.dict(os.environ, {"DAYTONA_SNAPSHOT": ""}):
            assert daytona_sandbox_snapshot() == DEFAULT_DAYTONA_SNAPSHOT

    def test_daytona_sandbox_os_user(self):
        with patch.dict(os.environ, {}, clear=True):
            assert daytona_sandbox_os_user(custom_snapshot=False) is None
            assert daytona_sandbox_os_user(custom_snapshot=True) == "greagents"
        with patch.dict(os.environ, {"DAYTONA_SANDBOX_USER": "mybot"}):
            assert daytona_sandbox_os_user(custom_snapshot=True) == "mybot"
        with patch.dict(os.environ, {"DAYTONA_OS_USER": " builder "}):
            assert daytona_sandbox_os_user(custom_snapshot=False) == "builder"
            assert daytona_sandbox_os_user(custom_snapshot=True) == "builder"
        with patch.dict(os.environ, {"DAYTONA_OS_USER": "none"}):
            assert daytona_sandbox_os_user(custom_snapshot=True) is None
        with patch.dict(os.environ, {"DAYTONA_OS_USER": "-"}):
            assert daytona_sandbox_os_user(custom_snapshot=True) is None

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

    def test_get_axiom_token_uses_canonical_env_name(self):
        """Axiom token is read only from AXIOM_TOKEN."""
        with patch.dict(os.environ, {"AXIOM_TOKEN": "sdk-token"}, clear=True):
            assert get_axiom_token() == "sdk-token"

    def test_get_axiom_token_ignores_noncanonical_env_names(self):
        """Legacy alias env vars are not supported."""
        with patch.dict(
            os.environ,
            {"AXIOM_API_TOKEN": "app-token", "AIOM_API_KEY": "legacy-token"},
            clear=True,
        ):
            assert get_axiom_token() == ""

    def test_get_axiom_dataset_default(self):
        """Axiom logs use the default dataset when unset."""
        with patch.dict(os.environ, {}, clear=True):
            assert get_axiom_dataset() == "greagents-be"

    def test_get_axiom_org_id_default(self):
        """Org id is optional for Axiom configuration."""
        with patch.dict(os.environ, {}, clear=True):
            assert get_axiom_org_id() == ""

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

    def test_ollama_api_key_is_string(self):
        """OLLAMA_API_KEY is always a str (empty when unset)."""
        assert isinstance(OLLAMA_API_KEY, str)

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
