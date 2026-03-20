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


# GitHub API token for webhook operations
token = os.environ["GITHUB_TOKEN"]

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
