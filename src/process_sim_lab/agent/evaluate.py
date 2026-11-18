"""Run the evaluation cases of the agent layer and report pass or fail per case.

Usage:

    python3 -m process_sim_lab.agent.evaluate [--cases DIR]

DIR defaults to ``evals/cases`` of the repository. Each ``*.json`` file there is one case, run in file-name order:

    {
      "id": "cstr-first-order",
      "description": "what the case checks",
      "source": "where the expected values come from (a unit test and its hand check)",
      "call": {"name": "cstr", "arguments": {...}},
      "expected": [
        {"pointer": "/conversion", "value": 0.8333333333333334, "abs_tol": 1e-12},
        {"pointer": "/phase", "value": "two-phase"}
      ]
    }

A case passes when ``run_tool`` returns ``ok`` and every expected value is found in its "result" at the JSON pointer
(RFC 6901): a number within ``abs_tol`` (required for numbers), anything else equal. The command exits with 0 when
every case passes, otherwise 1. No LLM is called: the cases are fixed tool calls, so the same check can later grade
the calls an agent makes.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from process_sim_lab.agent.runner import run_tool

DEFAULT_CASES = Path(__file__).resolve().parents[3] / "evals" / "cases"

_CASE_KEYS = {"id", "description", "source", "call", "expected"}
_CALL_KEYS = {"name", "arguments"}


@dataclass(frozen=True)
class Expectation:
    pointer: str
    value: Any
    abs_tol: float | None


@dataclass(frozen=True)
class Case:
    id: str
    description: str
    source: str
    tool: str
    arguments: Any
    expected: tuple[Expectation, ...]


@dataclass(frozen=True)
class CaseResult:
    case: Case
    passed: bool
    failures: tuple[str, ...]


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def parse_case(obj: Any, where: str) -> Case:
    """Build a Case from its JSON form; ``where`` names the file in error messages."""
    if not isinstance(obj, Mapping):
        raise ValueError(f"{where}: a case must be a JSON object")
    if set(obj) != _CASE_KEYS:
        raise ValueError(f"{where}: a case needs exactly the keys {sorted(_CASE_KEYS)}, got {sorted(obj)}")
    for key in ("id", "description", "source"):
        if not isinstance(obj[key], str) or not obj[key]:
            raise ValueError(f"{where}: {key!r} must be a non-empty string")
    call = obj["call"]
    if not isinstance(call, Mapping) or set(call) != _CALL_KEYS or not isinstance(call["name"], str):
        raise ValueError(f"{where}: 'call' must be {{\"name\": str, \"arguments\": ...}}")
    if not isinstance(obj["expected"], list) or not obj["expected"]:
        raise ValueError(f"{where}: 'expected' must be a non-empty list")
    expected = []
    for i, e in enumerate(obj["expected"]):
        if not isinstance(e, Mapping) or not {"pointer", "value"} <= set(e) <= {"pointer", "value", "abs_tol"}:
            raise ValueError(f"{where}: expected[{i}] needs 'pointer' and 'value', and may have 'abs_tol'")
        if not isinstance(e["pointer"], str) or not e["pointer"].startswith("/"):
            raise ValueError(f"{where}: expected[{i}].pointer must be a JSON pointer such as '/conversion'")
        tol = e.get("abs_tol")
        if _is_number(e["value"]) and not (_is_number(tol) and math.isfinite(tol) and tol >= 0):
            raise ValueError(f"{where}: expected[{i}] is a number and needs a finite abs_tol >= 0")
        expected.append(Expectation(e["pointer"], e["value"], tol))
    return Case(obj["id"], obj["description"], obj["source"], call["name"], call["arguments"], tuple(expected))


def load_cases(directory: Path) -> list[Case]:
    """Every ``*.json`` case in ``directory``, in file-name order."""
    files = sorted(Path(directory).glob("*.json"))
    if not files:
        raise ValueError(f"no case files (*.json) in {directory}")
    cases = [parse_case(json.loads(f.read_text(encoding="utf-8")), f.name) for f in files]
    ids = [c.id for c in cases]
    if len(set(ids)) != len(ids):
        raise ValueError(f"case ids repeat: {ids}")
    return cases


def resolve_pointer(document: Any, pointer: str) -> Any:
    """The value at a JSON pointer (RFC 6901); KeyError when it does not exist."""
    value = document
    for token in pointer.split("/")[1:]:
        token = token.replace("~1", "/").replace("~0", "~")
        if isinstance(value, list):
            if not token.isdigit() or int(token) >= len(value):
                raise KeyError(pointer)
            value = value[int(token)]
        elif isinstance(value, Mapping) and token in value:
            value = value[token]
        else:
            raise KeyError(pointer)
    return value


def run_case(case: Case) -> CaseResult:
    """Run the case's tool call and compare the result with every expectation."""
    out = run_tool(case.tool, case.arguments)
    if not out["ok"]:
        error = out["error"]
        return CaseResult(case, False, (f"tool call failed: {error['type']}: {error['message']}",))
    failures = []
    for e in case.expected:
        try:
            got = resolve_pointer(out["result"], e.pointer)
        except KeyError:
            failures.append(f"{e.pointer}: not in the result")
            continue
        if e.abs_tol is not None and _is_number(e.value):
            if not _is_number(got) or not abs(got - e.value) <= e.abs_tol:
                failures.append(f"{e.pointer}: expected {e.value} +/- {e.abs_tol}, got {got!r}")
        elif got != e.value:
            failures.append(f"{e.pointer}: expected {e.value!r}, got {got!r}")
    return CaseResult(case, not failures, tuple(failures))


def evaluate(cases: Sequence[Case]) -> list[CaseResult]:
    """Run every case."""
    return [run_case(c) for c in cases]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python3 -m process_sim_lab.agent.evaluate", description=__doc__.splitlines()[0]
    )
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES, help=f"case folder (default: {DEFAULT_CASES})")
    args = parser.parse_args(argv)

    results = evaluate(load_cases(args.cases))
    for r in results:
        checks = len(r.case.expected)
        print(f"{'PASS' if r.passed else 'FAIL'}  {r.case.id}  ({r.case.tool}, {checks} check{'s' * (checks != 1)})")
        for failure in r.failures:
            print(f"      {failure}")
    passed = sum(r.passed for r in results)
    print(f"{passed}/{len(results)} cases passed")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
