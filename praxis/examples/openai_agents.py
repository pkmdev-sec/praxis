"""
Praxis × OpenAI Agents SDK — minimum working example.

Attaches :class:`PraxisRunHooks` to a ``Runner`` so each turn's reasoning
effort is chosen per-prompt. Works out of the box against GPT-5.x.

Run with::

    export OPENAI_API_KEY=sk-...
    pip install 'praxis[openai-agents]' openai-agents
    python examples/openai_agents.py
"""

from __future__ import annotations

import asyncio
import uuid

from agents import Agent, Runner

from praxis.adapters.openai_agents import PraxisRunHooks


async def main() -> None:
    session_id = f"agents-demo-{uuid.uuid4().hex[:8]}"
    agent = Agent(name="ResearchAgent", model="gpt-5.3-codex")
    hooks = PraxisRunHooks(session_id=session_id)

    prompts = [
        "What is a variable?",
        "Implement a small URL shortener in Python.",
        "Design a CRDT-based collaborative editor with conflict resolution.",
    ]

    print(f"Praxis + OpenAI Agents demo  (session={session_id})\n")
    for p in prompts:
        result = await Runner.run(agent, p, hooks=hooks)
        print(f"  prompt: {p}")
        print(f"  output: {str(result.final_output)[:120]}\n")

    print("Run `praxis report` to see the per-tier regret ledger for this run.")


if __name__ == "__main__":
    asyncio.run(main())
