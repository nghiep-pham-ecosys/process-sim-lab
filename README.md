# process-sim-lab

A small lab for chemical process and equipment simulation, built step by step with agentic AI in mind.

- **Correct engineering first:** every model states its equations, assumptions and source, and is tested against a
  known answer.
- **Towards design tools:** sized equipment will be exported as plain parametric JSON that a CAD script can read.
- **Agent-ready:** every operation will have a JSON schema, so an LLM agent can build and run a flowsheet through tool
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

## Run the tests

Python 3.12, no third-party packages.

```bash
python3 -m pip install -e .
python3 -m unittest discover -v -s tests -p 'test_*.py'
```

## License

MIT (see [`LICENSE`](LICENSE)).
