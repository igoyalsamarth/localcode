"""Message queue infrastructure using Dramatiq with RabbitMQ."""

from task_queue.broker import broker
from task_queue.tasks import process_github_issue

__all__ = ["broker", "process_github_issue"]
