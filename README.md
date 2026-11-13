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

## Run the tests

Python 3.12, no third-party packages.

```bash
python3 -m pip install -e .
python3 -m unittest discover -v -s tests
```

## License

MIT (see [`LICENSE`](LICENSE)).
