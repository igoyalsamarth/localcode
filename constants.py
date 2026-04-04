import os
from decimal import Decimal
from dotenv import load_dotenv

load_dotenv()

_MILLION = Decimal(1_000_000)
# Default GitHub agent LLM (see MODEL). Priced per million tokens for Kimi K2.5-class models.
_DEFAULT_LLM_INPUT_USD_PER_MILLION = Decimal("0.60")
_DEFAULT_LLM_OUTPUT_USD_PER_MILLION = Decimal("3.00")

# LLM billing provider string stored on usage rows (Ollama, OpenAI, etc.)
AGENT_LLM_PROVIDER = os.environ.get("AGENT_LLM_PROVIDER", "ollama")

# Hosted API default (https://github.com/ollama/ollama-python). Override for self-hosted,
# e.g. OLLAMA_BASE_URL=http://localhost:11434 and leave OLLAMA_API_KEY unset.
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "https://ollama.com").rstrip("/")
OLLAMA_API_KEY = os.environ.get("OLLAMA_API_KEY", "").strip()
OLLAMA_MAX_RETRIES = int(os.environ.get("OLLAMA_MAX_RETRIES", "10"))
OLLAMA_TIMEOUT_SEC = int(os.environ.get("OLLAMA_TIMEOUT_SEC", "120"))


def get_agent_model_name() -> str:
    """Default / configured LLM id for GitHub deep agents (``MODEL`` env)."""
    return os.environ.get("MODEL", "kimi-k2.5:cloud")


def default_catalog_model_spec() -> tuple[str, str, Decimal, Decimal]:
    """
    Provider, model id, and per-token USD rates for a new ``models`` catalog row.

    Aligns with :func:`get_agent_model_name` and :data:`AGENT_LLM_PROVIDER` so usage
    keys match. Rates: $0.60 / 1M input, $3.00 / 1M output (stored per token).
    """
    inp = _DEFAULT_LLM_INPUT_USD_PER_MILLION / _MILLION
    out = _DEFAULT_LLM_OUTPUT_USD_PER_MILLION / _MILLION
    return (
        os.environ.get("AGENT_LLM_PROVIDER", "ollama"),
        get_agent_model_name(),
        inp,
        out,
    )


def get_database_url() -> str:
    """
    PostgreSQL ``DATABASE_URL`` for the app (SQLAlchemy).

    Same value as used by ``db.client`` — single source of truth.
    """
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "DATABASE_URL is not set. Set it to your PostgreSQL connection URI "
            "(e.g. postgresql://user:pass@host:5432/dbname)."
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

# Initial wallet credit for new personal orgs (same balance pool as top-ups / subscription).
SIGNUP_PROMO_WALLET_USD = Decimal(os.environ.get("SIGNUP_PROMO_WALLET_USD", "5"))

# Dodo Payments (checkout + webhooks). Keys must never be exposed to the browser.
DODO_PAYMENTS_API_KEY = os.environ.get("DODO_PAYMENTS_API_KEY", "").strip()
DODO_PAYMENTS_ENVIRONMENT = os.environ.get(
    "DODO_PAYMENTS_ENVIRONMENT", "test_mode"
).strip()
DODO_PAYMENTS_WEBHOOK_KEY = os.environ.get("DODO_PAYMENTS_WEBHOOK_KEY", "").strip()
# Product id from Dodo dashboard (e.g. pdt_...) for the paid “Ship Goblin” plan.
DODO_PRODUCT_ID_SHIP_GOBLIN = os.environ.get("DODO_PRODUCT_ID_SHIP_GOBLIN", "").strip()
# One-time product for wallet top-up (hosted checkout).
DODO_PRODUCT_ID_WALLET_TOPUP = os.environ.get(
    "DODO_PRODUCT_ID_WALLET_TOPUP", ""
).strip()

# Session JWT (issued after GitHub OAuth user login; used as API Bearer token)
JWT_SECRET = os.environ.get("JWT_SECRET", "").strip()
JWT_EXPIRE_DAYS = int(os.environ.get("JWT_EXPIRE_DAYS", "7"))

# GitHub Webhook configuration
GITHUB_WEBHOOK_SECRET = os.environ.get("GITHUB_WEBHOOK_SECRET", "")

# GitHub REST API calendar version (``X-GitHub-Api-Version``). Override via env if needed.
# See https://docs.github.com/en/rest/about-the-rest-api/api-versions
GITHUB_REST_API_VERSION = os.environ.get("GITHUB_REST_API_VERSION", "2026-03-10")

# Optional: deep-agent ``git commit`` author/committer (override ``GET /user`` for bot identity).
GIT_AUTHOR_NAME = os.environ.get("GIT_AUTHOR_NAME", "").strip()
GIT_AUTHOR_EMAIL = os.environ.get("GIT_AUTHOR_EMAIL", "").strip()
GIT_COMMITTER_NAME = os.environ.get("GIT_COMMITTER_NAME", "").strip()
GIT_COMMITTER_EMAIL = os.environ.get("GIT_COMMITTER_EMAIL", "").strip()

# Default Daytona snapshot when ``DAYTONA_SNAPSHOT`` is unset (override via env).
DEFAULT_DAYTONA_SNAPSHOT = "greagents-be-custom-snapshot"


def daytona_sandbox_snapshot() -> str | None:
    """
    Registered Daytona **snapshot name** for custom sandboxes (e.g. minimal git+gh from GHCR).

    Defaults to :data:`DEFAULT_DAYTONA_SNAPSHOT`. Override with ``DAYTONA_SNAPSHOT``.
    Set ``DAYTONA_SNAPSHOT`` to ``none`` or ``-`` to use Daytona's stock language
    snapshots instead (see :func:`daytona_sandbox_language_or_default`).
    """
    raw = os.environ.get("DAYTONA_SNAPSHOT")
    if raw is None:
        return DEFAULT_DAYTONA_SNAPSHOT
    s = raw.strip()
    if not s:
        return DEFAULT_DAYTONA_SNAPSHOT  # treat empty like unset
    if s.lower() in ("-", "none"):
        return None
    return s


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
DAYTONA_INSTALL_GH_CLI = os.environ.get("DAYTONA_INSTALL_GH_CLI", "false")
GITHUB_CLI_VERSION = os.environ.get("GITHUB_CLI_VERSION", "2.88.1")


# Logging configuration
def get_log_level() -> str:
    """Get log level from environment."""
    return os.environ.get("LOG_LEVEL", "INFO").upper()


def get_axiom_token() -> str:
    """Resolve the Axiom ingest token from the canonical SDK env name."""
    return os.environ.get("AXIOM_TOKEN", "").strip()


def get_axiom_dataset() -> str:
    """Dataset name for application logs."""
    return os.environ.get("AXIOM_DATASET", "greagents-be").strip()


def get_axiom_org_id() -> str:
    """Optional org id for personal Axiom tokens."""
    return os.environ.get("AXIOM_ORG_ID", "").strip()


# Database configuration
def get_sql_echo() -> bool:
    """Whether to echo SQL queries (for debugging)."""
    return os.environ.get("SQL_ECHO", "").lower() in ("1", "true")
