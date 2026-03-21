import os
from dotenv import load_dotenv

load_dotenv()


# Coder agent (ChatOllama): provider string stored on usage rows for billing
CODER_LLM_PROVIDER = os.environ.get("CODER_LLM_PROVIDER", "ollama")


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


# GitHub OAuth configuration (for user authentication)
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

# GitHub Webhook configuration
GITHUB_WEBHOOK_SECRET = os.environ.get("GITHUB_WEBHOOK_SECRET", "")

# GitHub REST API calendar version (``X-GitHub-Api-Version``). Override via env if needed.
# See https://docs.github.com/en/rest/about-the-rest-api/api-versions
GITHUB_REST_API_VERSION = os.environ.get("GITHUB_REST_API_VERSION", "2026-03-21")

# Optional: coder agent ``git commit`` author/committer (override ``GET /user`` for bot identity).
GIT_AUTHOR_NAME = os.environ.get("GIT_AUTHOR_NAME", "").strip()
GIT_AUTHOR_EMAIL = os.environ.get("GIT_AUTHOR_EMAIL", "").strip()
GIT_COMMITTER_NAME = os.environ.get("GIT_COMMITTER_NAME", "").strip()
GIT_COMMITTER_EMAIL = os.environ.get("GIT_COMMITTER_EMAIL", "").strip()


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
