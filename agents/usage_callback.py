"""
LLM usage aggregation for GitHub deep agents (issue + PR workflows).

Extends LangChain's ``UsageMetadataCallbackHandler`` so Ollama / cloud models are
counted even when ``response_metadata`` uses ``model`` instead of ``model_name``.
"""

from __future__ import annotations

from typing import Any

from langchain_core.callbacks.usage import UsageMetadataCallbackHandler
from langchain_core.messages import AIMessage
from langchain_core.messages.ai import add_usage
from langchain_core.outputs import ChatGeneration, LLMResult


def _model_label_from_message(message: AIMessage) -> str:
    meta = message.response_metadata or {}
    return (
        meta.get("model_name")
        or meta.get("model")
        or "unknown"
    )


class AgentLlmUsageCallbackHandler(UsageMetadataCallbackHandler):
    """Accumulates per-model token usage across all LLM calls (including subagents)."""

    def on_llm_end(self, response: LLMResult, **kwargs: Any) -> None:
        for gen_list in response.generations:
            for generation in gen_list:
                if not isinstance(generation, ChatGeneration):
                    continue
                message = generation.message
                if not isinstance(message, AIMessage):
                    continue
                usage_metadata = message.usage_metadata
                model_name = _model_label_from_message(message)
                if not usage_metadata:
                    continue
                with self._lock:
                    if model_name not in self.usage_metadata:
                        self.usage_metadata[model_name] = usage_metadata
                    else:
                        self.usage_metadata[model_name] = add_usage(
                            self.usage_metadata[model_name],
                            usage_metadata,
                        )
