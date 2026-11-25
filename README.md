# process-sim-lab

A small lab for chemical process and equipment simulation, built step by step with agentic AI in mind.

- **Correct engineering first:** every model states its equations, assumptions and source, and is tested against a
  known answer.
- **Towards design tools:** sized equipment will be exported as plain parametric JSON that a CAD script can read.
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

The hand derivation, the direct-substitution and Wegstein runs side by side, and the schema check are in
[`docs/flowsheet-worked-example.md`](docs/flowsheet-worked-example.md).

## Agent layer

Week 4: every operation is a tool with a JSON schema, so an agent can call the library through tool calls.

| Tool | Operation |
|---|---|
| `cstr`, `pfr` | isothermal first-order reactor A → B |
| `mixer`, `splitter` | mix streams; split one stream by fraction |
| `flash_drum` | isothermal flash with given K-values (Rachford–Rice) |
| `heat_exchanger_area` | counter-current exchanger area from the duty and the LMTD |
| `antoine_vapour_pressure`, `antoine_saturation_temperature` | pure-component Antoine equation (NIST constants) |
| `solve_flowsheet` | a flowsheet in the week-3 JSON form, recycle included |

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
run_tool("heat_exchanger_area", {..., "overall_u": -500.0})
# {"ok": False, "tool": "heat_exchanger_area",
#  "error": {"type": "invalid_input", "message": "$.overall_u: must be > 0, got -500.0",
#            "issues": [{"path": "$.overall_u", "message": "must be > 0, got -500.0"}]}}
```

Ten evaluation cases in [`evals/cases/`](evals/cases/) are fixed tool calls with expected results. The values and
tolerances come from the hand-checked unit tests and the week-3 flowsheet; each case names its source. No LLM is
called:

```bash
python3 -m process_sim_lab.agent.evaluate      # PASS/FAIL per case, then "10/10 cases passed"; exit code 1 on a failure
```

The default case folder is the repository's `evals/cases`, which an editable install (`pip install -e .`) finds. Pass
`--cases DIR` otherwise.

## Run the tests

Python 3.12, no third-party packages.

```bash
python3 -m pip install -e .
python3 -m unittest discover -v -s tests -p 'test_*.py'
```

## License

MIT (see [`LICENSE`](LICENSE)).
