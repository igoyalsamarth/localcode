"""Dramatiq broker configuration for RabbitMQ."""

from dramatiq import Middleware
from dramatiq.broker import Broker
from dramatiq.brokers.rabbitmq import RabbitmqBroker

from constants import get_rabbitmq_url
from logger import get_logger

logger = get_logger(__name__)

# Single Dramatiq queue for coder + reviewer actors (must match ``task_queue.tasks``).
GITHUB_AGENT_QUEUE_NAME = "github_agent"


class WorkerProcessDbMiddleware(Middleware):
    """
    Run ORM ``create_tables`` inside each worker **OS process**.

    The Dramatiq CLI spawns worker subprocesses; opening DB pools in the parent before
    ``multiprocessing`` starts can leave forked children with invalid handles, and the parent
    never runs tasks. This hook matches ``broker.emit_after("process_boot")`` in the worker
    child only.
    """

    def after_process_boot(self, broker: Broker) -> None:
        from db import create_tables

        create_tables()
        logger.info("Database tables ensured")

        # Dramatiq RabbitMQ: ``Worker`` starts consumers for both the main queue and
        # ``{name}.DQ`` in parallel. The delay consumer may call ``consume(ensure=True)``
        # before the main consumer has run ``_ensure_queue``, so ``declare_queue`` skips
        # creating ``.DQ`` / ``.XQ`` and RabbitMQ returns NOT_FOUND. Declaring here runs once
        # per worker subprocess after ``import_broker`` but before ``Worker.start()``.
        try:
            broker.declare_queue(GITHUB_AGENT_QUEUE_NAME, ensure=True)
        except TypeError:
            # Non-RabbitMQ brokers (e.g. stubs) may not support ``ensure``.
            pass


def create_broker() -> RabbitmqBroker:
    """Create and configure the Dramatiq RabbitMQ broker."""
    rabbitmq_url = get_rabbitmq_url()
    logger.info(
        "Connecting to RabbitMQ at: %s",
        rabbitmq_url.replace(
            rabbitmq_url.split("@")[0].split("//")[1] if "@" in rabbitmq_url else "",
            "***",
        ),
    )

    broker = RabbitmqBroker(url=rabbitmq_url)
    broker.add_middleware(WorkerProcessDbMiddleware())
    return broker


broker = create_broker()
