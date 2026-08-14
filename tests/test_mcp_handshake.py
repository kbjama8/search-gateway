# -*- coding: utf-8 -*-
"""stdio JSON-RPC handshake + tool-call tests.

Covers both the bare `search-gateway` invocation (what OpenCode's MCP config
uses — no subcommand) and the explicit `serve` subcommand, plus a regression
guard for the `saved_queries` module/function shadowing bug.
"""

import asyncio
import json
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def _handshake(args: list[str]) -> list[str]:
    async def _run() -> list[str]:
        params = StdioServerParameters(
            command=sys.executable, args=["-m", "search_gateway.cli", *args],
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                return [t.name for t in tools.tools]

    return asyncio.run(_run())


def _call_tool(args: list[str], tool: str, arguments: dict) -> dict:
    async def _run() -> dict:
        params = StdioServerParameters(
            command=sys.executable, args=["-m", "search_gateway.cli", *args],
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                res = await session.call_tool(tool, arguments)
                for c in res.content:
                    if c.type == "text":
                        return json.loads(c.text)
                return {}

    return asyncio.run(_run())


def _assert_surface(names: list[str]) -> None:
    assert len(names) == 14
    assert "saved_queries" in names
    assert "search" in names and "research_answer" in names


def test_bare_command_lists_14_tools():
    # The bare command is what `"command": ["search-gateway"]` runs — it must
    # not require the `serve` subcommand to be present (regression guard).
    _assert_surface(_handshake([]))


def test_explicit_serve_lists_14_tools():
    _assert_surface(_handshake(["serve"]))


def test_saved_queries_tool_not_shadowed():
    # The module `saved_queries` is imported and the MCP tool shares its name.
    # A previous bug let the tool function shadow the module, so the tool
    # crashed with AttributeError. `action=list` must return a dict, not error.
    result = _call_tool([], "saved_queries", {"action": "list"})
    assert "queries" in result, f"saved_queries tool broken: {result}"
    assert isinstance(result["queries"], list)
