"""Tests for usage callback handler."""

import pytest
from unittest.mock import MagicMock

from agents.usage_callback import (
    AgentLlmUsageCallbackHandler,
    _model_label_from_message,
)
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, LLMResult


@pytest.mark.unit
class TestUsageCallback:
    """Test usage callback handler."""

    def test_model_label_from_message_with_model_name(self):
        """Test extracting model label from message with model_name."""
        message = AIMessage(
            content="test",
            response_metadata={"model_name": "gpt-4"},
        )
        
        label = _model_label_from_message(message)
        assert label == "gpt-4"

    def test_model_label_from_message_with_model(self):
        """Test extracting model label from message with model."""
        message = AIMessage(
            content="test",
            response_metadata={"model": "claude-3"},
        )
        
        label = _model_label_from_message(message)
        assert label == "claude-3"

    def test_model_label_from_message_prefers_model_name(self):
        """Test that model_name is preferred over model."""
        message = AIMessage(
            content="test",
            response_metadata={
                "model_name": "gpt-4",
                "model": "claude-3",
            },
        )
        
        label = _model_label_from_message(message)
        assert label == "gpt-4"

    def test_model_label_from_message_no_metadata(self):
        """Test extracting model label with no metadata."""
        message = AIMessage(content="test")
        
        label = _model_label_from_message(message)
        assert label == "unknown"

    def test_model_label_from_message_empty_metadata(self):
        """Test extracting model label with empty metadata."""
        message = AIMessage(
            content="test",
            response_metadata={},
        )
        
        label = _model_label_from_message(message)
        assert label == "unknown"

    def test_coder_llm_usage_callback_handler_initialization(self):
        """Test AgentLlmUsageCallbackHandler initialization."""
        handler = AgentLlmUsageCallbackHandler()
        
        assert handler is not None
        assert hasattr(handler, "usage_metadata")
        assert isinstance(handler.usage_metadata, dict)

    def test_coder_llm_usage_callback_handler_on_llm_end_with_usage(self):
        """Test on_llm_end accumulates usage metadata."""
        handler = AgentLlmUsageCallbackHandler()
        
        message = AIMessage(
            content="test response",
            response_metadata={"model": "gpt-4"},
            usage_metadata={
                "input_tokens": 10,
                "output_tokens": 20,
                "total_tokens": 30,
            },
        )
        
        generation = ChatGeneration(message=message)
        result = LLMResult(generations=[[generation]])
        
        handler.on_llm_end(result)
        
        assert "gpt-4" in handler.usage_metadata
        assert handler.usage_metadata["gpt-4"]["input_tokens"] == 10
        assert handler.usage_metadata["gpt-4"]["output_tokens"] == 20
        assert handler.usage_metadata["gpt-4"]["total_tokens"] == 30

    def test_coder_llm_usage_callback_handler_accumulates_usage(self):
        """Test that usage is accumulated across multiple calls."""
        handler = AgentLlmUsageCallbackHandler()
        
        message1 = AIMessage(
            content="response 1",
            response_metadata={"model": "gpt-4"},
            usage_metadata={
                "input_tokens": 10,
                "output_tokens": 20,
                "total_tokens": 30,
            },
        )
        
        message2 = AIMessage(
            content="response 2",
            response_metadata={"model": "gpt-4"},
            usage_metadata={
                "input_tokens": 15,
                "output_tokens": 25,
                "total_tokens": 40,
            },
        )
        
        generation1 = ChatGeneration(message=message1)
        result1 = LLMResult(generations=[[generation1]])
        handler.on_llm_end(result1)
        
        generation2 = ChatGeneration(message=message2)
        result2 = LLMResult(generations=[[generation2]])
        handler.on_llm_end(result2)
        
        assert "gpt-4" in handler.usage_metadata
        assert handler.usage_metadata["gpt-4"]["input_tokens"] == 25
        assert handler.usage_metadata["gpt-4"]["output_tokens"] == 45
        assert handler.usage_metadata["gpt-4"]["total_tokens"] == 70

    def test_coder_llm_usage_callback_handler_multiple_models(self):
        """Test usage tracking for multiple models."""
        handler = AgentLlmUsageCallbackHandler()
        
        message1 = AIMessage(
            content="response 1",
            response_metadata={"model": "gpt-4"},
            usage_metadata={
                "input_tokens": 10,
                "output_tokens": 20,
                "total_tokens": 30,
            },
        )
        
        message2 = AIMessage(
            content="response 2",
            response_metadata={"model": "claude-3"},
            usage_metadata={
                "input_tokens": 15,
                "output_tokens": 25,
                "total_tokens": 40,
            },
        )
        
        generation1 = ChatGeneration(message=message1)
        result1 = LLMResult(generations=[[generation1]])
        handler.on_llm_end(result1)
        
        generation2 = ChatGeneration(message=message2)
        result2 = LLMResult(generations=[[generation2]])
        handler.on_llm_end(result2)
        
        assert "gpt-4" in handler.usage_metadata
        assert "claude-3" in handler.usage_metadata
        assert handler.usage_metadata["gpt-4"]["input_tokens"] == 10
        assert handler.usage_metadata["claude-3"]["input_tokens"] == 15

    def test_coder_llm_usage_callback_handler_no_usage_metadata(self):
        """Test on_llm_end with no usage metadata."""
        handler = AgentLlmUsageCallbackHandler()
        
        message = AIMessage(
            content="test response",
            response_metadata={"model": "gpt-4"},
        )
        
        generation = ChatGeneration(message=message)
        result = LLMResult(generations=[[generation]])
        
        handler.on_llm_end(result)
        
        assert len(handler.usage_metadata) == 0

    def test_coder_llm_usage_callback_handler_non_chat_generation(self):
        """Test on_llm_end with non-ChatGeneration."""
        from langchain_core.outputs import Generation
        
        handler = AgentLlmUsageCallbackHandler()
        
        generation = Generation(text="test response")
        result = LLMResult(generations=[[generation]])
        
        handler.on_llm_end(result)
        
        assert len(handler.usage_metadata) == 0
