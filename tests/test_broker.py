"""Tests for task queue broker utilities."""

import pytest
from unittest.mock import patch, MagicMock


@pytest.mark.unit
class TestBroker:
    """Test broker utility functions."""

    def test_url_masking_with_credentials(self):
        """Test URL masking masks credentials in logs."""
        from task_queue.broker import create_broker
        
        test_url = "amqp://user:password@localhost:5672/"
        
        with patch("task_queue.broker.get_rabbitmq_url", return_value=test_url):
            with patch("task_queue.broker.RabbitmqBroker") as mock_broker:
                with patch("task_queue.broker.logger") as mock_logger:
                    create_broker()
                    
                    mock_logger.info.assert_called_once()
                    call_args = mock_logger.info.call_args[0]
                    log_message = call_args[1]
                    
                    assert "user:password" not in log_message
                    assert "***" in log_message

    def test_url_masking_without_credentials(self):
        """Test URL masking with no credentials."""
        from task_queue.broker import create_broker
        
        test_url = "amqp://localhost:5672/"
        
        with patch("task_queue.broker.get_rabbitmq_url", return_value=test_url):
            with patch("task_queue.broker.RabbitmqBroker") as mock_broker:
                with patch("task_queue.broker.logger") as mock_logger:
                    create_broker()
                    
                    mock_logger.info.assert_called_once()
                    call_args = mock_logger.info.call_args[0]
                    log_message = call_args[1]
                    
                    # URL without credentials should be logged as-is or masked
                    assert isinstance(log_message, str)

    def test_create_broker_returns_broker(self):
        """Test that create_broker returns a broker instance."""
        from task_queue.broker import create_broker
        
        test_url = "amqp://guest:guest@localhost:5672/"
        
        with patch("task_queue.broker.get_rabbitmq_url", return_value=test_url):
            with patch("task_queue.broker.RabbitmqBroker") as mock_broker_class:
                mock_instance = MagicMock()
                mock_broker_class.return_value = mock_instance
                
                result = create_broker()
                
                assert result == mock_instance
                mock_broker_class.assert_called_once_with(url=test_url)

    def test_create_broker_uses_config_url(self):
        """Test that create_broker uses URL from config."""
        from task_queue.broker import create_broker
        
        test_url = "amqp://custom:secret@rabbitmq:5672/vhost"
        
        with patch("task_queue.broker.get_rabbitmq_url", return_value=test_url):
            with patch("task_queue.broker.RabbitmqBroker") as mock_broker_class:
                create_broker()
                
                mock_broker_class.assert_called_once_with(url=test_url)
