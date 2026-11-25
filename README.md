# process-sim-lab

A small lab for chemical process and equipment simulation, built step by step with agentic AI in mind.

- **Correct engineering first:** every model states its equations, assumptions and source, and is tested against a
  known answer.
- **Towards design tools:** sized equipment is exported as plain parametric JSON (the `sizing` of each unit in a
  solved flowsheet) that a CAD script can read.
- **Agent-ready:** every operation has a JSON schema, so an LLM agent can build and run a flowsheet through tool
  calls and be checked against fixed cases.

The plan and the 4-week roadmap: [`docs/spec.md`](docs/spec.md).

## Status

Week 1: package skeleton, `Stream`, and an isothermal CSTR for a first-order reaction A → B.

```python
from process_sim_lab import Stream
from process_sim_lab.units import isothermal_cstr_first_order

feed = Stream(flows={"A": 10.0, "W": 50.0}, temperature=330.0)        # mol/s, K
r = isothermal_cstr_first_order(feed, reactant="A", product="B",
                                rate_constant=0.01, volume=2.0, volumetric_flow=0.004)
print(r.conversion)   # 0.8333... = k*tau / (1 + k*tau), tau = 500 s
```

Week 2: unit library (PFR, mixer, splitter, isothermal flash drum, LMTD heat exchanger) and Antoine vapour pressure.
Each example below is run by `tests/test_readme.py`, and its `assert` is the hand-check from the unit's own test.

PFR, same feed and kinetics form as the CSTR. With k·τ = ln 2 the conversion is 1 − exp(−ln 2) = 1/2
(`tests/test_pfr.py`):

```python
import math
from process_sim_lab import Stream
from process_sim_lab.units import isothermal_pfr_first_order

feed = Stream(flows={"A": 10.0, "W": 50.0}, temperature=330.0)        # mol/s, K
r = isothermal_pfr_first_order(feed, reactant="A", product="B",
                               rate_constant=math.log(2) / 100, volume=1.0, volumetric_flow=0.01)
print(r.space_time, r.conversion)   # 100.0 s, 0.5
assert abs(r.conversion - 0.5) < 1e-12
```

Mixer and splitter: the mixer adds component flows and takes the lowest inlet pressure; the splitter scales every
flow by the fraction (`tests/test_mixer.py`, `tests/test_splitter.py`):

```python
from process_sim_lab import Stream
from process_sim_lab.units import mix_streams, split_stream

s1 = Stream(flows={"A": 2.0, "B": 1.0}, temperature=300.0, pressure=3e5)
s2 = Stream(flows={"A": 3.0, "C": 4.0}, temperature=300.0, pressure=2e5)
mixed = mix_streams([s1, s2])
print(mixed.flows, mixed.pressure)   # {'A': 5.0, 'B': 1.0, 'C': 4.0} 200000.0
assert mixed.flows == {"A": 5.0, "B": 1.0, "C": 4.0} and mixed.pressure == 2e5

purge, recycle = split_stream(Stream(flows={"A": 6.0, "B": 4.0}), [0.25, 0.75])
print(purge.flows, recycle.flows)    # {'A': 1.5, 'B': 1.0} {'A': 4.5, 'B': 3.0}
assert purge.flows == {"A": 1.5, "B": 1.0} and recycle.flows == {"A": 4.5, "B": 3.0}
```

Isothermal flash drum with given K-values. For z = (0.5, 0.5) and K = (2, 0.5) the Rachford–Rice root is
ψ = 0.5, x = (1/3, 2/3), y = (2/3, 1/3) (`tests/test_flash.py`):

```python
from process_sim_lab import Stream
from process_sim_lab.units import isothermal_flash

feed = Stream(flows={"A": 5.0, "B": 5.0}, temperature=350.0, pressure=1.5e5)
r = isothermal_flash(feed, k_values={"A": 2.0, "B": 0.5})
print(r.vapour_fraction, r.x["A"], r.y["A"])   # 0.5, 0.3333..., 0.6666...
assert abs(r.vapour_fraction - 0.5) < 1e-9
assert abs(r.x["A"] - 1 / 3) < 1e-9 and abs(r.y["A"] - 2 / 3) < 1e-9
```

Heat exchanger: log-mean temperature difference and the counter-current area. Terminal differences 80 K and 60 K
give LMTD = 20 / ln(4/3) = 69.5212 K, and A = 5e5 / (500 · 69.5212) = 14.3841 m² (`tests/test_heat_exchanger.py`):

```python
from process_sim_lab.units import counter_current_area, log_mean_temperature_difference

print(log_mean_temperature_difference(80.0, 60.0))     # 69.5211899...
r = counter_current_area(duty=5e5, overall_u=500.0,                 # W, W/(m2 K)
                         hot_in=423.15, hot_out=363.15, cold_in=303.15, cold_out=343.15)   # K
print(r.area)                                          # 14.3841036... m2
assert abs(log_mean_temperature_difference(80.0, 60.0) - 69.5211899356) < 1e-6
assert abs(r.area - 14.3841036) < 1e-6
```

Antoine vapour pressure (NIST constants). Benzene at 300 K: log10(P/bar) = 4.01814 − 1203.835 / (300 − 53.226),
so P = 13 799 Pa; its normal boiling point is 353.3 K ± 0.1 K (NIST WebBook) (`tests/test_antoine.py`):

```python
from process_sim_lab.antoine import saturation_temperature, vapour_pressure

print(vapour_pressure("benzene", 300.0))               # 13799.09... Pa
print(saturation_temperature("benzene", 101_325.0))    # 353.25... K
assert abs(vapour_pressure("benzene", 300.0) - 13_799.0) < 1.0
assert abs(saturation_temperature("benzene", 101_325.0) - 353.3) < 0.1
```

Week 3: a flowsheet defined in JSON, solved unit by unit, with a recycle loop converged by tearing a stream
(successive substitution or Wegstein). The example in
[`examples/reactor_flash_recycle.json`](examples/reactor_flash_recycle.json) is a CSTR, a flash drum and a purged
vapour recycle:

```python
from process_sim_lab.flowsheet import Flowsheet, solve_flowsheet

r = solve_flowsheet(Flowsheet.load("examples/reactor_flash_recycle.json"))
print(r.iterations, r.residual)          # 3 passes with Wegstein, residual below the stated tol of 1e-10
print(r.streams["recycle"].flows)        # about {'A': 1.0, 'I': 0.6, 'B': 0.4} mol/s
print(r.overall_balance())               # feeds + generation - products, about 0 for every component
```

The JSON format is described in the docstring of
[`src/process_sim_lab/flowsheet.py`](src/process_sim_lab/flowsheet.py). Unknown keys are rejected, a loop with no
tear stream is rejected with the units that form it, and a loop that does not converge raises `ConvergenceError`.
A tear stream without an `initial` guess starts at zero flow. Tearing `recycle` works that way, but a tear upstream
of the flash (`reactor-in` or `reactor-out` in the example) needs an `initial` guess in `tear`, or the first pass
fails because the flash gets an empty feed.

The result is written as one JSON object, and `RESULT_SCHEMA` in
[`src/process_sim_lab/flowsheet_json.py`](src/process_sim_lab/flowsheet_json.py) (JSON Schema draft 2020-12)
describes it. The example's output is committed as
[`examples/reactor_flash_recycle.result.json`](examples/reactor_flash_recycle.result.json):

```bash
python3 -m process_sim_lab.flowsheet_json solve examples/reactor_flash_recycle.json -o result.json
python3 -m process_sim_lab.flowsheet_json check result.json      # result.json: valid
python3 -m process_sim_lab.flowsheet_json schema                 # prints RESULT_SCHEMA
```

Each unit in the result carries a `sizing` object, the equipment size in SI units, computed once from the converged
streams: reactor volume and space time; vertical flash drum diameter, height and volume (Souders–Brown, when the
flash has the four sizing params `molar_masses`, `liquid_density`, `souders_brown_k`, `height_to_diameter`); and for
the `heat_exchanger` and `shortcut_column` unit types, the exchanger duty, area and LMTD, and the column stages and
reflux. Mixers and splitters have nothing to size (`{}`). In the example, the drum comes out at D = 0.206 m and
H = 0.823 m.

The hand derivation, the direct-substitution and Wegstein runs side by side, the sizing and the schema check are in
[`docs/flowsheet-worked-example.md`](docs/flowsheet-worked-example.md).

## Agent layer

Week 4: every operation is a tool with a JSON schema, so an agent can call the library through tool calls.

| Tool | Operation |
|---|---|
| `cstr`, `pfr` | isothermal first-order reactor A → B |
| `mixer`, `splitter` | mix streams; split one stream by fraction |
| `flash_drum` | isothermal flash with given K-values (Rachford–Rice) |
| `shortcut_column` | distillation column by Fenske–Underwood–Gilliland: minimum stages, minimum reflux, actual stages |
| `heat_exchanger_area` | counter-current exchanger area from the duty and the LMTD |
| `antoine_vapour_pressure`, `antoine_saturation_temperature` | pure-component Antoine equation (NIST constants) |
| `solve_flowsheet` | a flowsheet in the week-3 JSON form, recycle included; returns the streams and each unit's sizing |

The schemas live in [`src/process_sim_lab/agent/schemas.py`](src/process_sim_lab/agent/schemas.py) (JSON Schema
draft 2020-12, plain dicts, SI units in every description, one example input each). `tool_definitions()` returns
them as `{"name", "description", "input_schema"}`. `run_tool(name, arguments)` checks the arguments against the
schema, calls the operation and returns plain JSON. It never raises for a bad call.

A worked tool call, the hand-checked exchanger of `tests/test_heat_exchanger.py`:

```python
from process_sim_lab.agent.runner import run_tool

run_tool("heat_exchanger_area", {"duty": 5e5, "overall_u": 500.0,               # W, W/(m2 K)
                                 "hot_in": 423.15, "hot_out": 363.15,           # K
                                 "cold_in": 303.15, "cold_out": 343.15})        # K
# {"ok": True, "tool": "heat_exchanger_area",
#  "result": {"area": 14.384103622589043, "lmtd": 69.52118993564416, "delta_t1": 80.0, "delta_t2": 60.0}}
```

A bad call comes back as a structured error. Its type is `unknown_tool`, `invalid_input` (with the path of each bad
field), `model_error` (valid shape, but the model rejects it, such as a temperature cross) or `convergence_error`:

```python
from process_sim_lab.agent.runner import run_tool

bad = run_tool("heat_exchanger_area", {"duty": 5e5, "overall_u": -500.0,
                                       "hot_in": 423.15, "hot_out": 363.15,
                                       "cold_in": 303.15, "cold_out": 343.15})
assert bad["error"]["type"] == "invalid_input"
# {"ok": False, "tool": "heat_exchanger_area",
#  "error": {"type": "invalid_input", "message": "$.overall_u: must be > 0, got -500.0",
#            "issues": [{"path": "$.overall_u", "message": "must be > 0, got -500.0"}]}}
```

Twenty-five evaluation cases in [`evals/cases/`](evals/cases/) are fixed tool calls with expected results. The values
and tolerances come from the hand-checked unit tests, NIST data and a textbook example; each case names its source and
tolerance. No LLM is called:

| Cases | Cover |
|---|---|
| 01–09 | one call per unit tool: reactors, mixer, splitter, flash, exchanger area, Antoine |
| 10, 12–15 | recycle: the week-3 flowsheet by Wegstein and by direct substitution, torn at the reactor outlet; a linear loop with purge 1/5 and 1/10 |
| 11, 16–18 | distillation: the Wankat column (q = 0, R given); a binary column with q = 1 and q = 0 and `reflux_factor`, alone and as a flowsheet unit |
| 10, 15, 18–20 | sizing outputs: reactor, flash drum (every field), column, cooler and heater |
| 21–25 | error paths: `unknown_tool`, `invalid_input`, `model_error` (temperature cross, reflux given twice), `convergence_error` |

```bash
python3 -m process_sim_lab.agent.evaluate      # PASS/FAIL per case, then "25/25 cases passed"; exit code 1 on a failure
```

An error-path case names the error it expects (`"expected_error": "invalid_input"`) and checks fields of the error
instead of the result, so an agent's recovery from a bad call can be graded the same way.

The default case folder is the repository's `evals/cases`, which an editable install (`pip install -e .`) finds. Pass
`--cases DIR` otherwise.

After week 4: a shortcut distillation column (Fenske, Underwood, Gilliland) as the tool `shortcut_column`, checked
against a textbook example (Wankat, Separation Process Engineering, Examples 7-1 and 7-2).

## Use from an MCP client

An MCP server wraps the same runner, so any MCP client (Claude Code, Claude Desktop, another agent) can list and
call every tool above. Each tool's input schema is the schema from `schemas.py`, unchanged. The server needs the
official MCP Python SDK (MIT licence), an optional extra; the library itself stays standard library only:

```bash
python3 -m pip install -e '.[mcp]'
python3 -m process_sim_lab.mcp_server --help      # the server speaks MCP over stdio; a client starts it
```

Claude Code, from the repository root (use the Python of the environment you installed into):

```bash
claude mcp add process-sim-lab -- "$(command -v python3)" -m process_sim_lab.mcp_server
```

Claude Desktop (`claude_desktop_config.json`), or a project `.mcp.json`, with the absolute path of that Python:

```json
{
  "mcpServers": {
    "process-sim-lab": {
      "command": "/absolute/path/to/.venv/bin/python",
      "args": ["-m", "process_sim_lab.mcp_server"]
    }
  }
}
```

The install also adds a console script, `process-sim-lab-mcp`, which can be the `command` instead. A tool call
returns the runner's JSON twice: as `structuredContent` and as one text block. A bad call sets `isError` and carries
the runner's error (`invalid_input`, `model_error`, `convergence_error`), so the model can correct it; an unknown tool
name is a JSON-RPC error (-32602) that lists the known tools. `tests/test_mcp_server.py` connects a client through the
SDK, in process and over stdio, and builds the week-3 flowsheet with `solve_flowsheet`.

## Try it without code

A local web demo solves the week-3 flowsheet from a form: change the feed, the kinetics, the K-values, the drum sizing
data, the purge fraction or the tear update rule, and read the streams, the sizing and the convergence. It needs
Gradio (Apache-2.0), an optional extra, and runs on your machine only (127.0.0.1, no share link, analytics off):

```bash
python3 -m pip install -e '.[demo]'
python3 -m process_sim_lab.demo            # open http://127.0.0.1:7860 ; stop with Ctrl+C
```

`process_sim_lab.demo.solve_week3(...)` is the function behind the form; it needs no Gradio.

## Docs site

One page per unit (equations, assumptions, a runnable example, the flowsheet params and the agent tool, the source),
plus Antoine, the flowsheet, the agent layer and the demo:
[nghiep-pham-ecosys.github.io/process-sim-lab](https://nghiep-pham-ecosys.github.io/process-sim-lab/). It is built
from [`docs/`](docs/) and [`mkdocs.yml`](mkdocs.yml) by `.github/workflows/pages.yml` (`mkdocs build --strict`).
Locally, with the optional extra `docs` (MkDocs, BSD-2-Clause):

```bash
python3 -m pip install -e '.[docs]'
mkdocs serve                               # http://127.0.0.1:8000
```

## Run the tests

Python 3.12, no third-party packages.

```bash
python3 -m pip install -e .
python3 -m unittest discover -v -s tests -p 'test_*.py'
```

The MCP client tests are skipped unless the `mcp` extra is installed (`python3 -m pip install -e '.[mcp]'`); the
Gradio interface tests need the `demo` extra and the strict site build test needs the `docs` extra.

## License

MIT (see [`LICENSE`](LICENSE)).
