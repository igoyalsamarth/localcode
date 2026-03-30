"""Console streaming helper for deep agents (GitHub coder / reviewer workflows)."""

from __future__ import annotations


def stream_deep_agent(agent: object, user_prompt: str, config: dict) -> None:
    """Stream agent messages to stdout (tool calls, tool results, AI text)."""
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
                        print(f"[{source}] Tool call: {tc['name']}")
                    if tc.get("args"):
                        print(tc["args"], end="", flush=True)

            if msg.type == "tool":
                print(
                    f"[{source}] Tool result [{msg.name}]: {str(msg.content)[:150]}"
                )

            if msg.type == "ai" and msg.content and not tool_call_chunks:
                print(msg.content, end="", flush=True)

        print()
