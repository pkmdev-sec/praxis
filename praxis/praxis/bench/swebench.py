"""
PRAXIS — SWE-bench Verified loader.

Dataset: ``princeton-nlp/SWE-bench_Verified`` on Hugging Face. 500 manually-
reviewed Python repo-level issues with gold patches + `FAIL_TO_PASS` /
`PASS_TO_PASS` test lists per instance.

The dataset surface is simple enough that we offer *three* load modes, in
increasing reliance on external infrastructure:

  1. :func:`load_from_hf`         — the official path. Requires the
                                    ``datasets`` package and network access.
  2. :func:`load_from_jsonl`      — read a user-exported JSONL dump. Works
                                    offline, pins reproducibility to a file.
  3. :func:`fixture_tasks`        — tiny hand-curated subset (3 real
                                    instances, shapes verified) used by CI
                                    so the loader contract is tested without
                                    pulling HF. Not for publication claims.

All three produce the same :class:`praxis.bench.Task` objects and the
harness doesn't care which you used.

## Scoring

SWE-bench Verified isn't scored by string-matching. The canonical scorer
applies the model's patch to a Docker-isolated copy of the repo at the
instance's base commit, runs the `FAIL_TO_PASS` + `PASS_TO_PASS` tests,
and requires every `FAIL_TO_PASS` to flip green and every `PASS_TO_PASS`
to stay green. We expose this as :class:`SweBenchScorer`, which takes an
``eval_fn: (instance, patch) -> dict`` callable — the user wires up
their preferred harness (`swebench.harness`, `SWE-bench Lite runner`,
etc.) and the Praxis side handles scoring + receipt emission.

The default ``eval_fn`` in this module is **stub only** — it returns
0 for every patch. That's deliberate: we don't want to silently pretend
a run passed. Users plug in a real evaluator; the stub just makes CI
testable.

## Minimum viable usage

```python
from praxis.bench import run_bench, summarise
from praxis.bench.swebench import load_from_hf, SweBenchScorer
from praxis.bench.anthropic_adapter import anthropic_llm

tasks = list(load_from_hf(split="test", limit=10, scorer_fn=my_real_eval))
arms = [...]   # as in docs/benchmarks.md
results = run_bench(tasks, arms, bench_name="swebench-verified-n10")
print(summarise(results).rendered())
```
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

from .core import Task


__all__ = [
    "SweBenchInstance",
    "SweBenchScorer",
    "load_from_hf",
    "load_from_jsonl",
    "fixture_tasks",
    "build_prompt",
    "make_tasks",
]


# ── Instance shape ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class SweBenchInstance:
    """The subset of SWE-bench Verified fields Praxis actually needs."""

    instance_id: str
    repo: str
    base_commit: str
    problem_statement: str
    hints_text: str
    fail_to_pass: List[str]
    pass_to_pass: List[str]
    patch: str                   # gold patch — reference for debugging only
    test_patch: str              # test setup; required for scoring
    version: str = ""
    environment_setup_commit: Optional[str] = None

    @classmethod
    def from_hf_row(cls, row: Dict[str, Any]) -> "SweBenchInstance":
        """Parse a single HF row into our typed shape.

        The HF schema uses `FAIL_TO_PASS` / `PASS_TO_PASS` as JSON-string
        fields (list-of-strings wrapped in quotes). We normalise here so the
        rest of the codebase sees plain ``list[str]``.
        """
        def _list(v: Any) -> List[str]:
            if isinstance(v, list):
                return [str(x) for x in v]
            if isinstance(v, str):
                try:
                    parsed = json.loads(v)
                    return [str(x) for x in parsed] if isinstance(parsed, list) else [v]
                except json.JSONDecodeError:
                    return [v]
            return []
        return cls(
            instance_id=str(row.get("instance_id", "")),
            repo=str(row.get("repo", "")),
            base_commit=str(row.get("base_commit", "")),
            problem_statement=str(row.get("problem_statement", "")),
            hints_text=str(row.get("hints_text", "")),
            fail_to_pass=_list(row.get("FAIL_TO_PASS")),
            pass_to_pass=_list(row.get("PASS_TO_PASS")),
            patch=str(row.get("patch", "")),
            test_patch=str(row.get("test_patch", "")),
            version=str(row.get("version", "")),
            environment_setup_commit=row.get("environment_setup_commit"),
        )


# ── Prompt building ─────────────────────────────────────────────────────────


def build_prompt(instance: SweBenchInstance, *, include_hints: bool = False) -> str:
    """
    Canonical SWE-bench prompt shape.

    We deliberately keep this prompt simple and neutral — no system-prompt
    jailbreaks, no "you are the world's best engineer" flattery. The whole
    point of benchmarking is that the prompt is fair to every arm.

    The output format instruction is important: the evaluator is a diff
    applier, so we ask for a unified diff and nothing else.
    """
    parts = [
        f"Repository: {instance.repo} @ {instance.base_commit[:12]}",
        "",
        "Task:",
        instance.problem_statement.strip(),
    ]
    if include_hints and instance.hints_text.strip():
        parts += ["", "Hints:", instance.hints_text.strip()]
    parts += [
        "",
        "Produce a unified diff (git-style, starting with `diff --git`) that "
        "resolves the issue. The diff will be applied to the repository at "
        "the specified base commit and the project's tests will be run. "
        "Output ONLY the diff, no prose.",
    ]
    return "\n".join(parts)


# ── Scoring ─────────────────────────────────────────────────────────────────

# Type for the pluggable evaluator. The user hooks in their preferred
# SWE-bench harness — we don't care whether it's Docker-based, modal-
# based, or a simple subprocess. What matters is the contract:
#
#   eval_fn(instance: SweBenchInstance, patch: str) -> dict
#
# with at least ``{"resolved": bool}`` in the returned dict. Additional
# keys land in the bench receipt for forensics.
EvalFn = Callable[[SweBenchInstance, str], Dict[str, Any]]


def stub_eval_fn(instance: SweBenchInstance, patch: str) -> Dict[str, Any]:
    """
    No-op evaluator that never resolves an issue.

    Deliberate design: if the user hasn't wired up a real evaluator, every
    task fails. That means an un-configured harness produces a legible
    "0 % solve rate" chart rather than a silently-correct one. Far safer
    than returning a random or optimistic verdict.
    """
    return {
        "resolved": False,
        "eval_stubbed": True,
        "message": "no evaluator configured; use SweBenchScorer(eval_fn=...) to wire one in",
    }


class SweBenchScorer:
    """
    Task-level scorer. Applies the model's answer as a patch via the
    pluggable ``eval_fn``, normalises the verdict to a float in {0.0, 1.0}.

    Holds instance metadata so it can look up the right FAIL/PASS lists at
    scoring time (Task objects are frozen; scorer state lives here).
    """

    def __init__(self, eval_fn: EvalFn = stub_eval_fn):
        self._eval_fn = eval_fn

    def __call__(self, task: Task, answer: str) -> float:
        instance = task.meta.get("instance")
        if not isinstance(instance, SweBenchInstance):
            return 0.0
        patch = _extract_patch(answer)
        # Require a real diff marker. If the model returned prose or an
        # apology, short-circuit with 0 — applying a non-diff to a repo is
        # a category error, not a scoring question.
        if not patch.strip() or "diff --git" not in patch:
            return 0.0
        try:
            verdict = self._eval_fn(instance, patch) or {}
        except Exception as e:  # noqa: BLE001
            # Crashing evaluators must not break the whole sweep.
            verdict = {"resolved": False, "error": str(e)}
        return 1.0 if verdict.get("resolved") else 0.0


def _extract_patch(answer: str) -> str:
    """
    Strip any prose surrounding the diff.

    Models occasionally ignore the "output only the diff" instruction.
    We look for the first ``diff --git`` and take everything from there.
    If no diff marker is found, return the raw string and let the
    evaluator fail gracefully.
    """
    marker = "diff --git"
    idx = answer.find(marker)
    if idx < 0:
        return answer.strip()
    tail = answer[idx:]
    # If the model wrapped the diff in a code fence (```diff), strip the
    # trailing fence.
    fence = tail.find("\n```")
    if fence > 0:
        tail = tail[:fence]
    return tail.strip()


# ── Loaders ─────────────────────────────────────────────────────────────────


def load_from_hf(
    *,
    split: str = "test",
    limit: Optional[int] = None,
    scorer_fn: EvalFn = stub_eval_fn,
    include_hints: bool = False,
) -> Iterable[Task]:
    """
    Load SWE-bench Verified from Hugging Face.

    Requires ``pip install datasets``. If the package isn't installed we
    raise a clear ImportError pointing at the install command — we do
    not silently fall back to the fixture.
    """
    try:
        from datasets import load_dataset  # type: ignore
    except ImportError as e:  # pragma: no cover
        raise ImportError(
            "praxis.bench.swebench.load_from_hf requires the 'datasets' package. "
            "Install with: pip install datasets"
        ) from e

    ds = load_dataset("princeton-nlp/SWE-bench_Verified", split=split)
    if limit is not None:
        ds = ds.select(range(min(limit, len(ds))))
    return make_tasks(
        (SweBenchInstance.from_hf_row(row) for row in ds),
        scorer_fn=scorer_fn,
        include_hints=include_hints,
    )


def load_from_jsonl(
    path: str | os.PathLike,
    *,
    limit: Optional[int] = None,
    scorer_fn: EvalFn = stub_eval_fn,
    include_hints: bool = False,
) -> Iterable[Task]:
    """
    Load SWE-bench instances from a JSONL file dumped offline.

    Each line is a row in the same shape as the HF dataset. Useful for
    airgapped CI and for pinning an exact dataset version to a run.
    """
    path = Path(path)
    rows = []
    with path.open("r", encoding="utf-8") as fh:
        for i, raw in enumerate(fh):
            line = raw.strip()
            if not line:
                continue
            if limit is not None and len(rows) >= limit:
                break
            rows.append(SweBenchInstance.from_hf_row(json.loads(line)))
    return make_tasks(rows, scorer_fn=scorer_fn, include_hints=include_hints)


def fixture_tasks(*, scorer_fn: EvalFn = stub_eval_fn) -> List[Task]:
    """
    Three real SWE-bench Verified instances, hand-inlined for CI.

    Field values are condensed — long problem statements are truncated
    and gold patches elided — but instance_id, repo, base_commit, and
    FAIL_TO_PASS come from the real dataset. Good enough for loader-
    contract tests; not valid for published claims.

    If you need CI coverage over more instances, use ``load_from_jsonl``
    with a file you dumped yourself.
    """
    fixtures = [
        SweBenchInstance(
            instance_id="django__django-11019",
            repo="django/django",
            base_commit="93e892bb645b16ebaf287beb5fe7f3ffe8d10408",
            problem_statement=(
                "Merging 3 or more media objects can throw unnecessary "
                "MediaOrderConflictWarnings."
            ),
            hints_text="",
            fail_to_pass=["test_merge_warning (forms_tests.test_media)"],
            pass_to_pass=["test_combine_media (forms_tests.test_media)"],
            patch="",
            test_patch="",
            version="3.0",
        ),
        SweBenchInstance(
            instance_id="sympy__sympy-20590",
            repo="sympy/sympy",
            base_commit="cffd4e0f86fefd4802349a9f9b19ed70934ea354",
            problem_statement=(
                "Symbol instances have __dict__ since 1.7 — a regression "
                "that breaks pickling in downstream projects."
            ),
            hints_text="",
            fail_to_pass=["test_Symbol_no_dict (sympy.core.tests.test_symbol)"],
            pass_to_pass=["test_Symbol (sympy.core.tests.test_symbol)"],
            patch="",
            test_patch="",
            version="1.7",
        ),
        SweBenchInstance(
            instance_id="scikit-learn__scikit-learn-14894",
            repo="scikit-learn/scikit-learn",
            base_commit="fdbaa58acbead5a254f2e6d597dc1ab3b947f4c6",
            problem_statement=(
                "ZeroDivisionError in _sparse_fit for SVM with empty "
                "support_vectors_."
            ),
            hints_text="",
            fail_to_pass=["sklearn/svm/tests/test_svm.py::test_sparse_fit_support_vectors_empty"],
            pass_to_pass=["sklearn/svm/tests/test_svm.py::test_sparse_fit"],
            patch="",
            test_patch="",
            version="0.22",
        ),
    ]
    return list(make_tasks(fixtures, scorer_fn=scorer_fn))


def make_tasks(
    instances: Iterable[SweBenchInstance],
    *,
    scorer_fn: EvalFn = stub_eval_fn,
    include_hints: bool = False,
) -> Iterable[Task]:
    """
    Convert SWE-bench instances into :class:`praxis.bench.Task`.

    One scorer per run (wired in once); every task gets the same
    instance attached via ``Task.meta`` so the scorer can look up the
    FAIL/PASS lists.
    """
    scorer = SweBenchScorer(eval_fn=scorer_fn)
    for inst in instances:
        yield Task(
            id=inst.instance_id,
            prompt=build_prompt(inst, include_hints=include_hints),
            reference=None,         # no string reference; scorer is patch-based
            scorer=scorer,
            meta={
                "instance": inst,
                "repo": inst.repo,
                "base_commit": inst.base_commit,
                "fail_to_pass_n": len(inst.fail_to_pass),
                "pass_to_pass_n": len(inst.pass_to_pass),
            },
        )
