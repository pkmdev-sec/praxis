"""
Praxis × LangGraph — minimum working example.

The helper ``with_praxis`` wraps a LangChain chat model so it can be used
verbatim as a LangGraph node. Agent loops, tool calls, and checkpointing
work unchanged; Praxis scores each invocation and emits receipts.

Run with::

    export ANTHROPIC_API_KEY=sk-ant-...
    pip install 'praxis[langchain]' langgraph langchain-anthropic
    python examples/langgraph_agent.py
"""

from __future__ import annotations

import uuid

from langchain_anthropic import ChatAnthropic
from langchain_core.tools import tool
from langgraph.prebuilt import create_agent

from praxis.adapters.langgraph import with_praxis


@tool
def list_files(path: str) -> str:
    """List files in a directory. Stub for the demo."""
    return f"[stub] would list {path}"


def main() -> None:
    session_id = f"langgraph-demo-{uuid.uuid4().hex[:8]}"
    base = ChatAnthropic(model="claude-opus-4-7", max_tokens=4096)
    llm = with_praxis(base, session_id=session_id)

    agent = create_agent(llm, tools=[list_files])

    for prompt in [
        "What is git?",
        "Design a distributed deployment pipeline and list the files under src/.",
    ]:
        print(f"\nprompt: {prompt}")
        out = agent.invoke({"messages": [("user", prompt)]})
        print(f"output: {out['messages'][-1].content[:200]}")

    print("\nRun `praxis report` to see the per-tier regret ledger.")


if __name__ == "__main__":
    main()
