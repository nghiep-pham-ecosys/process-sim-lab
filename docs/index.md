# process-sim-lab

A small, readable library for chemical process and equipment simulation, built step by step with agentic AI in mind.

- **Correct engineering first:** every model states its equations, assumptions and source, and is tested against a
  known answer.
- **Towards design tools:** sized equipment is exported as plain parametric JSON (the `sizing` of each unit in a
  solved flowsheet) that a CAD script can read.
- **Agent-ready:** every operation has a JSON schema, so an LLM agent can build and run a flowsheet through tool
  calls and be checked against fixed cases.

Python 3.12, standard library only. SI units inside the library. Source code:
[github.com/nghiep-pham-ecosys/process-sim-lab](https://github.com/nghiep-pham-ecosys/process-sim-lab).

## Pages

| Page | What it covers |
|---|---|
| [CSTR](units/cstr.md) | isothermal stirred-tank reactor, first-order A → B |
| [PFR](units/pfr.md) | isothermal plug-flow reactor, first-order A → B |
| [Mixer](units/mixer.md) | streams joined, lowest inlet pressure |
| [Splitter](units/splitter.md) | one stream split by fractions |
| [Flash drum and its sizing](units/flash.md) | Rachford–Rice flash; vertical drum by Souders–Brown |
| [Heat exchanger](units/heat_exchanger.md) | counter-current area by the LMTD |
| [Shortcut column](units/shortcut_column.md) | Fenske–Underwood–Gilliland distillation |
| [Antoine vapour pressure](antoine.md) | NIST Antoine constants for three aromatics |
| [Flowsheet](flowsheet.md) | flowsheets in JSON, tear streams, direct substitution and Wegstein |
| [Flowsheet worked example](flowsheet-worked-example.md) | the week-3 example by hand and with the library |
| [Agent layer and MCP](agent.md) | tool schemas, runner, 25 evaluation cases, MCP server |
| [Local demo](demo.md) | a web form around the week-3 flowsheet |
| [Spec](spec.md) | the contract of the repository and the roadmap |

## Install and test

```bash
python3 -m pip install -e .
python3 -m unittest discover -v -s tests -p 'test_*.py'
```

Optional extras, each outside the core library: `mcp` (the MCP server), `demo` (the local web demo, Gradio) and
`docs` (this site, MkDocs). Build the site locally with `python3 -m pip install -e '.[docs]'` and `mkdocs serve`.

Every Python block on these pages runs in `tests/test_docs.py`, with the repository root as the working directory.
