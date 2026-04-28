"""
PRAXIS — LangGraph node pre-hook adapter.

LangGraph's ``create_agent`` / ``StateGraph`` nodes wrap a LangChain chat
model. :class:`PraxisBudget` from :mod:`praxis.adapters.langchain` already
works as a node because it is a ``Runnable``; this module just exposes a
one-liner helper for the common case.

Use::

    from langgraph.prebuilt import create_agent
    from praxis.adapters.langgraph import with_praxis
    from langchain_anthropic import ChatAnthropic

    llm = with_praxis(ChatAnthropic(model="claude-opus-4-7"), session_id="sess-1")
    agent = create_agent(llm, tools=[...])

The wrapped ``llm`` participates in tool-calling, handoffs, and checkpointing
exactly as a bare ``ChatAnthropic`` would; Praxis scores on each invocation
and emits alloc/outcome receipts.
"""

from __future__ import annotations

from typing import Any, Optional

from .langchain import PraxisBudget

__all__ = ["with_praxis"]


def with_praxis(
    llm: Any,
    *,
    session_id: Optional[str] = None,
    model: Optional[str] = None,
    emit_receipts: bool = True,
) -> PraxisBudget:
    """Wrap a LangChain chat model so it can be used as a LangGraph node."""
    return PraxisBudget(
        llm,
        session_id=session_id,
        model=model,
        emit_receipts=emit_receipts,
    )
