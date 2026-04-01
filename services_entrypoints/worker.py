"""
Service 3: Worker Service
Dramatiq worker that consumes GitHub deep-agent tasks from RabbitMQ (``github_agent`` queue).
Multiple instances can run in parallel for horizontal scaling.
"""

import sys

from dotenv import load_dotenv
from dramatiq.cli import main as dramatiq_main

from logger import get_logger

load_dotenv()
logger = get_logger(__name__)


def main() -> None:
    """
    Start the Dramatiq worker process.

    Loads ``task_queue.tasks`` so workers consume the shared ``github_agent`` queue (coder and
    reviewer actors) and any other actors defined in that module.

    ``create_tables`` runs in each worker **subprocess** via
    ``WorkerProcessDbMiddleware.after_process_boot`` (see ``task_queue.broker``), not here,
    so multiprocessing children are not affected by a pre-fork parent opening DB resources.
    """
    logger.info("Starting Greagent Worker service...")

    sys.argv = [
        "dramatiq",
        "task_queue.tasks",
        "--processes",
        "2",
        "--threads",
        "4",
        "--verbose",
    ]
    dramatiq_main()
    logger.info("Worker supervisor exited")


if __name__ == "__main__":
    main()
