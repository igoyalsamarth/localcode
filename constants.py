import os
from dotenv import load_dotenv

load_dotenv()


# Coder agent (ChatOllama): provider string stored on usage rows for billing
CODER_LLM_PROVIDER = os.environ.get("CODER_LLM_PROVIDER", "ollama")
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")


def get_coder_model_name() -> str:
    """Default / configured LLM id for the GitHub coder agent (``MODEL`` env)."""
    return os.environ.get("MODEL", "kimi-k2.5:cloud")


def get_database_url() -> str:
    """
    PostgreSQL ``DATABASE_URL`` for the app (SQLAlchemy) and LangGraph checkpoints.

    Same value as used by ``db.client`` — single source of truth.
    """
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "DATABASE_URL is not set. Get it from Supabase Dashboard → Project Settings → Database."
        )
    return url


# GitHub OAuth (identity only: profile + email). Repo/org access is via the GitHub App.
GITHUB_CLIENT_ID = os.environ.get("GITHUB_CLIENT_ID", "")
GITHUB_CLIENT_SECRET = os.environ.get("GITHUB_CLIENT_SECRET", "")
GITHUB_REDIRECT_URI = os.environ.get(
    "GITHUB_REDIRECT_URI", "http://localhost:8000/auth/github/callback"
)

# GitHub App configuration (for repository integration)
GITHUB_APP_CLIENT_ID = os.environ.get("GITHUB_APP_CLIENT_ID", "")
GITHUB_APP_CLIENT_SECRET = os.environ.get("GITHUB_APP_CLIENT_SECRET", "")
GITHUB_APP_ID = os.environ.get("GITHUB_APP_ID", "")
GITHUB_APP_SLUG = os.environ.get("GITHUB_APP_SLUG", "")
GITHUB_APP_PRIVATE_KEY = os.environ.get("GITHUB_APP_PRIVATE_KEY", "")

CLIENT_URL = os.environ.get("CLIENT_URL", "http://localhost:3000")

# Session JWT (issued after GitHub OAuth user login; used as API Bearer token)
JWT_SECRET = os.environ.get("JWT_SECRET", "").strip()
JWT_EXPIRE_DAYS = int(os.environ.get("JWT_EXPIRE_DAYS", "7"))

# GitHub Webhook configuration
GITHUB_WEBHOOK_SECRET = os.environ.get("GITHUB_WEBHOOK_SECRET", "")

# GitHub REST API calendar version (``X-GitHub-Api-Version``). Override via env if needed.
# See https://docs.github.com/en/rest/about-the-rest-api/api-versions
GITHUB_REST_API_VERSION = os.environ.get("GITHUB_REST_API_VERSION", "2026-03-10")

# Optional: coder agent ``git commit`` author/committer (override ``GET /user`` for bot identity).
GIT_AUTHOR_NAME = os.environ.get("GIT_AUTHOR_NAME", "").strip()
GIT_AUTHOR_EMAIL = os.environ.get("GIT_AUTHOR_EMAIL", "").strip()
GIT_COMMITTER_NAME = os.environ.get("GIT_COMMITTER_NAME", "").strip()
GIT_COMMITTER_EMAIL = os.environ.get("GIT_COMMITTER_EMAIL", "").strip()


def daytona_coder_enabled() -> bool:
    """
    Use Daytona remote sandbox for the GitHub coder when ``DAYTONA_API_KEY`` is set.

    Set ``DAYTONA_CODER_ENABLED=false`` to force the local ``LocalShellBackend`` even if a key exists.
    """
    if os.environ.get("DAYTONA_CODER_ENABLED", "").strip().lower() in (
        "0",
        "false",
        "no",
        "off",
    ):
        return False
    return bool(os.environ.get("DAYTONA_API_KEY", "").strip())


def daytona_coder_home() -> str:
    """
    Default OS home inside the TypeScript Daytona snapshot (used for ``CODER_REPO_ABS`` / ``PATH``).

    Override if your snapshot uses a different user home.
    """
    h = os.environ.get("DAYTONA_CODER_HOME", "").strip()
    return h if h else "/home/daytona"


def git_identity_from_env() -> tuple[tuple[str, str], tuple[str, str]] | None:
    """
    Return ``((author_name, author_email), (committer_name, committer_email))`` when
    ``GIT_AUTHOR_NAME`` and ``GIT_AUTHOR_EMAIL`` are set.

    Committer defaults to author if committer vars are empty.
    """
    if GIT_AUTHOR_NAME and GIT_AUTHOR_EMAIL:
        cn = GIT_COMMITTER_NAME or GIT_AUTHOR_NAME
        ce = GIT_COMMITTER_EMAIL or GIT_AUTHOR_EMAIL
        return (GIT_AUTHOR_NAME, GIT_AUTHOR_EMAIL), (cn, ce)
    return None


# RabbitMQ configuration
def get_rabbitmq_url() -> str:
    """RabbitMQ connection URL."""
    return os.environ.get("RABBITMQ_URL", "amqp://guest:guest@localhost:5672/")


# Daytona configuration
DAYTONA_INSTALL_GH_CLI = os.environ.get("DAYTONA_INSTALL_GH_CLI", "true")
GITHUB_CLI_VERSION = os.environ.get("GITHUB_CLI_VERSION", "2.88.1")


# Logging configuration
def get_log_level() -> str:
    """Get log level from environment."""
    return os.environ.get("LOG_LEVEL", "INFO").upper()


# Database configuration
def get_sql_echo() -> bool:
    """Whether to echo SQL queries (for debugging)."""
    return os.environ.get("SQL_ECHO", "").lower() in ("1", "true")
