"""MCP server around the tool runner: any MCP client can list and call every tool of the agent layer.

The server reuses the agent layer as it is. ``tools/list`` returns one tool per entry of
``process_sim_lab.agent.schemas.TOOL_SCHEMAS``, with that schema as the tool's input schema (JSON Schema draft
2020-12, SI units in every description). ``tools/call`` hands the name and arguments to
``process_sim_lab.agent.runner.run_tool`` and returns its JSON:

    success   is_error false, structured content {"ok": true,  "tool": name, "result": {...}}
    failure   is_error true,  structured content {"ok": false, "tool": name, "error": {"type": ..., ...}}

The same JSON is also sent as one text content block, for clients that read only text. A bad call (invalid input,
a model error, a recycle loop that does not converge) is a tool result with ``is_error`` set, so the model sees the
runner's error and can correct the call. An unknown tool name is a protocol error (JSON-RPC -32602, invalid
params), as the MCP specification asks, with the known tool names in its data.

The server needs the official MCP Python SDK (``pip install -e '.[mcp]'``, MIT licence). The SDK is imported only
when the server is built, so the rest of this module, and the library, work without it. Run the server over stdio:

    python3 -m process_sim_lab.mcp_server        # or the console script: process-sim-lab-mcp

Source: Model Context Protocol specification, "Server features: Tools" (https://modelcontextprotocol.io/specification,
accessed 2026-11-25), and the MCP Python SDK 2.x low-level ``Server`` (https://github.com/modelcontextprotocol/python-sdk,
accessed 2026-11-25).
"""

from __future__ import annotations

import copy
import json
import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from process_sim_lab import __version__
from process_sim_lab.agent.runner import UNKNOWN_TOOL, run_tool
from process_sim_lab.agent.schemas import tool_definitions

if TYPE_CHECKING:
    from mcp.server.lowlevel import Server

SERVER_NAME = "process-sim-lab"
INSTRUCTIONS = (
    "Chemical process simulation tools. Every quantity is in SI units (mol/s, K, Pa, m, m2, m3, s, W). "
    "Each tool's input schema states the unit of every field and carries one example input. "
    "solve_flowsheet takes a whole flowsheet in the week-3 JSON form (feeds, units, tear streams) and returns the "
    "streams and each unit's sizing. A failed call returns is_error with the runner's error type "
    "(invalid_input with the path of each bad field, model_error or convergence_error)."
)
INSTALL_HINT = "the MCP server needs the MCP Python SDK: python3 -m pip install -e '.[mcp]'"
INVALID_PARAMS = -32602  # JSON-RPC 2.0 "Invalid params"


def tool_listing() -> list[dict[str, Any]]:
    """Every runner tool as an MCP tool definition ``{"name", "description", "inputSchema"}``.

    The input schema is a deep copy of the runner's schema, so a client cannot change the runner's copy.
    """
    return [
        {"name": t["name"], "description": t["description"], "inputSchema": copy.deepcopy(t["input_schema"])}
        for t in tool_definitions()
    ]


@dataclass(frozen=True)
class ToolCall:
    """The outcome of one MCP tool call, before it is wrapped in the SDK's types.

    Attributes:
        output: the runner's JSON (``{"ok", "tool", "result"}`` or ``{"ok", "tool", "error"}``).
        text: ``output`` as JSON text (no NaN or infinity).
        is_error: true when the runner reports a failure.
        unknown_tool: true when no tool has that name; the server turns this into a protocol error.
    """

    output: dict[str, Any]
    text: str
    is_error: bool
    unknown_tool: bool


def call_tool(name: Any, arguments: Any) -> ToolCall:
    """Run one MCP tool call through ``run_tool``. Missing arguments (``None``) are an empty object."""
    output = run_tool(name, {} if arguments is None else arguments)
    error_type = None if output["ok"] else output["error"]["type"]
    return ToolCall(
        output=output,
        text=json.dumps(output, allow_nan=False),
        is_error=not output["ok"],
        unknown_tool=error_type == UNKNOWN_TOOL,
    )


def build_server() -> Server:
    """The low-level MCP server with the ``tools/list`` and ``tools/call`` handlers.

    Raises:
        ImportError: the MCP Python SDK is not installed (``pip install -e '.[mcp]'``).
    """
    from mcp import types
    from mcp.server.lowlevel import Server
    from mcp.shared.exceptions import MCPError

    tools = [
        types.Tool(name=t["name"], description=t["description"], input_schema=t["inputSchema"])
        for t in tool_listing()
    ]

    async def on_list_tools(ctx: Any, params: types.PaginatedRequestParams | None) -> types.ListToolsResult:
        return types.ListToolsResult(tools=tools)

    async def on_call_tool(ctx: Any, params: types.CallToolRequestParams) -> types.CallToolResult:
        call = call_tool(params.name, params.arguments)
        if call.unknown_tool:
            error = call.output["error"]
            raise MCPError(INVALID_PARAMS, error["message"], data={"known_tools": error["known_tools"]})
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=call.text)],
            structured_content=call.output,
            is_error=call.is_error,
        )

    return Server(
        SERVER_NAME,
        version=__version__,
        instructions=INSTRUCTIONS,
        on_list_tools=on_list_tools,
        on_call_tool=on_call_tool,
    )


async def serve_stdio() -> None:
    """Serve one MCP connection over stdin and stdout until the client closes it."""
    from mcp.server.stdio import stdio_server

    server = build_server()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def main(argv: list[str] | None = None) -> int:
    """Command line: serve over stdio. Exit code 2 when the MCP Python SDK is missing."""
    args = sys.argv[1:] if argv is None else argv
    if args in (["-h"], ["--help"]):
        print(f"usage: python3 -m process_sim_lab.mcp_server\n\nServe the {len(tool_listing())} process-sim-lab "
              "tools to an MCP client over stdio.")
        return 0
    if args:
        print(f"unexpected arguments: {' '.join(args)} (the server takes none)", file=sys.stderr)
        return 2
    try:
        import anyio
        import mcp.server.lowlevel  # noqa: F401  (fail here, before stdio is taken over)
    except ImportError:
        print(f"error: {INSTALL_HINT}", file=sys.stderr)
        return 2
    anyio.run(serve_stdio)
    return 0


if __name__ == "__main__":
    sys.exit(main())
