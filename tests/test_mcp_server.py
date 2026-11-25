"""Tests for the MCP server around the tool runner.

The first group is pure Python and always runs. The client tests need the optional extra (``pip install -e
'.[mcp]'``) and are skipped without it, so the base CI stays standard library only. They talk to the server through
the SDK's in-process client and through a real stdio subprocess, and build the week-3 flowsheet.
"""

import contextlib
import io
import json
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path

from process_sim_lab.agent.runner import OPERATIONS, run_tool
from process_sim_lab.agent.schemas import TOOL_SCHEMAS
from process_sim_lab.mcp_server import call_tool, main, tool_listing

try:
    import anyio
    from mcp import Client, MCPError, StdioServerParameters

    from process_sim_lab.mcp_server import build_server
except ImportError:
    anyio = None

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
EXAMPLE = ROOT / "examples" / "reactor_flash_recycle.json"
# MCP specification 2025-11-25, "Tool names": 1 to 128 characters from A-Z, a-z, 0-9, _, - and .
TOOL_NAME = re.compile(r"[A-Za-z0-9_.-]{1,128}")
VALUE_TOL = 1e-8  # mol/s, as tests/test_flowsheet.py

# The week-3 flowsheet by hand (evals/cases/10-flowsheet-reactor-flash-recycle.json): flows in mol/s for (A, I, B).
HAND = {
    "recycle": {"A": 1.0, "I": 0.6, "B": 0.4},
    "liquid": {"A": 0.75, "I": 2.25, "B": 4.5},
    "purge": {"A": 0.25, "I": 0.15, "B": 0.1},
}


def week3_flowsheet():
    return json.loads(EXAMPLE.read_text(encoding="utf-8"))


def run_python(code):
    env = dict(os.environ, PYTHONPATH=str(SRC))
    return subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, timeout=60)


class ToolListingTest(unittest.TestCase):
    """Pure Python: the MCP tool list is the runner's, without the SDK."""

    def test_tool_names_match_operations(self):
        self.assertEqual([t["name"] for t in tool_listing()], list(OPERATIONS))

    def test_input_schema_is_the_runner_schema(self):
        for tool in tool_listing():
            with self.subTest(tool=tool["name"]):
                self.assertEqual(tool["inputSchema"], TOOL_SCHEMAS[tool["name"]])
                self.assertEqual(tool["description"], TOOL_SCHEMAS[tool["name"]]["description"])
                self.assertEqual(tool["inputSchema"]["type"], "object")
                self.assertRegex(tool["name"], TOOL_NAME)
                json.dumps(tool, allow_nan=False)

    def test_listing_is_a_copy(self):
        listing = tool_listing()
        listing[0]["inputSchema"]["properties"].clear()
        self.assertTrue(TOOL_SCHEMAS[listing[0]["name"]]["properties"])

    def test_module_imports_without_the_sdk(self):
        out = run_python("import sys; sys.modules['mcp'] = None; import process_sim_lab.mcp_server as m; "
                         "print(len(m.tool_listing()))")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(out.stdout.strip(), str(len(TOOL_SCHEMAS)))

    def test_main_without_the_sdk_exits_2_with_a_hint(self):
        out = run_python("import sys; sys.modules['mcp'] = None; from process_sim_lab.mcp_server import main; "
                         "sys.exit(main([]))")
        self.assertEqual(out.returncode, 2)
        self.assertIn("pip install -e '.[mcp]'", out.stderr)

    def test_main_rejects_arguments(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(main(["--port", "8000"]), 2)
        self.assertIn("unexpected arguments", err.getvalue())


    def test_readme_config_snippet(self):
        text = (ROOT / "README.md").read_text(encoding="utf-8")
        section = text[text.index("## Use from an MCP client"):]
        config = json.loads(re.search(r"^```json\n(.*?)^```", section, re.DOTALL | re.MULTILINE).group(1))
        server = config["mcpServers"]["process-sim-lab"]
        self.assertEqual(server["args"], ["-m", "process_sim_lab.mcp_server"])


class CallToolTest(unittest.TestCase):
    """Pure Python: one tool call as the server makes it."""

    def test_success_is_the_runner_output(self):
        call = call_tool("solve_flowsheet", week3_flowsheet())
        self.assertFalse(call.is_error)
        self.assertFalse(call.unknown_tool)
        self.assertEqual(call.output, run_tool("solve_flowsheet", week3_flowsheet()))
        self.assertEqual(json.loads(call.text), call.output)

    def test_bad_input_is_a_tool_error(self):
        call = call_tool("cstr", None)
        self.assertTrue(call.is_error)
        self.assertFalse(call.unknown_tool)
        self.assertEqual(call.output["error"]["type"], "invalid_input")

    def test_unknown_tool_is_flagged(self):
        call = call_tool("distil", {})
        self.assertTrue(call.unknown_tool)
        self.assertEqual(call.output["error"]["known_tools"], list(TOOL_SCHEMAS))


@unittest.skipIf(anyio is None, "MCP Python SDK not installed (pip install -e '.[mcp]')")
class McpClientTest(unittest.TestCase):
    """Through the SDK client: list the tools, build the week-3 flowsheet, get structured errors."""

    def run_client(self, server, check):
        async def session():
            async with Client(server) as client:
                await check(client)

        anyio.run(session)

    def check_flowsheet(self, result):
        self.assertFalse(result.is_error)
        out = result.structured_content
        self.assertEqual(json.loads(result.content[0].text), out)
        self.assertTrue(out["ok"])
        r = out["result"]
        self.assertEqual(r["method"], "wegstein")
        self.assertLessEqual(r["residual"], r["tol"])
        for stream, flows in HAND.items():
            for component, value in flows.items():
                with self.subTest(stream=stream, component=component):
                    self.assertAlmostEqual(r["streams"][stream]["flows"][component], value, delta=VALUE_TOL)

    def test_in_process(self):
        async def check(client):
            listed = (await client.list_tools()).tools
            self.assertEqual([t.name for t in listed], list(OPERATIONS))
            for tool in listed:
                self.assertEqual(tool.input_schema, TOOL_SCHEMAS[tool.name])

            self.check_flowsheet(await client.call_tool("solve_flowsheet", week3_flowsheet()))

            bad = week3_flowsheet()
            bad["units"][1]["params"]["volume"] = -2.0
            result = await client.call_tool("solve_flowsheet", bad)
            self.assertTrue(result.is_error)
            error = result.structured_content["error"]
            self.assertEqual(error["type"], "invalid_input")
            self.assertEqual(error["issues"][0]["path"], "$.units[1].params.volume")

            with self.assertRaises(MCPError) as raised:
                await client.call_tool("distil", {})
            self.assertEqual(raised.exception.code, -32602)
            self.assertEqual(raised.exception.data["known_tools"], list(TOOL_SCHEMAS))

        self.run_client(build_server(), check)

    def test_stdio_subprocess(self):
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "process_sim_lab.mcp_server"],
            env=dict(os.environ, PYTHONPATH=str(SRC)),
        )

        async def check(client):
            listed = (await client.list_tools()).tools
            self.assertEqual({t.name: t.input_schema for t in listed}, TOOL_SCHEMAS)
            self.check_flowsheet(await client.call_tool("solve_flowsheet", week3_flowsheet()))

        self.run_client(params, check)


if __name__ == "__main__":
    unittest.main()
