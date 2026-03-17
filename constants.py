import os
from dotenv import load_dotenv

load_dotenv()

# GitHub API token for webhook operations
token = os.environ["GITHUB_TOKEN"]

# GitHub OAuth configuration
GITHUB_CLIENT_ID = os.environ.get("GITHUB_CLIENT_ID", "")
GITHUB_CLIENT_SECRET = os.environ.get("GITHUB_CLIENT_SECRET", "")
GITHUB_REDIRECT_URI = os.environ.get(
    "GITHUB_REDIRECT_URI", "http://localhost:8000/auth/github/callback"
)

# GitHub Webhook configuration
GITHUB_WEBHOOK_SECRET = os.environ.get("GITHUB_WEBHOOK_SECRET", "")
