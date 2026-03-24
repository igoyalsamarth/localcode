"""
Service 3: Worker Service
Dramatiq worker that consumes tasks from RabbitMQ and executes the GitHub coder agent.
Multiple instances can run in parallel for horizontal scaling.
"""

import sys
from dotenv import load_dotenv
from dramatiq.cli import main as dramatiq_main

from agents.checkpoint import init_checkpointer, shutdown_checkpointer
from db import create_tables
from logger import get_logger
from task_queue.tasks import process_github_issue

load_dotenv()
logger = get_logger(__name__)


def main() -> None:
    """
    Start the Dramatiq worker process.
    
    This worker will consume tasks from the 'github_coder' queue and execute them.
    Multiple worker instances can be started for parallel processing.
    """
    logger.info("Starting LocalCode Worker service...")
    
    create_tables()
    logger.info("Database tables ensured")
    
    init_checkpointer()
    logger.info("Checkpointer initialized")
    
    try:
        sys.argv = [
            "dramatiq",
            "task_queue.tasks",
            "--processes", "2",
            "--threads", "4",
            "--verbose",
        ]
        dramatiq_main()
    finally:
        shutdown_checkpointer()
        logger.info("Worker shutdown complete")


if __name__ == "__main__":
    main()
