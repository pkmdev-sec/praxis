"""
PRAXIS — Capability policy.

Mapping from tier → **set of active test-time-compute amplifiers**. The
scorer gives an honest complexity estimate; the policy decides which
capability levers to pull at each tier.

Amplifiers currently implemented:
  - ``escalate_on_max_tokens`` — if the model hits max_tokens, retry one
    tier higher (bounded; see :mod:`praxis.escalation`).
  - ``reflect_on_complex``     — after the primary answer, run a
    self-critique pass and revise if needed (see :mod:`praxis.reflection`).
  - (deferred) ``sample_k`` — self-consistency: sample k answers, pick best.
    Multiplicative cost; shipped when we have Pareto data to calibrate k.

Defaults err toward capability extraction at `heavy`/`max`, while leaving
`light`/`none` untouched so easy prompts stay cheap. This embodies the
"honest scoring + opt-in amplifiers" choice — the scorer is unchanged;
amplifiers only fire where they pay back.

Users override via a single dict::

    from praxis.policy import Policy, TierPolicy

    my_policy = Policy({
        "heavy": TierPolicy(escalate=True, reflect=True),
        "max":   TierPolicy(escalate=True, reflect=True),
    })

All overrides merge onto the default policy; omitted tiers keep defaults.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Dict, Optional

__all__ = [
    "TierPolicy",
    "Policy",
    "DEFAULT_POLICY",
]


@dataclass(frozen=True)
class TierPolicy:
    """Which capability amplifiers fire for a single tier."""

    # Retry at tier+1 on ``stop_reason=max_tokens``. Bounded by
    # ``max_escalation_hops`` to prevent runaway loops.
    escalate: bool = False
    max_escalation_hops: int = 1

    # Run a reflection pass (self-critique + revise) after the primary call.
    # See :mod:`praxis.reflection`. Costs roughly 1× a normal turn.
    reflect: bool = False

    # Prefer DroidX as the reflector when available; fall back to self-
    # reflection (same model) when not.
    prefer_droidx_reflector: bool = True

    # (reserved for sample_k) — number of parallel samples; 1 = off.
    sample_k: int = 1


# The default policy encodes: more amplifiers at higher tiers, nothing at
# low tiers. Each default here is a design decision that maps a *capability
# claim* we want the framework to defend.
_DEFAULTS: Dict[str, TierPolicy] = {
    # "none" tier: trivial prompts. No amplifiers; keep the cheap path cheap.
    "none":   TierPolicy(),
    # "light": easy edits / factual follow-ups. No amplifiers.
    "light":  TierPolicy(),
    # "medium": typical code/implementation. Reflect only if explicitly
    # configured — usually not worth the 2× cost on routine work.
    "medium": TierPolicy(),
    # "heavy": complex design/debug. Escalate on max_tokens (high-value prompts
    # should not silently truncate), reflect for quality.
    "heavy":  TierPolicy(escalate=True, reflect=True, max_escalation_hops=1),
    # "max": the hardest prompts we see. Escalation is already at the ceiling
    # (no tier+1 to escalate to), so escalate=False; reflection pays back.
    "max":    TierPolicy(escalate=False, reflect=True, max_escalation_hops=0),
}


@dataclass(frozen=True)
class Policy:
    """
    A full capability policy covering every tier. Unset tiers fall back to
    defaults. Use :meth:`for_tier` to get the effective :class:`TierPolicy`.
    """

    tiers: Dict[str, TierPolicy] = field(default_factory=dict)

    def for_tier(self, tier: str) -> TierPolicy:
        """Return the effective policy for a tier (user override or default)."""
        return self.tiers.get(tier) or _DEFAULTS.get(tier, TierPolicy())

    def override(self, **tiers: TierPolicy) -> "Policy":
        """Return a new Policy with specific tiers replaced."""
        merged = dict(self.tiers)
        merged.update(tiers)
        return replace(self, tiers=merged)

    @classmethod
    def from_dict(cls, d: Optional[Dict[str, dict]]) -> "Policy":
        """Build a Policy from a plain config dict (e.g. loaded YAML/TOML)."""
        if not d:
            return cls()
        tiers = {}
        for name, body in d.items():
            if isinstance(body, TierPolicy):
                tiers[name] = body
            elif isinstance(body, dict):
                tiers[name] = TierPolicy(**body)
        return cls(tiers=tiers)


# The canonical default instance. Import this as
# ``from praxis.policy import DEFAULT_POLICY`` when you want the shipped
# defaults; instantiate ``Policy(...)`` to override.
DEFAULT_POLICY = Policy()
