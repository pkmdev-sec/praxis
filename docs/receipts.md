# Receipts: The Verification Layer

Every Praxis decision writes a **signed receipt** to disk. Every turn's outcome
writes a paired receipt. Together they make reasoning-budget allocation
*auditable* — which is the property no other tool in the 2026 landscape ships.

## Why this exists

The three-layer trust model (see [`docs/competitive-landscape.md`](./competitive-landscape.md)):

1. **Visibility** — *what am I paying for?* Partially solved by `ccusage`,
   `aider` leaderboard, `claude-cost`. Commoditizing.
2. **Verification** — *did I get what I paid for?* **Unsolved. No product
   ships it.** This is the layer Praxis claims.
3. **Agency** — *can I control it?* Partially solved via environment variables
   and stop-hooks.

Anthropic's March 2026 silent-degradation incident (one user's monthly spend
jumping from $345 to $42,121 after a silent default flip) is the canonical
"why now" for Layer 2. With signed receipts, that kind of drift becomes
*detectable from the client side*. The provider said *"high effort"* — the
ledger can show that `thinking_used` collapsed to 1/10 of the prior week's
median at the same tier. That difference is the receipt.

## The schema

Each receipt is a single JSON line under `$PRAXIS_HOME/<ledger>.jsonl`:

```json
{
  "v": 1,
  "type": "alloc",
  "sid": "<stable session id>",
  "tid": <monotonic turn id within session>,
  "ts": 1700000000.5,
  "policy_version": "1.1.0",
  "payload": { ... type-specific ... },
  "sig": "<hex SHA-256 HMAC>"
}
```

**`alloc` payload** — written by `hooks/praxis-allocator.py` on
`UserPromptSubmit`:

```json
{
  "prompt_preview": "Design a distributed system...",
  "prompt_len": 27,
  "complexity": 7,
  "tier": "heavy",
  "budget_requested": 16384,
  "effort": "high",
  "model": "claude-opus-4-7",
  "model_family": "adaptive_only",
  "decision": "auto_scored"
}
```

**`outcome` payload** — written by `hooks/praxis-outcome.py` on `Stop`:

```json
{
  "thinking_used": 9100,
  "input_tokens": 1200,
  "output_tokens": 640,
  "cache_read": null,
  "tool_calls": 0,
  "duration_ms": null,
  "stop_reason": "end_turn"
}
```

The join key is **`(sid, tid)`**. The outcome hook pairs against the most
recent turn id issued by the allocator for the same session, so the two
records are always one-to-one.

## Signing

- Algorithm: **SHA-256 HMAC** over the canonical JSON encoding of the record
  with its `sig` field removed.
- Canonicalisation: sorted keys, compact separators (`,` / `:`), UTF-8, no
  trailing whitespace. Matches Python's
  `json.dumps(sort_keys=True, separators=(',', ':'))` byte-for-byte against
  Node's deterministic encoder in [`lib/receipt.mjs`](../lib/receipt.mjs).
- Key: a 32-byte random key stored at `$PRAXIS_HOME/receipt.key`,
  `chmod 600`, auto-generated on first run. Override with
  `$PRAXIS_RECEIPT_KEY` (hex) for CI.

This is deliberately boring. No PKI, no rotation, no on-chain flex. The
primitive the market is missing is *"every allocation + every outcome is
tamper-evident, joinable, and verifiable locally without a server round-trip"*
— and HMAC gets you there in 200 lines.

## Verifying a ledger

```bash
bin/praxis verify
#   ✓  <home>/allocation-log.jsonl  total=312 ok=312 tampered=0 malformed=0
#   ✓  <home>/outcome-log.jsonl     total=308 ok=308 tampered=0 malformed=0
#
#   summary: 620/620 verified, 0 tampered, 0 malformed
```

Any row whose signature no longer verifies is reported as `tampered`. That's
the forensic signal — whether because someone edited the file, the key was
rotated without re-signing, or (in the hostile case) someone tried to
retroactively rewrite a "surprise" bill.

## The regret ledger

Cost-only reporting was the old Praxis story. The new story is
**honest regret**: *how often were we wrong, and in which direction?*

```bash
bin/praxis report
#
#   PRAXIS regret ledger
#   ──────────────────────────────────────────────────────────────────────
#     allocs=312  outcomes=308  tampered=0  malformed=0
#
#     tier     n   w/outcome   budget       used        util    over%   under%
#     ──────────────────────────────────────────────────────────────────────
#     none    41         41          0          0         —       —      —
#     light   94         93    192,512     142,080      73.8%    5.4%    0.0%
#     medium  82         82    671,744     540,928      80.5%    2.4%    1.2%
#     heavy   59         58    966,656     312,832      32.4%   45.0%    3.4%
#     max     36         34  1,179,648     988,416      83.8%    2.9%   14.7%
#     ──────────────────────────────────────────────────────────────────────
#     TOTAL  312        308  3,010,560   1,984,256      65.9%   14.6%    4.5%
```

- **`over%`** — turns where `thinking_used < 25% of budget`. Paid for
  thinking we didn't do. **Anthropic's bill minus our regret on this row is
  the honest "savings" figure.**
- **`under%`** — turns that hit `stop_reason = max_tokens`. Paid too little;
  model ran out of runway.
- **`util`** — mean utilisation. Close to 1.0 and `under%` low = well
  calibrated at this tier. Low and stable = systematic over-allocation.
- **`unknown` tier rows** indicate receipts from a pre-1.1 allocator and can
  be ignored; re-run the turns to refresh.

## Calibration curve

```bash
bin/praxis calibrate
#
#   score   n   util    under%
#   ──────────────────────────────
#      1   37    —        —
#      2    4    —        —
#      3   48   38.1%    0.0%
#   ...
#     10   18   96.0%   27.8%
```

A well-calibrated scorer produces monotone utilisation — i.e. higher
complexity scores spend a higher fraction of their budget. Flat columns
mean the scorer is not doing useful work at that score.

## Invariants the Verification Layer guarantees

1. Every `alloc` record is reproducible from its payload: given the same
   prompt + model + policy_version, the scorer produces the same
   complexity, tier, and effort.
2. No `outcome` record exists without a preceding `alloc` on the same
   `(sid, tid)` — the allocator is the only writer of `tid`, and it's
   monotone.
3. Any row whose signature does not verify is *not* silently included in
   reports. `bin/praxis verify` returns non-zero; `loadLedger()` surfaces
   the `tampered` count.
4. Cross-language: a receipt signed by `hooks/_praxis_lib.py` (Python)
   verifies under `lib/receipt.mjs` (Node) and vice-versa.

## What this does **not** do (yet)

- **Key rotation.** If you regenerate `receipt.key`, prior records become
  unverifiable. Planned: multi-key verifier with key ids.
- **Provider-signed attestation.** Today the user signs their own receipts.
  A future upgrade would co-sign with an Anthropic-issued attestation
  (`Claude-Reasoning-Receipt` response header or similar) so the user can
  *prove to Anthropic* what was delivered, not just to themselves.
- **Quality signal.** `stop_reason` is a floor. Edit-distance, retry
  detection, and shadow-delta scoring land in Week 3 (see the project
  roadmap).

## One-liner pitch

> Your provider tells you the model "thought hard." Praxis is the open-source
> policy layer that decides *how* hard, records every decision as a
> verifiable receipt, and closes the loop so you find out when it's lying —
> across Claude, GPT, and Gemini.
