# Agent layer and MCP

Every operation is a tool with a JSON schema, so an LLM agent can call the library through tool calls, and its answers
can be checked against fixed cases. No LLM is called by the library or its tests.

Code: [`src/process_sim_lab/agent/`](../src/process_sim_lab/agent/) (schemas, runner, evaluation) and
[`src/process_sim_lab/mcp_server.py`](../src/process_sim_lab/mcp_server.py) ·
cases: [`evals/cases/`](../evals/cases/)

| Tool | Operation | Page |
|---|---|---|
| `cstr`, `pfr` | isothermal first-order reactor A → B | [CSTR](units/cstr.md), [PFR](units/pfr.md) |
| `mixer`, `splitter` | mix streams; split one stream by fraction | [Mixer](units/mixer.md), [Splitter](units/splitter.md) |
| `flash_drum` | isothermal flash with given K-values (Rachford–Rice) | [Flash drum](units/flash.md) |
| `shortcut_column` | Fenske–Underwood–Gilliland column | [Shortcut column](units/shortcut_column.md) |
| `heat_exchanger_area` | counter-current exchanger area from the duty and the LMTD | [Heat exchanger](units/heat_exchanger.md) |
| `antoine_vapour_pressure`, `antoine_saturation_temperature` | pure-component Antoine equation | [Antoine](antoine.md) |
| `solve_flowsheet` | a flowsheet in the week-3 JSON form; streams and each unit's sizing | [Flowsheet](flowsheet.md) |

`run_tool(name, arguments)` checks the arguments against the schema, calls the operation and returns plain JSON. It
never raises for a bad call: a bad call comes back as a structured error of type `unknown_tool`, `invalid_input`,
`model_error` or `convergence_error`.

```python
from process_sim_lab.agent.runner import run_tool

out = run_tool("heat_exchanger_area", {"duty": 5e5, "overall_u": 500.0,               # W, W/(m2 K)
                                       "hot_in": 423.15, "hot_out": 363.15,           # K
                                       "cold_in": 303.15, "cold_out": 343.15})        # K
assert out["ok"] and abs(out["result"]["area"] - 14.3841036) < 1e-6

bad = run_tool("heat_exchanger_area", {"duty": 5e5, "overall_u": -500.0,
                                       "hot_in": 423.15, "hot_out": 363.15,
                                       "cold_in": 303.15, "cold_out": 343.15})
assert bad["error"]["type"] == "invalid_input"
```

Twenty-five evaluation cases are fixed tool calls with expected values, each with its source and tolerance:

```bash
python3 -m process_sim_lab.agent.evaluate      # PASS/FAIL per case, then "25/25 cases passed"
```

An MCP server wraps the same runner, so any MCP client can list and call every tool. It needs the optional extra
`mcp` (the official MCP Python SDK, MIT licence):

```bash
python3 -m pip install -e '.[mcp]'
python3 -m process_sim_lab.mcp_server --help      # the server speaks MCP over stdio; a client starts it
```

The client set-up (Claude Code, Claude Desktop or a project `.mcp.json`) is in the
[README](../README.md#use-from-an-mcp-client).
