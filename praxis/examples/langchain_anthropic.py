"""
Praxis × LangChain × Anthropic — minimum working example.

Wraps a ``ChatAnthropic`` so every invocation decides its own reasoning
budget and records a signed receipt pair.

Run with::

    export ANTHROPIC_API_KEY=sk-ant-...
    pip install 'praxis[langchain]' langchain-anthropic
    python examples/langchain_anthropic.py
"""

from __future__ import annotations

import os
import uuid

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage

from praxis.adapters.langchain import PraxisBudget


def main() -> None:
    # Fresh session id per run so receipts don't clash with prior runs.
    session_id = f"langchain-demo-{uuid.uuid4().hex[:8]}"
    os.environ.setdefault("PRAXIS_SESSION_ID", session_id)

    base = ChatAnthropic(model="claude-opus-4-7", max_tokens=4096)
    llm = PraxisBudget(base, session_id=session_id)

    prompts = [
        "What is a variable?",                                       # trivial
        "Refactor the login flow to use PKCE.",                      # moderate
        "Design a distributed fault-tolerant microservice pipeline.",# complex
    ]

    print(f"Praxis + LangChain demo  (session={session_id})\n")
    for p in prompts:
        reply = llm.invoke([HumanMessage(p)])
        print(f"  prompt: {p}")
        print(f"  reply : {str(reply.content)[:120]}\n")

    print("Run `praxis report` to see the per-tier regret ledger for this run.")


if __name__ == "__main__":
    main()
