"""
Shared ChatOllama client for GitHub deep agents (issue + PR workflows).

Uses the Ollama HTTP API (hosted ``https://ollama.com`` by default, or any compatible
``OLLAMA_BASE_URL``). When ``OLLAMA_API_KEY`` is set, sends ``Authorization: Bearer …``
via :attr:`langchain_ollama.ChatOllama.client_kwargs` (same pattern as the official
``ollama.Client``).
"""

from __future__ import annotations

from functools import lru_cache

from langchain_ollama import ChatOllama

from constants import (
    OLLAMA_API_KEY,
    OLLAMA_BASE_URL,
    OLLAMA_MAX_RETRIES,
    OLLAMA_TIMEOUT_SEC,
    get_agent_model_name,
)


def _ollama_client_kwargs() -> dict:
    if not OLLAMA_API_KEY:
        return {}
    return {"headers": {"Authorization": f"Bearer {OLLAMA_API_KEY}"}}


@lru_cache(maxsize=1)
def get_github_deep_agent_llm() -> ChatOllama:
    """Return the process-wide LLM used by ``create_deep_agent`` for GitHub workflows."""
    return ChatOllama(
        model=get_agent_model_name(),
        base_url=OLLAMA_BASE_URL,
        max_retries=OLLAMA_MAX_RETRIES,
        timeout=OLLAMA_TIMEOUT_SEC,
        client_kwargs=_ollama_client_kwargs(),
    )
