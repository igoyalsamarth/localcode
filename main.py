"""
Main entry point for Greagent webhook server.

Run with: uv run main.py or python main.py
"""

import uvicorn
from logger import get_logger

logger = get_logger(__name__)


def main() -> None:
    """Start the Greagent webhook server."""
    logger.info("Starting Greagent webhook server...")

    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=8000,
        log_config=None,
        access_log=True,
    )


if __name__ == "__main__":
    main()
