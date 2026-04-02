"""
Centralized logging configuration for Greagent.

Usage:
    from logger import get_logger

    logger = get_logger(__name__)
    logger.info("Message here")
"""

from __future__ import annotations

import logging
import sys
from typing import Optional

import structlog
from axiom_py import Client
from axiom_py.logging import AxiomHandler
from structlog.stdlib import BoundLogger

from constants import (
    get_axiom_dataset,
    get_axiom_org_id,
    get_axiom_token,
    get_log_level as _get_log_level,
)


_configured = False
_axiom_enabled = False


def _build_shared_processors() -> list[structlog.typing.Processor]:
    """Processors shared by both Axiom and local console rendering."""
    return [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.TimeStamper(fmt="iso", key="_time"),
        structlog.processors.format_exc_info,
    ]


def _build_handlers(
    level: int,
) -> tuple[list[logging.Handler], structlog.typing.Processor, bool]:
    """Create root handlers and the terminal structlog processor."""
    token = get_axiom_token()
    dataset = get_axiom_dataset()

    if token and dataset:
        client_kwargs: dict[str, str] = {"token": token}
        org_id = get_axiom_org_id()
        if org_id:
            client_kwargs["org_id"] = org_id

        client = Client(**client_kwargs)
        return [AxiomHandler(client, dataset, level=level)], structlog.stdlib.render_to_log_kwargs, True

    console = logging.StreamHandler(sys.stdout)
    console.setLevel(level)
    console.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            processor=structlog.dev.ConsoleRenderer(),
            foreign_pre_chain=_build_shared_processors(),
        )
    )
    return [console], structlog.stdlib.ProcessorFormatter.wrap_for_formatter, False


def configure_logging(level: Optional[str] = None) -> None:
    """
    Configure application logging once.

    Uses structlog for logger calls throughout the app. When Axiom credentials
    are present, logs are shipped via ``AxiomHandler`` instead of streaming to
    stdout; otherwise logs render locally to stdout for development.
    """
    global _configured, _axiom_enabled

    if _configured:
        return

    log_level_name = level or _get_log_level()
    log_level = getattr(logging, log_level_name, logging.INFO)
    shared_processors = _build_shared_processors()
    handlers, final_processor, axiom_enabled = _build_handlers(log_level)

    logging.basicConfig(
        level=log_level,
        handlers=handlers,
        force=True,
    )

    structlog.reset_defaults()
    structlog.configure(
        processors=[
            *shared_processors,
            final_processor,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    _axiom_enabled = axiom_enabled
    _configured = True


def get_logger(name: str) -> BoundLogger:
    """
    Return a configured structlog logger bound to the given module name.
    """
    if not _configured:
        configure_logging()

    return structlog.get_logger(name)


__all__ = ["get_logger", "configure_logging"]
