"""Dramatiq broker configuration for RabbitMQ."""

from dramatiq.brokers.rabbitmq import RabbitmqBroker
from constants import get_rabbitmq_url
from logger import get_logger

logger = get_logger(__name__)


def create_broker() -> RabbitmqBroker:
    """Create and configure the Dramatiq RabbitMQ broker."""
    rabbitmq_url = get_rabbitmq_url()
    logger.info("Connecting to RabbitMQ at: %s", rabbitmq_url.replace(
        rabbitmq_url.split("@")[0].split("//")[1] if "@" in rabbitmq_url else "",
        "***"
    ))
    
    broker = RabbitmqBroker(url=rabbitmq_url)
    return broker


broker = create_broker()
