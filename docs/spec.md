# process-sim-lab: spec

Version 0.1 (2026-11-13). This file is the contract for the repo. Change it in a pull request.

## 1. Goal

Build a small, readable library for chemical process and equipment simulation, and an agent interface on top of it.
A person or an LLM agent describes a process, the library solves the mass and energy balances, sizes the equipment,
and writes the results in a form that design tools can read.

Three things this lab wants to show:

1. **Correct engineering.** Every model has its equations written down, a source, and a test against a known answer.
2. **A path towards design tools (CAD/CAM).** Sized equipment is exported as plain parametric data (JSON), so a
   CAD script can draw it later. No CAD dependency in the core library.
3. **Agent-ready.** Each operation is a function with typed inputs and outputs and a JSON schema, so an agent can
   build and run a flowsheet through tool calls, and its answers can be checked against fixed cases.

## 2. Scope

In scope:

- Steady-state unit operations: reactors (CSTR, PFR), flash drum, mixer, splitter, heat exchanger.
- Simple physical property models with cited data (Antoine vapour pressure, ideal mixtures first).
- Sequential-modular flowsheet solving, including one recycle loop.
- Equipment sizing outputs: vessel volume and dimensions, heat-exchanger area.
- An agent tool layer: schemas, a runner, and evaluation cases with expected results.

Out of scope for the first 4 weeks:

- Dynamic simulation, control loops, non-ideal thermodynamics (activity or equation-of-state models).
- A GUI, a hosted service, or drawing CAD geometry.
- Any paid API. Agent experiments run locally inside an existing subscription.

## 3. Principles

- Python 3.12. Core library: standard library only. `numpy`/`scipy` may come later, one PR each, with a reason.
- SI units inside the library. Conversions only at the edges.
- Each model: a docstring with the equations, the assumptions and a source; a test against an analytic or textbook
  value with a stated tolerance.
- Small pull requests. One unit operation or one feature per PR.

## 4. Roadmap (4 weeks)

| Week | Deliverable | Done when |
|---|---|---|
| 1 | Repo, spec, package skeleton, CI; `Stream` and an isothermal CSTR (first-order A → B) | CI green; CSTR matches the analytic conversion X = kτ / (1 + kτ) |
| 2 | Unit library: PFR, mixer, splitter, flash drum (Rachford–Rice), heat exchanger (LMTD); Antoine data with sources | each unit has a test against a hand-checked case |
| 3 | Flowsheet: connect units, solve in sequence, one recycle loop (successive substitution, then Wegstein); sizing outputs exported as JSON | a reactor–separator–recycle example converges and its JSON validates against a schema |
| 4 | Agent layer: JSON schemas for every operation, a tool runner, 10 evaluation cases with expected results; a worked example in the README | the runner passes all 10 cases; an agent session that builds the week-3 flowsheet is recorded in `docs/` |

## 5. Layout

```
src/process_sim_lab/      library
  streams.py              Stream: molar flows by component, temperature, pressure
  units/                  one module per unit operation
tests/                    unittest, one file per module
docs/spec.md              this file
```

## 6. How work is checked

- `python -m unittest discover -s tests` passes locally and in CI.
- CI jobs `ci-result` and `pr-title` are required on `main`.
- A model without a source and a test does not merge.
