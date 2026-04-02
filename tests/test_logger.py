"""Tests for logger module."""

import logging
from unittest.mock import patch

import pytest
import structlog
from structlog.stdlib import ProcessorFormatter

import logger as logger_module
from logger import configure_logging, get_logger


@pytest.mark.unit
class TestLogger:
    """Test logging configuration."""

    def setup_method(self):
        """Reset module-level logging state between tests."""
        logger_module._configured = False
        logger_module._axiom_enabled = False
        structlog.reset_defaults()
        logging.basicConfig(handlers=[], force=True)

    def test_get_logger_returns_structlog_logger(self):
        """Test get_logger returns a structlog logger instance."""
        logger = get_logger("test")
        assert hasattr(logger, "info")
        assert hasattr(logger, "bind")

    def test_get_logger_configures_automatically(self):
        """Test get_logger configures logging automatically."""
        logger = get_logger("test_auto")
        assert hasattr(logger, "info")
        assert logger_module._configured is True

    def test_configure_logging_default_level(self):
        """Test configure_logging with default level."""
        with patch.dict("os.environ", {"LOG_LEVEL": "WARNING"}, clear=False):
            configure_logging()
            root_logger = logging.getLogger()
            assert root_logger.level == logging.WARNING

    def test_configure_logging_custom_level(self):
        """Test configure_logging with custom level."""
        configure_logging(level="ERROR")
        root_logger = logging.getLogger()
        assert root_logger.level == logging.ERROR

    def test_logger_uses_console_handler_without_axiom_token(self):
        """Test local logging falls back to stdout handler."""
        with patch.dict("os.environ", {}, clear=True):
            configure_logging()
            root_logger = logging.getLogger()
            assert len(root_logger.handlers) == 1
            assert isinstance(root_logger.handlers[0], logging.StreamHandler)
            assert isinstance(root_logger.handlers[0].formatter, ProcessorFormatter)
            assert logger_module._axiom_enabled is False

    def test_logger_uses_axiom_handler_when_token_present(self):
        """Test Axiom logging is enabled from env-backed credentials."""
        mock_handler = logging.NullHandler()

        with patch.dict(
            "os.environ",
            {"AXIOM_TOKEN": "test-token", "AXIOM_DATASET": "greagent-test"},
            clear=True,
        ):
            with patch.object(logger_module, "Client") as client_cls:
                with patch.object(
                    logger_module, "AxiomHandler", return_value=mock_handler
                ) as handler_cls:
                    configure_logging()

        client_cls.assert_called_once_with(token="test-token")
        handler_cls.assert_called_once()
        root_logger = logging.getLogger()
        assert root_logger.handlers == [mock_handler]
        assert logger_module._axiom_enabled is True

    def test_configure_logging_routes_uvicorn_loggers_to_root(self):
        """Uvicorn/FastAPI loggers should propagate into the shared handlers."""
        configure_logging()

        for logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access", "fastapi"):
            ext_logger = logging.getLogger(logger_name)
            assert ext_logger.handlers == []
            assert ext_logger.propagate is True
