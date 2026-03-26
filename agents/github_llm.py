"""
Shared ChatOllama client for GitHub deep agents (issue + PR workflows).

Single instance avoids duplicating model configuration across agent modules.
"""

from __future__ import annotations

from functools import lru_cache

from langchain_ollama import ChatOllama

from constants import (
    OLLAMA_BASE_URL,
    OLLAMA_MAX_RETRIES,
    OLLAMA_TIMEOUT_SEC,
    get_agent_model_name,
)


@lru_cache(maxsize=1)
def get_github_deep_agent_llm() -> ChatOllama:
    """Return the process-wide LLM used by ``create_deep_agent`` for GitHub workflows."""
    return ChatOllama(
        model=get_agent_model_name(),
        base_url=OLLAMA_BASE_URL,
        max_retries=OLLAMA_MAX_RETRIES,
        timeout=OLLAMA_TIMEOUT_SEC,
    )
