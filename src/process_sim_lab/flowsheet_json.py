"""JSON output of a solved flowsheet: its schema, a checker and a command line.

``FlowsheetResult.to_dict()`` (and the ``solve_flowsheet`` tool of the agent layer) returns one JSON object.
``RESULT_SCHEMA`` describes it in the JSON Schema draft 2020-12 form, with the same keyword subset and validator as
the tool schemas (``process_sim_lab.agent.schemas``), so any draft 2020-12 validator can check it too:

    {
      "name": "reactor-flash-recycle",
      "method": "wegstein",                 "direct" or "wegstein"
      "iterations": 3,                      passes run, >= 1
      "residual": 1.44e-12,                 scaled tear residual of the last pass, <= tol
      "tol": 1e-10,                         tolerance the residual met
      "history": [0.897, 0.0924, 1.44e-12], scaled residual of every pass, one per iteration
      "feeds": ["feed"], "products": ["liquid", "purge"], "components": ["A", "I", "B"],
      "streams": {"recycle": {"flows": {"A": 1.0, ...}, "temperature": 330.0, "pressure": 200000.0}, ...},
      "units": {"reactor": {"type": "cstr", "inlets": [...], "outlets": [...], "generation": {"A": -4.6, ...}}, ...},
      "overall_balance": {"A": 0.0, ...}    feeds + generation - products, mol/s
    }

A schema keyword cannot say that a name refers to another part of the document, so ``check_result`` adds these
checks after the schema passes:

    references   every feed, product and unit inlet or outlet is a key of "streams", and every stream is a feed or
                 the outlet of a unit
    components   every component in "flows" and "generation" is listed in "components"; "overall_balance" has one
                 entry per component
    convergence  len(history) == iterations, history[-1] == residual and residual <= tol

Command line (exit code 0 on success; 1 on a bad spec, a unit or convergence error, or an invalid result; 2 on bad
command-line arguments):

    python3 -m process_sim_lab.flowsheet_json solve examples/reactor_flash_recycle.json [-o result.json]
    python3 -m process_sim_lab.flowsheet_json check result.json
    python3 -m process_sim_lab.flowsheet_json schema

``solve`` checks the spec against the ``solve_flowsheet`` tool schema, solves it, checks the result against
``RESULT_SCHEMA`` and writes it (to stdout without ``-o``). ``check`` validates a result file. ``schema`` prints
``RESULT_SCHEMA``.

Units: mol/s for flows, generation and balances; K; Pa. The residual and tol are dimensionless.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from process_sim_lab.agent.schemas import DRAFT, SchemaIssue, _child, validate, validate_arguments
from process_sim_lab.flowsheet import METHODS, UNIT_TYPES, ConvergenceError, solve_flowsheet


def _names(description: str, *, min_items: int = 0) -> dict[str, Any]:
    schema: dict[str, Any] = {"type": "array", "description": description, "items": {"type": "string", "minLength": 1}}
    if min_items:
        schema["minItems"] = min_items
    return schema


def _by_component(description: str, **bounds: float) -> dict[str, Any]:
    return {"type": "object", "description": description, "additionalProperties": {"type": "number", **bounds}}


def _object(description: str, properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "description": description,
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


_STREAM = _object(
    "one stream",
    {
        "flows": _by_component("molar flow by component, mol/s, >= 0", minimum=0),
        "temperature": {"type": "number", "exclusiveMinimum": 0, "description": "temperature, K, > 0"},
        "pressure": {"type": "number", "exclusiveMinimum": 0, "description": "pressure, Pa, > 0"},
    },
)

_UNIT = _object(
    "result of one unit operation",
    {
        "type": {"type": "string", "enum": sorted(UNIT_TYPES), "description": "unit type"},
        "inlets": _names("inlet stream names, in order", min_items=1),
        "outlets": _names("outlet stream names, in order (flash: vapour then liquid)", min_items=1),
        "generation": _by_component("net generation by component, mol/s; < 0 for a reactant, absent when zero"),
    },
)

RESULT_SCHEMA: dict[str, Any] = {
    "$schema": DRAFT,
    "title": "Solved flowsheet",
    **_object(
        "Result of process_sim_lab.flowsheet.solve_flowsheet: every stream, every unit and the convergence record. "
        "SI units: mol/s, K, Pa.",
        {
            "name": {"type": "string", "description": "flowsheet name"},
            "method": {"type": "string", "enum": list(METHODS), "description": "tear update rule"},
            "iterations": {"type": "integer", "minimum": 1, "description": "passes run, count, >= 1"},
            "residual": {"type": "number", "minimum": 0,
                         "description": "scaled tear residual of the last pass, dimensionless, <= tol"},
            "tol": {"type": "number", "exclusiveMinimum": 0,
                    "description": "tolerance on the scaled residual, dimensionless, > 0"},
            "history": {"type": "array", "minItems": 1,
                        "description": "scaled residual of every pass, dimensionless, one per iteration",
                        "items": {"type": "number", "minimum": 0}},
            "feeds": _names("feed stream names", min_items=1),
            "products": _names("product stream names (no unit consumes them)"),
            "components": _names("every component of the flowsheet", min_items=1),
            "streams": {"type": "object", "description": "every stream by name: feeds, internal, tear and product",
                        "additionalProperties": _STREAM},
            "units": {"type": "object", "description": "per-unit results by unit name, in calculation order",
                      "additionalProperties": _UNIT},
            "overall_balance": _by_component("feeds + generation - products by component, mol/s; about 0"),
        },
    ),
}


def check_result(data: Any) -> list[SchemaIssue]:
    """Check a result object against ``RESULT_SCHEMA``, then its references, components and convergence record.

    Returns:
        Every issue found; an empty list when the result is valid. The extra checks run only when the schema passes.
    """
    issues = validate(data, RESULT_SCHEMA)
    if issues:
        return issues

    streams = data["streams"]
    components = set(data["components"])
    produced: set[str] = set()

    def need_stream(name: str, path: str) -> None:
        if name not in streams:
            issues.append(SchemaIssue(path, f"names stream {name!r}, which is not in $.streams"))

    for i, name in enumerate(data["feeds"]):
        need_stream(name, f"$.feeds[{i}]")
    for i, name in enumerate(data["products"]):
        need_stream(name, f"$.products[{i}]")
    for unit, u in data["units"].items():
        where = _child("$.units", unit)
        for side in ("inlets", "outlets"):
            for i, name in enumerate(u[side]):
                need_stream(name, f"{where}.{side}[{i}]")
        produced.update(u["outlets"])
        for c in u["generation"]:
            if c not in components:
                issues.append(SchemaIssue(f"{where}.generation", f"component {c!r} is not in $.components"))
    for name, s in streams.items():
        where = _child("$.streams", name)
        if name not in data["feeds"] and name not in produced:
            issues.append(SchemaIssue(where, "stream is neither a feed nor the outlet of a unit"))
        for c in s["flows"]:
            if c not in components:
                issues.append(SchemaIssue(f"{where}.flows", f"component {c!r} is not in $.components"))
    if set(data["overall_balance"]) != components:
        issues.append(SchemaIssue("$.overall_balance", f"must have one entry per component {data['components']}"))

    history = data["history"]
    if len(history) != data["iterations"]:
        issues.append(SchemaIssue("$.history", f"has {len(history)} entries for {data['iterations']} iterations"))
    if history[-1] != data["residual"]:
        issues.append(SchemaIssue("$.residual", f"must equal the last history entry {history[-1]!r}"))
    if data["residual"] > data["tol"]:
        issues.append(SchemaIssue("$.residual", f"{data['residual']!r} is above tol {data['tol']!r}"))
    return issues


def dumps(data: Any) -> str:
    """JSON text of a result or schema: two-space indent, no NaN or infinity, a final newline."""
    return json.dumps(data, indent=2, allow_nan=False) + "\n"


def _read_json(path: str) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _report(issues: Sequence[SchemaIssue], what: str) -> int:
    print(f"{what}: {len(issues)} issue(s)", file=sys.stderr)
    for issue in issues:
        print(f"  {issue}", file=sys.stderr)
    return 1


def _solve(spec_path: str, output: str | None) -> int:
    try:
        spec = _read_json(spec_path)
    except (OSError, ValueError) as exc:
        print(f"cannot read {spec_path}: {exc}", file=sys.stderr)
        return 1
    issues = validate_arguments("solve_flowsheet", spec)
    if issues:
        return _report(issues, f"{spec_path} is not a valid flowsheet spec")
    try:
        result = solve_flowsheet(spec).to_dict()
    except ConvergenceError as exc:
        print(f"{spec_path} did not converge: {exc}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"{spec_path} cannot be solved: {exc}", file=sys.stderr)
        return 1
    issues = check_result(result)
    if issues:  # a bug in the library, not in the spec
        return _report(issues, "the result does not match RESULT_SCHEMA")
    text = dumps(result)
    if output is None:
        sys.stdout.write(text)
    else:
        try:
            Path(output).write_text(text, encoding="utf-8")
        except OSError as exc:
            print(f"cannot write {output}: {exc}", file=sys.stderr)
            return 1
        print(f"{output}: {result['iterations']} passes, residual {result['residual']:.3e}", file=sys.stderr)
    return 0


def _check(path: str) -> int:
    try:
        data = _read_json(path)
    except (OSError, ValueError) as exc:
        print(f"cannot read {path}: {exc}", file=sys.stderr)
        return 1
    issues = check_result(data)
    if issues:
        return _report(issues, f"{path} does not match RESULT_SCHEMA")
    print(f"{path}: valid")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python3 -m process_sim_lab.flowsheet_json", description="Solve, check or describe flowsheet results."
    )
    sub = parser.add_subparsers(dest="command", required=True)
    solve = sub.add_parser("solve", help="solve a flowsheet spec and write its result as JSON")
    solve.add_argument("spec", help="flowsheet spec, a JSON file")
    solve.add_argument("-o", "--output", help="result file (default: stdout)")
    check = sub.add_parser("check", help="validate a result file against RESULT_SCHEMA")
    check.add_argument("result", help="result, a JSON file")
    sub.add_parser("schema", help="print RESULT_SCHEMA")
    args = parser.parse_args(argv)
    if args.command == "solve":
        return _solve(args.spec, args.output)
    if args.command == "check":
        return _check(args.result)
    sys.stdout.write(dumps(RESULT_SCHEMA))
    return 0


if __name__ == "__main__":
    sys.exit(main())
