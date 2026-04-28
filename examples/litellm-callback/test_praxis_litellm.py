"""
Unit tests for the Praxis × LiteLLM callback.

These tests do not require LiteLLM itself — the callback ships with a
fallback `CustomLogger` base that lets us exercise the injection logic in
isolation.

Run: python -m unittest examples/litellm-callback/test_praxis_litellm.py
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from praxis_litellm import decide, PraxisCallback  # noqa: E402


class DecideTest(unittest.TestCase):
    def test_trivial_prompt_maps_to_none_effort(self):
        d = decide("What is 2+2?", "claude-opus-4-7")
        self.assertEqual(d.effort, None)
        self.assertEqual(d.tokens, 0)
        self.assertEqual(d.tier, "none")

    def test_design_prompt_escalates_to_high_or_above(self):
        d = decide("Design a scalable distributed caching system", "claude-opus-4-7")
        self.assertIn(d.effort, ("high", "xhigh", "max"))
        self.assertEqual(d.model_family, "adaptive_only")

    def test_opus_4_5_lands_in_manual_family(self):
        d = decide("Refactor this function", "claude-opus-4-5")
        self.assertEqual(d.model_family, "manual")


class InjectionTest(unittest.TestCase):
    def setUp(self):
        self.cb = PraxisCallback()

    def _run(self, model, text, **extra):
        kwargs = dict(extra)
        self.cb._inject(model, [{"role": "user", "content": text}], kwargs)
        return kwargs

    def test_opus_4_7_injects_adaptive_effort(self):
        kw = self._run("claude-opus-4-7", "Design a distributed cache system")
        self.assertEqual(kw["thinking"], {"type": "adaptive"})
        self.assertIn("output_config", kw)
        self.assertIn(kw["output_config"]["effort"], ("high", "xhigh", "max"))
        # Critical: no budget_tokens key anywhere on Opus 4.7.
        self.assertNotIn("budget_tokens", kw.get("thinking", {}))

    def test_opus_4_7_trivial_leaves_no_thinking(self):
        kw = self._run("claude-opus-4-7", "What is Python?")
        self.assertNotIn("thinking", kw)

    def test_opus_4_5_uses_legacy_budget_tokens(self):
        kw = self._run("claude-opus-4-5", "Refactor this function")
        self.assertEqual(kw["thinking"]["type"], "enabled")
        self.assertIn("budget_tokens", kw["thinking"])
        self.assertNotIn("output_config", kw)

    def test_openai_o_series_uses_reasoning_effort(self):
        kw = self._run("o3-mini", "Design a fault-tolerant event-driven pipeline")
        self.assertIn("reasoning_effort", kw)
        self.assertIn(kw["reasoning_effort"], ("low", "medium", "high"))

    def test_openai_xhigh_clamped_to_high(self):
        # OpenAI's enum doesn't have xhigh/max, so Praxis maps both to "high".
        kw = self._run("o3", "Debug complex race condition in concurrent pipeline with memory leak")
        self.assertEqual(kw.get("reasoning_effort"), "high")

    def test_explicit_user_setting_wins(self):
        kw = self._run("claude-opus-4-7", "Design a cache",
                       thinking={"type": "disabled"})
        # Praxis must honour the caller's explicit disable.
        self.assertEqual(kw["thinking"], {"type": "disabled"})

    def test_idempotent(self):
        kw = self._run("claude-opus-4-7", "Design a cache")
        snapshot = dict(kw)
        # Re-entry should not mutate anything further.
        self.cb._inject("claude-opus-4-7",
                        [{"role": "user", "content": "Design a cache"}], kw)
        self.assertEqual(kw, snapshot)


class RecordTest(unittest.TestCase):
    def test_records_budget_utilization_and_flags_over_allocation(self):
        cb = PraxisCallback()
        kwargs = {}
        cb._inject("claude-opus-4-7",
                   [{"role": "user", "content": "Design a scalable distributed system"}],
                   kwargs)
        response = {"usage": {"completion_tokens_details": {"reasoning_tokens": 500}}}
        emitted = {}
        cb._emit = lambda a: emitted.update(a)  # type: ignore[method-assign]
        cb._record(kwargs, response)
        self.assertEqual(emitted["praxis.reasoning_tokens_used"], 500)
        # 500 / 16384 ≈ 0.03, well under 25% → over_allocated.
        self.assertEqual(emitted["praxis.over_allocated"], 1)


if __name__ == "__main__":
    unittest.main()
