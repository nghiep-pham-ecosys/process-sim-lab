"""Local web demo of the week-3 flowsheet: change the spec values, solve, and read the streams, sizing and convergence.

The flowsheet is the one in ``examples/reactor_flash_recycle.json`` (a CSTR, a flash drum and a purged vapour recycle,
solved by tearing the recycle). The demo exposes its main numbers as inputs, builds the JSON spec from them, calls
``process_sim_lab.flowsheet.solve_flowsheet`` and shows three tables: every stream, the sizing of every unit, and the
convergence of the tear loop (passes, residual history, overall mole balance).

Two layers:

    week3_spec(...)    the flowsheet spec as a dict, with the example's values as defaults       (standard library)
    solve_week3(...)   solve that spec; returns plain tables and never raises for a bad input   (standard library)
    build_app()        the Gradio interface around solve_week3                               (needs the extra)

Only ``build_app`` and ``main`` import Gradio (Apache-2.0 licence), the optional extra ``demo``:

    python3 -m pip install -e '.[demo]'
    python3 -m process_sim_lab.demo          # serves on http://127.0.0.1:7860 only; no share link, no telemetry

The demo runs on this machine only: it binds to 127.0.0.1, never asks Gradio for a public share link and turns
Gradio's usage analytics off.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from process_sim_lab.flowsheet import METHODS, SIZING_FIELDS, ConvergenceError, solve_flowsheet

if TYPE_CHECKING:
    import gradio

HOST = "127.0.0.1"
DEFAULT_PORT = 7860
INSTALL_HINT = "the demo needs Gradio: python3 -m pip install -e '.[demo]'"

# The values of examples/reactor_flash_recycle.json (tests/test_demo.py checks that week3_spec() equals that file).
DEFAULTS: dict[str, Any] = {
    "feed_a": 5.6,  # mol/s
    "feed_i": 2.4,  # mol/s
    "rate_constant": 0.023,  # 1/s
    "volume": 2.0,  # m3
    "volumetric_flow": 0.02,  # m3/s
    "k_a": 5.0,  # K-value of A in the drum
    "k_i": 1.0,
    "k_b": 1.0 / 3.0,
    "liquid_density": 800.0,  # kg/m3
    "souders_brown_k": 0.07,  # m/s
    "height_to_diameter": 4.0,
    "purge_fraction": 0.2,  # share of the vapour sent to purge
    "method": "wegstein",
    "max_iter": 100,
}

# Unit of each sizing field (flowsheet.SIZING_FIELDS), for the sizing table.
SIZING_UNITS: dict[str, str] = {
    "volume": "m3",
    "space_time": "s",
    "diameter": "m",
    "height": "m",
    "height_to_diameter": "-",
    "vapour_density": "kg/m3",
    "vapour_volumetric_flow": "m3/s",
    "max_vapour_velocity": "m/s",
    "duty": "W",
    "area": "m2",
    "lmtd": "K",
    "minimum_stages": "-",
    "stages": "-",
    "minimum_reflux": "-",
    "reflux_ratio": "-",
}

SIZING_HEADERS = ["unit", "type", "field", "value", "SI unit"]
TOL = 1e-10  # the example's tear tolerance on the scaled residual


def week3_spec(
    *,
    feed_a: float = DEFAULTS["feed_a"],
    feed_i: float = DEFAULTS["feed_i"],
    rate_constant: float = DEFAULTS["rate_constant"],
    volume: float = DEFAULTS["volume"],
    volumetric_flow: float = DEFAULTS["volumetric_flow"],
    k_a: float = DEFAULTS["k_a"],
    k_i: float = DEFAULTS["k_i"],
    k_b: float = DEFAULTS["k_b"],
    liquid_density: float = DEFAULTS["liquid_density"],
    souders_brown_k: float = DEFAULTS["souders_brown_k"],
    height_to_diameter: float = DEFAULTS["height_to_diameter"],
    purge_fraction: float = DEFAULTS["purge_fraction"],
    method: str = DEFAULTS["method"],
    max_iter: int = DEFAULTS["max_iter"],
) -> dict[str, Any]:
    """The week-3 flowsheet in its JSON form (``process_sim_lab.flowsheet``), with the given values.

    Args:
        feed_a, feed_i: fresh feed of A and of the inert I, mol/s (at 330 K and 2 bar).
        rate_constant: first-order rate constant of A -> B in the CSTR, 1/s.
        volume, volumetric_flow: reactor volume (m3) and volumetric flow (m3/s).
        k_a, k_i, k_b: K-values of A, I and B in the flash drum.
        liquid_density, souders_brown_k, height_to_diameter: drum sizing data (kg/m3, m/s, -).
        purge_fraction: share of the drum vapour sent to purge; the rest is recycled.
        method: tear update rule, "direct" or "wegstein".
        max_iter: most passes allowed.

    The values are not checked here: ``solve_flowsheet`` and the unit models check them.
    """
    return {
        "name": "reactor-flash-recycle",
        "feeds": {"feed": {"flows": {"A": feed_a, "I": feed_i}, "temperature": 330.0, "pressure": 200000.0}},
        "units": [
            {"name": "mixer", "type": "mixer", "inlets": ["feed", "recycle"], "outlets": ["reactor-in"]},
            {
                "name": "reactor",
                "type": "cstr",
                "inlets": ["reactor-in"],
                "outlets": ["reactor-out"],
                "params": {
                    "reactant": "A",
                    "product": "B",
                    "rate_constant": rate_constant,
                    "volume": volume,
                    "volumetric_flow": volumetric_flow,
                },
            },
            {
                "name": "drum",
                "type": "flash",
                "inlets": ["reactor-out"],
                "outlets": ["vapour", "liquid"],
                "params": {
                    "k_values": {"A": k_a, "I": k_i, "B": k_b},
                    "molar_masses": {"A": 0.06, "I": 0.028, "B": 0.06},
                    "liquid_density": liquid_density,
                    "souders_brown_k": souders_brown_k,
                    "height_to_diameter": height_to_diameter,
                },
            },
            {
                "name": "purge-split",
                "type": "splitter",
                "inlets": ["vapour"],
                "outlets": ["purge", "recycle"],
                "params": {"fractions": [purge_fraction, 1.0 - purge_fraction]},
            },
        ],
        "tear": {"streams": ["recycle"], "method": method, "tol": TOL, "max_iter": max_iter},
    }


def solve_week3(**values: Any) -> dict[str, Any]:
    """Solve the week-3 flowsheet with the given values (``week3_spec`` keywords) and return plain tables.

    Returns:
        ``{"ok": True, "streams": {"headers", "rows"}, "sizing": {"headers", "rows"}, "convergence": {...},
        "result": FlowsheetResult.to_dict()}`` on success, or ``{"ok": False, "error": message}`` when the spec is
        rejected, a unit fails or the loop does not converge. Flows are in mol/s, temperatures in K, pressures in Pa;
        each sizing row names its SI unit.
    """
    unknown = sorted(values.keys() - DEFAULTS.keys())
    if unknown:
        return {"ok": False, "error": f"unknown inputs {unknown}"}
    missing = sorted(k for k, v in values.items() if v is None)
    if missing:
        return {"ok": False, "error": f"no value for {missing}"}
    if values.get("method", DEFAULTS["method"]) not in METHODS:
        return {"ok": False, "error": f"method must be one of {list(METHODS)}, got {values['method']!r}"}
    try:
        if "max_iter" in values:
            max_iter = float(values["max_iter"])
            if not max_iter.is_integer() or max_iter < 1:
                raise ValueError(f"max_iter must be a whole number >= 1, got {values['max_iter']!r}")
            values["max_iter"] = int(max_iter)
        result = solve_flowsheet(week3_spec(**values))
    except (ConvergenceError, ValueError, TypeError) as exc:
        return {"ok": False, "error": str(exc)}

    data = result.to_dict()
    components = data["components"]
    stream_rows = []
    for name, s in data["streams"].items():
        flows = [s["flows"].get(c, 0.0) for c in components]
        stream_rows.append([name, *flows, math.fsum(flows), s["temperature"], s["pressure"]])
    sizing_rows = [
        [name, u["type"], field, u["sizing"][field], SIZING_UNITS[field]]
        for name, u in data["units"].items()
        for field in SIZING_FIELDS[u["type"]]
        if field in u["sizing"]
    ]
    return {
        "ok": True,
        "streams": {
            "headers": ["stream", *(f"{c} (mol/s)" for c in components), "total (mol/s)", "T (K)", "P (Pa)"],
            "rows": stream_rows,
        },
        "sizing": {"headers": SIZING_HEADERS, "rows": sizing_rows},
        "convergence": {
            "method": data["method"],
            "iterations": data["iterations"],
            "residual": data["residual"],
            "tol": data["tol"],
            "history": data["history"],
            "overall_balance": data["overall_balance"],
        },
        "result": data,
    }


def convergence_markdown(outcome: dict[str, Any]) -> str:
    """The convergence block (or the error) of a ``solve_week3`` outcome as Markdown."""
    if not outcome["ok"]:
        return f"**Not solved.** {outcome['error']}"
    c = outcome["convergence"]
    lines = [
        f"**Converged** with `{c['method']}` in {c['iterations']} passes: scaled residual {c['residual']:.3e} "
        f"(tol {c['tol']:.0e}).",
        "",
        "| pass | scaled residual |",
        "|---|---|",
        *(f"| {i} | {r:.3e} |" for i, r in enumerate(c["history"], start=1)),
        "",
        "Overall mole balance, feeds + generation - products (mol/s): "
        + ", ".join(f"{k} {v:.1e}" for k, v in c["overall_balance"].items()),
    ]
    return "\n".join(lines)


INPUT_ORDER = tuple(DEFAULTS)


def demo_outputs(*args: Any) -> tuple[list[list[Any]], list[list[Any]], str, str]:
    """The four outputs of the interface for inputs given in ``INPUT_ORDER``: streams, sizing, convergence, JSON."""
    outcome = solve_week3(**dict(zip(INPUT_ORDER, args, strict=True)))
    if not outcome["ok"]:
        return [], [], convergence_markdown(outcome), json.dumps({"error": outcome["error"]}, indent=2)
    return (
        outcome["streams"]["rows"],
        outcome["sizing"]["rows"],
        convergence_markdown(outcome),
        json.dumps(outcome["result"], indent=2),
    )


def build_app() -> gradio.Blocks:
    """The Gradio interface. Imports Gradio, so it needs the optional extra ``demo``."""
    import gradio as gr

    d = DEFAULTS
    headers = solve_week3()["streams"]["headers"]
    with gr.Blocks(title="process-sim-lab: week-3 flowsheet", analytics_enabled=False) as app:
        gr.Markdown(
            "# Reactor, flash drum and purged recycle\n"
            "Change the spec of the week-3 flowsheet and press **Solve**. Every number is in SI units. "
            "The solver is `process_sim_lab.flowsheet.solve_flowsheet`; the hand derivation of the default case is "
            "in `docs/flowsheet-worked-example.md`."
        )
        with gr.Row():
            with gr.Column():
                gr.Markdown("**Feed** (330 K, 2 bar)")
                feed_a = gr.Number(d["feed_a"], label="feed A (mol/s)", minimum=0)
                feed_i = gr.Number(d["feed_i"], label="feed I, inert (mol/s)", minimum=0)
                gr.Markdown("**CSTR**, A → B, first order")
                rate_constant = gr.Number(d["rate_constant"], label="rate constant k (1/s)", minimum=0)
                volume = gr.Number(d["volume"], label="volume V (m3)", minimum=0)
                volumetric_flow = gr.Number(d["volumetric_flow"], label="volumetric flow Q (m3/s)", minimum=0)
            with gr.Column():
                gr.Markdown("**Flash drum**, K-values and sizing data")
                k_a = gr.Number(d["k_a"], label="K of A", minimum=0)
                k_i = gr.Number(d["k_i"], label="K of I", minimum=0)
                k_b = gr.Number(d["k_b"], label="K of B", minimum=0)
                liquid_density = gr.Number(d["liquid_density"], label="liquid density (kg/m3)", minimum=0)
                souders_brown_k = gr.Number(d["souders_brown_k"], label="Souders-Brown K (m/s)", minimum=0)
                height_to_diameter = gr.Number(d["height_to_diameter"], label="height / diameter", minimum=0)
            with gr.Column():
                gr.Markdown("**Purge and recycle loop**")
                purge_fraction = gr.Slider(0.01, 0.99, value=d["purge_fraction"], step=0.01, label="purge fraction")
                method = gr.Radio(list(METHODS), value=d["method"], label="tear update rule")
                max_iter = gr.Number(d["max_iter"], label="most passes", precision=0, minimum=1)
                solve = gr.Button("Solve", variant="primary")
        streams = gr.Dataframe(headers=headers, label="Streams", interactive=False)
        sizing = gr.Dataframe(headers=SIZING_HEADERS, label="Sizing", interactive=False)
        convergence = gr.Markdown()
        with gr.Accordion("Result JSON (RESULT_SCHEMA in process_sim_lab.flowsheet_json)", open=False):
            result_json = gr.Code(language="json")
        inputs = [
            feed_a, feed_i, rate_constant, volume, volumetric_flow, k_a, k_i, k_b,
            liquid_density, souders_brown_k, height_to_diameter, purge_fraction, method, max_iter,
        ]  # fmt: skip
        outputs = [streams, sizing, convergence, result_json]
        solve.click(demo_outputs, inputs=inputs, outputs=outputs)
        app.load(demo_outputs, inputs=inputs, outputs=outputs)
    return app


def main(argv: Sequence[str] | None = None) -> int:
    """Serve the demo on 127.0.0.1 (``python3 -m process_sim_lab.demo [--port N]``)."""
    parser = argparse.ArgumentParser(
        prog="python3 -m process_sim_lab.demo",
        description="Local web demo of the week-3 flowsheet (Gradio). Serves on 127.0.0.1 only.",
    )
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"local port (default {DEFAULT_PORT})")
    args = parser.parse_args(argv)
    os.environ["GRADIO_ANALYTICS_ENABLED"] = "False"  # set before Gradio is imported
    try:
        app = build_app()
    except ImportError:
        print(INSTALL_HINT, file=sys.stderr)
        return 2
    app.launch(server_name=HOST, server_port=args.port, share=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
