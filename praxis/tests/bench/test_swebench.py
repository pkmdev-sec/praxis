"""
PRAXIS — SWE-bench loader + scorer tests.

Exercises:
  - ``SweBenchInstance.from_hf_row`` normalises both list and JSON-string
    shapes for FAIL_TO_PASS / PASS_TO_PASS (HF dataset has both in the wild).
  - Prompt building produces diff-only instructions.
  - ``SweBenchScorer`` extracts diffs from prose-wrapped model output.
  - The stub evaluator returns 0 (deliberately; non-configured runs must
    produce a legible "0 %" chart, not optimistic silence).
  - ``load_from_jsonl`` round-trips a dumped row back into a Task.
  - ``fixture_tasks`` yields three real-looking instances for CI coverage.

Does NOT exercise ``load_from_hf`` (requires network + datasets package).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_PKG = _HERE.parent.parent
sys.path.insert(0, str(_PKG))

from praxis.bench.swebench import (
    SweBenchInstance,
    SweBenchScorer,
    build_prompt,
    fixture_tasks,
    load_from_jsonl,
    make_tasks,
    stub_eval_fn,
    _extract_patch,
)
from praxis.bench.core import Task
from praxis.receipt import _reset_key_cache


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("PRAXIS_HOME", str(tmp_path))
    monkeypatch.setenv("PRAXIS_RECEIPT_KEY", "ab" * 32)
    _reset_key_cache()
    yield


# ── Instance parsing ────────────────────────────────────────────────────────


def test_from_hf_row_accepts_list_shape():
    """Pre-parsed list-of-strings (common in datasets>=2.0) must pass through."""
    row = {
        "instance_id": "django__django-1",
        "repo": "django/django",
        "base_commit": "deadbeef",
        "problem_statement": "Do the thing.",
        "FAIL_TO_PASS": ["test_a", "test_b"],
        "PASS_TO_PASS": ["test_c"],
        "patch": "", "test_patch": "",
    }
    inst = SweBenchInstance.from_hf_row(row)
    assert inst.instance_id == "django__django-1"
    assert inst.fail_to_pass == ["test_a", "test_b"]
    assert inst.pass_to_pass == ["test_c"]


def test_from_hf_row_accepts_json_string_shape():
    """Legacy HF dump format stores the lists as JSON strings."""
    row = {
        "instance_id": "sympy__sympy-9",
        "repo": "sympy/sympy",
        "base_commit": "abc",
        "problem_statement": "Fix Symbol pickling.",
        "FAIL_TO_PASS": '["test_x", "test_y"]',
        "PASS_TO_PASS": '["test_z"]',
        "patch": "", "test_patch": "",
    }
    inst = SweBenchInstance.from_hf_row(row)
    assert inst.fail_to_pass == ["test_x", "test_y"]
    assert inst.pass_to_pass == ["test_z"]


def test_from_hf_row_handles_corrupt_lists_gracefully():
    """Non-JSON strings land as a single-element list rather than crash."""
    row = {
        "instance_id": "x",
        "FAIL_TO_PASS": "test_not_json",
        "PASS_TO_PASS": "also_not_json",
    }
    inst = SweBenchInstance.from_hf_row(row)
    assert inst.fail_to_pass == ["test_not_json"]


# ── Prompt building ─────────────────────────────────────────────────────────


def test_build_prompt_is_diff_only_and_omits_hints_by_default():
    inst = SweBenchInstance(
        instance_id="x", repo="acme/proj", base_commit="deadbeefcafe00",
        problem_statement="Fix the flaky test in test_widget.py",
        hints_text="The root cause is in widget_factory.py",
        fail_to_pass=[], pass_to_pass=[], patch="", test_patch="",
    )
    prompt = build_prompt(inst)
    assert "acme/proj" in prompt
    assert "deadbeefcafe" in prompt
    assert "Fix the flaky test" in prompt
    assert "Hints:" not in prompt
    assert "unified diff" in prompt
    assert "ONLY the diff" in prompt


def test_build_prompt_includes_hints_when_requested():
    inst = SweBenchInstance(
        instance_id="x", repo="r", base_commit="b",
        problem_statement="ps", hints_text="useful context",
        fail_to_pass=[], pass_to_pass=[], patch="", test_patch="",
    )
    prompt = build_prompt(inst, include_hints=True)
    assert "Hints:" in prompt
    assert "useful context" in prompt


# ── Patch extraction ───────────────────────────────────────────────────────


def test_extract_patch_strips_prose_preamble():
    """Models that ignore the 'output only the diff' rule must still score."""
    answer = (
        "Sure, here's the fix. I'll make the change to the file:\n"
        "\n"
        "diff --git a/x.py b/x.py\n"
        "--- a/x.py\n"
        "+++ b/x.py\n"
        "@@ -1 +1 @@\n"
        "-old\n"
        "+new\n"
    )
    patch = _extract_patch(answer)
    assert patch.startswith("diff --git")
    assert "Sure, here's the fix" not in patch


def test_extract_patch_strips_code_fence():
    answer = "```diff\ndiff --git a/x.py b/x.py\n---\n```\ntrailing prose"
    patch = _extract_patch(answer)
    assert patch.startswith("diff --git")
    assert "trailing prose" not in patch


def test_extract_patch_returns_raw_when_no_marker():
    """If the model produced no diff marker, let the evaluator fail honestly."""
    answer = "I'm afraid I can't do that."
    assert _extract_patch(answer) == "I'm afraid I can't do that."


# ── Scoring ────────────────────────────────────────────────────────────────


def test_stub_eval_always_fails():
    """Critical: un-configured benchmarks must produce a 0 % chart, not optimism."""
    inst = fixture_tasks()[0].meta["instance"]
    verdict = stub_eval_fn(inst, "diff --git a/x b/x\n...")
    assert verdict["resolved"] is False
    assert verdict.get("eval_stubbed") is True


def test_scorer_maps_resolved_true_to_1_0():
    def my_eval(instance, patch):
        return {"resolved": True}

    scorer = SweBenchScorer(eval_fn=my_eval)
    task = fixture_tasks(scorer_fn=my_eval)[0]
    assert scorer(task, "diff --git a/x b/x\n---") == 1.0


def test_scorer_maps_resolved_false_to_0_0():
    scorer = SweBenchScorer(eval_fn=lambda i, p: {"resolved": False})
    task = fixture_tasks()[0]
    # Even a real-looking diff gets 0 when the evaluator says no.
    assert scorer(task, "diff --git a/x b/x\n---") == 0.0


def test_scorer_returns_0_on_missing_diff():
    scorer = SweBenchScorer(eval_fn=lambda i, p: {"resolved": True})
    task = fixture_tasks()[0]
    assert scorer(task, "I can't help with that.") == 0.0


def test_scorer_swallows_evaluator_exceptions():
    """A crashing evaluator must not break the whole sweep."""
    def boom(instance, patch):
        raise RuntimeError("docker ran out of memory")
    scorer = SweBenchScorer(eval_fn=boom)
    task = fixture_tasks(scorer_fn=boom)[0]
    assert scorer(task, "diff --git a/x b/x\n---") == 0.0


# ── Loaders ────────────────────────────────────────────────────────────────


def test_fixture_tasks_produces_real_looking_instances():
    tasks = fixture_tasks()
    assert len(tasks) == 3
    for t in tasks:
        assert isinstance(t, Task)
        inst = t.meta["instance"]
        assert isinstance(inst, SweBenchInstance)
        # Real instances have real repos and FAIL_TO_PASS lists.
        assert "/" in inst.repo
        assert inst.base_commit
        assert inst.fail_to_pass, "fixture is empty; at least one FAIL_TO_PASS required"
        assert "unified diff" in t.prompt


def test_load_from_jsonl_roundtrip(tmp_path):
    """Dump two rows, load them back, assert the shape."""
    rows = [
        {
            "instance_id": "roundtrip-1",
            "repo": "acme/alpha",
            "base_commit": "cafef00d",
            "problem_statement": "Problem one.",
            "FAIL_TO_PASS": ["t1", "t2"],
            "PASS_TO_PASS": ["t3"],
            "patch": "p1", "test_patch": "tp1",
        },
        {
            "instance_id": "roundtrip-2",
            "repo": "acme/beta",
            "base_commit": "deadbeef",
            "problem_statement": "Problem two.",
            "FAIL_TO_PASS": '["t4"]',   # legacy string form
            "PASS_TO_PASS": '["t5"]',
            "patch": "", "test_patch": "",
        },
    ]
    path = tmp_path / "swebench.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")

    tasks = list(load_from_jsonl(path))
    assert [t.id for t in tasks] == ["roundtrip-1", "roundtrip-2"]
    assert tasks[0].meta["instance"].fail_to_pass == ["t1", "t2"]
    assert tasks[1].meta["instance"].fail_to_pass == ["t4"]  # JSON-string decoded


def test_load_from_jsonl_respects_limit(tmp_path):
    rows = [
        {"instance_id": f"lim-{i}", "repo": "r", "base_commit": "b",
         "problem_statement": f"p{i}", "FAIL_TO_PASS": [], "PASS_TO_PASS": [],
         "patch": "", "test_patch": ""}
        for i in range(5)
    ]
    path = tmp_path / "sb.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    tasks = list(load_from_jsonl(path, limit=2))
    assert len(tasks) == 2



# ── Realism invariants ──────────────────────────────────────────────────────


def test_realistic_swebench_prompt_scores_at_heavy_or_max():
    """
    A real SWE-bench problem statement (~1000+ chars with architecture/debug
    vocabulary) must land the scorer at heavy or max. Without this, Praxis's
    amplifiers never fire on real benchmarks and the capability claim
    evaporates.

    This test is a guardrail: if the scorer ever regresses into rating
    long, substantive problem statements as 'light', Praxis stops providing
    lift on real benchmarks.
    """
    from praxis import score_complexity
    realistic = SweBenchInstance(
        instance_id="django__django-11019",
        repo="django/django",
        base_commit="93e892bb645b16ebaf287beb5fe7f3ffe8d10408",
        problem_statement=(
            "When merging three or more media objects using their __add__ "
            "method, Django's media system can throw MediaOrderConflictWarnings "
            "that are incorrect. The issue is that when Media objects have "
            "overlapping JS/CSS files with different orders, the merge algorithm "
            "produces warnings even when the orders are actually compatible.\n\n"
            "The root cause is the left-fold merge order interacting with the "
            "warning detection logic in Media.__add__. The fix should produce "
            "a consistent ordering that merges the underlying lists without "
            "spurious warnings. Design a solution that handles the distributed "
            "ordering constraint efficiently."
        ),
        hints_text="",
        fail_to_pass=["test_merge_warning (forms_tests.test_media)"],
        pass_to_pass=[], patch="", test_patch="",
    )
    prompt = build_prompt(realistic)
    score = score_complexity(prompt)
    # At minimum we expect heavy (7+). Max (9-10) is what the default
    # policy actually wants; anything lower means the amplifiers will
    # skip this prompt, which is the failure mode we're guarding against.
    assert score >= 7, (
        f"Realistic SWE-bench prompt scored {score}; expected >= 7. "
        f"Praxis amplifiers won't fire on real benchmarks if the scorer "
        f"rates substantive problems as light or medium."
    )
