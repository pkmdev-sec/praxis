"""
PRAXIS — framework adapters.

Each adapter is a thin wrapper around :func:`praxis.allocate_for_model`:

  1. Read the prompt just before the model call.
  2. Score it and produce the provider-shape thinking config.
  3. Emit a signed ``alloc`` receipt.
  4. Mutate the outgoing request (``thinking``, ``reasoning_effort``, etc.).
  5. After the call, emit a paired ``outcome`` receipt with actual usage.

Adapters are lazy-imported: ``import praxis`` does not require LangChain or
OpenAI Agents to be installed. Import the adapter module explicitly when
you need it, and the SDK dependency will be checked at that point.
"""
