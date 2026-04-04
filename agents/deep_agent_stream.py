"""Console streaming helper for deep agents (GitHub coder / reviewer workflows)."""

from __future__ import annotations

from logger import get_logger


logger = get_logger(__name__)


def _render_content(content: object) -> str:
    """Normalize message content into a compact loggable string."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text")
                if text:
                    parts.append(str(text))
        return "\n".join(part for part in parts if part)
    return str(content)


def stream_deep_agent(agent: object, user_prompt: str, config: dict) -> None:
    """Stream agent activity through the centralized logger."""
    for chunk in agent.stream(
        {
            "messages": [
                {
                    "role": "user",
                    "content": user_prompt,
                }
            ]
        },
        config,
        stream_mode="messages",
        subgraphs=True,
        version="v2",
    ):
        if chunk["type"] == "messages":
            msg, _metadata = chunk["data"]

            is_subagent = any(s.startswith("tools:") for s in chunk["ns"])
            source = (
                next((s for s in chunk["ns"] if s.startswith("tools:")), "main")
                if is_subagent
                else "main"
            )

            tool_call_chunks = getattr(msg, "tool_call_chunks", None) or []
            if tool_call_chunks:
                for tc in tool_call_chunks:
                    if tc.get("name"):
                        logger.info("[%s] Tool call: %s", source, tc["name"])
                    if tc.get("args"):
                        logger.info("[%s] Tool args: %s", source, tc["args"])

            if msg.type == "tool":
                logger.info(
                    "[%s] Tool result [%s]: %s",
                    source,
                    msg.name,
                    _render_content(msg.content)[:300],
                )

            if msg.type == "ai" and msg.content and not tool_call_chunks:
                logger.info(
                    "[%s] Agent output: %s", source, _render_content(msg.content)
                )
