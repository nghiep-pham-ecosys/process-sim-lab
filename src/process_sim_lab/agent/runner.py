"""Run one tool call: check its arguments against the tool's schema, call the operation, return plain JSON.

``run_tool(name, arguments)`` never raises for a bad call. It returns one of two shapes, both JSON-safe (no NaN or
infinity, so ``json.dumps(..., allow_nan=False)`` works):

    success   {"ok": true,  "tool": name, "result": {...}}
    failure   {"ok": false, "tool": name, "error": {"type": ..., "message": ..., ...}}

Error types:

    unknown_tool        no tool has that name; "known_tools" lists the names
    invalid_input       the arguments do not match the schema (or are not valid JSON text); "issues" lists
                        {"path", "message"} for each problem, for example {"path": "$.volume", ...}
    model_error         the arguments match the schema but the model rejects them, for example a temperature cross
                        in a heat exchanger or a temperature outside an Antoine range (a ValueError of the library)
    convergence_error   a flowsheet's recycle loop did not converge; "iterations" and "residual" (null when it is
                        not finite) are given

Any other exception is a bug in the library and is raised, not hidden in an error result.

Results use SI units (mol/s, K, Pa, m2, s, W), like the library.
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable, Mapping
from typing import Any

from process_sim_lab.agent.schemas import TOOL_SCHEMAS, validate_arguments
from process_sim_lab.antoine import saturation_temperature, vapour_pressure
from process_sim_lab.flowsheet import ConvergenceError, solve_flowsheet
from process_sim_lab.streams import Stream
from process_sim_lab.units import (
    counter_current_area,
    isothermal_cstr_first_order,
    isothermal_flash,
    isothermal_pfr_first_order,
    mix_streams,
    split_stream,
)

UNKNOWN_TOOL = "unknown_tool"
INVALID_INPUT = "invalid_input"
MODEL_ERROR = "model_error"
CONVERGENCE_ERROR = "convergence_error"


def _stream_in(obj: Mapping[str, Any]) -> Stream:
    state = {k: obj[k] for k in ("temperature", "pressure") if k in obj}
    return Stream(flows=dict(obj["flows"]), **state)


def _stream_out(stream: Stream) -> dict[str, Any]:
    return {"flows": dict(stream.flows), "temperature": stream.temperature, "pressure": stream.pressure}


def _reactor(solve: Callable[..., Any]) -> Callable[[Mapping[str, Any]], dict[str, Any]]:
    def run(a: Mapping[str, Any]) -> dict[str, Any]:
        r = solve(
            _stream_in(a["feed"]),
            reactant=a["reactant"],
            product=a["product"],
            rate_constant=a["rate_constant"],
            volume=a["volume"],
            volumetric_flow=a["volumetric_flow"],
        )
        return {
            "outlet": _stream_out(r.outlet),
            "conversion": r.conversion,
            "space_time": r.space_time,
            "damkohler": r.damkohler,
        }

    return run


def _mixer(a: Mapping[str, Any]) -> dict[str, Any]:
    outlet = mix_streams([_stream_in(s) for s in a["inlets"]], temperature=a.get("temperature"))
    return {"outlet": _stream_out(outlet)}


def _splitter(a: Mapping[str, Any]) -> dict[str, Any]:
    return {"outlets": [_stream_out(s) for s in split_stream(_stream_in(a["feed"]), a["fractions"])]}


def _flash_drum(a: Mapping[str, Any]) -> dict[str, Any]:
    options = {k: a[k] for k in ("tol", "max_iter") if k in a}
    r = isothermal_flash(_stream_in(a["feed"]), k_values=dict(a["k_values"]), **options)
    return {
        "vapour": _stream_out(r.vapour),
        "liquid": _stream_out(r.liquid),
        "vapour_fraction": r.vapour_fraction,
        "x": r.x,
        "y": r.y,
        "phase": r.phase,
        "iterations": r.iterations,
    }


def _heat_exchanger_area(a: Mapping[str, Any]) -> dict[str, Any]:
    r = counter_current_area(
        duty=a["duty"],
        overall_u=a["overall_u"],
        hot_in=a["hot_in"],
        hot_out=a["hot_out"],
        cold_in=a["cold_in"],
        cold_out=a["cold_out"],
    )
    return {"area": r.area, "lmtd": r.lmtd, "delta_t1": r.delta_t1, "delta_t2": r.delta_t2}


def _antoine_vapour_pressure(a: Mapping[str, Any]) -> dict[str, Any]:
    p = vapour_pressure(a["component"], a["temperature"])
    return {"component": a["component"], "temperature": a["temperature"], "vapour_pressure": p}


def _antoine_saturation_temperature(a: Mapping[str, Any]) -> dict[str, Any]:
    t = saturation_temperature(a["component"], a["pressure"])
    return {"component": a["component"], "pressure": a["pressure"], "saturation_temperature": t}


def _solve_flowsheet(a: Mapping[str, Any]) -> dict[str, Any]:
    r = solve_flowsheet(a)
    return {**r.to_dict(), "history": list(r.history), "overall_balance": r.overall_balance()}


OPERATIONS: dict[str, Callable[[Mapping[str, Any]], dict[str, Any]]] = {
    "cstr": _reactor(isothermal_cstr_first_order),
    "pfr": _reactor(isothermal_pfr_first_order),
    "mixer": _mixer,
    "splitter": _splitter,
    "flash_drum": _flash_drum,
    "heat_exchanger_area": _heat_exchanger_area,
    "antoine_vapour_pressure": _antoine_vapour_pressure,
    "antoine_saturation_temperature": _antoine_saturation_temperature,
    "solve_flowsheet": _solve_flowsheet,
}


def _finite_or_none(value: float) -> float | None:
    return value if math.isfinite(value) else None


def _error(tool: Any, kind: str, message: str, **details: Any) -> dict[str, Any]:
    return {"ok": False, "tool": tool if isinstance(tool, str) else repr(tool),
            "error": {"type": kind, "message": message, **details}}


def run_tool(name: Any, arguments: Any) -> dict[str, Any]:
    """Run one tool call.

    Args:
        name: a key of ``TOOL_SCHEMAS`` (for example ``"cstr"``).
        arguments: the call's arguments as a dict, or as JSON text (some tool-calling APIs pass a string).

    Returns:
        ``{"ok": True, "tool", "result"}`` or ``{"ok": False, "tool", "error"}``; the error types are in the module
        docstring.
    """
    if not isinstance(name, str) or name not in TOOL_SCHEMAS:
        return _error(name, UNKNOWN_TOOL, f"unknown tool {name!r}", known_tools=list(TOOL_SCHEMAS))

    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except json.JSONDecodeError as exc:
            issue = {"path": "$", "message": f"not valid JSON: {exc}"}
            return _error(name, INVALID_INPUT, f"$: not valid JSON: {exc}", issues=[issue])

    issues = validate_arguments(name, arguments)
    if issues:
        return _error(name, INVALID_INPUT, "; ".join(str(i) for i in issues), issues=[i.to_dict() for i in issues])

    try:
        result = OPERATIONS[name](arguments)
    except ConvergenceError as exc:
        return _error(name, CONVERGENCE_ERROR, str(exc), iterations=exc.iterations,
                      residual=_finite_or_none(exc.residual))
    except ValueError as exc:
        return _error(name, MODEL_ERROR, str(exc))
    return {"ok": True, "tool": name, "result": result}
