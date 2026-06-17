"""R457 dynamic MCP tool registration spike.

This is deliberately a spike-style contract test, not a product feature test:
the project still exposes ``interactive_feedback`` as its stable core tool.
The dynamic FastMCP instance below proves the local SDK behavior we would need
before adding any future optional/conditional diagnostic tools.
"""

from __future__ import annotations

import asyncio
import inspect
import re
import unittest

from fastmcp import FastMCP
from fastmcp.tools import tool
from mcp.types import ToolAnnotations

import ai_intervention_agent.server as server

_MCP_TOOL_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")


def _list_tool_names(mcp: FastMCP) -> list[str]:
    return [t.name for t in asyncio.run(mcp.list_tools())]


class TestStaticCoreToolSurface(unittest.TestCase):
    """The human-in-the-loop entrypoint must remain statically discoverable."""

    def test_interactive_feedback_is_always_registered(self) -> None:
        self.assertIn("interactive_feedback", _list_tool_names(server.mcp))


class TestFastMcpDynamicToolSpike(unittest.TestCase):
    """Local FastMCP 3.2.4 dynamic add/remove behavior."""

    def _make_spike_tool(self):
        @tool(
            name="diagnostic.echo",
            annotations=ToolAnnotations(
                title="Diagnostic Echo",
                readOnlyHint=True,
                destructiveHint=False,
                idempotentHint=True,
                openWorldHint=False,
            ),
            tags={"diagnostic", "spike"},
            version="0.1.0",
        )
        def diagnostic_echo(value: int = 1) -> int:
            """Return the input value unchanged."""
            return value

        return diagnostic_echo

    def test_dynamic_add_remove_round_trips_metadata(self) -> None:
        mcp = FastMCP("dynamic-spike", on_duplicate="error")
        spike_tool = self._make_spike_tool()

        self.assertRegex("diagnostic.echo", _MCP_TOOL_NAME_RE)
        mcp.add_tool(spike_tool)

        tools = asyncio.run(mcp.list_tools())
        dynamic_tool = next((t for t in tools if t.name == "diagnostic.echo"), None)
        assert dynamic_tool is not None, "dynamic tool should appear in list_tools()"

        self.assertEqual(getattr(dynamic_tool, "tags", None), {"diagnostic", "spike"})
        self.assertEqual(getattr(dynamic_tool, "version", None), "0.1.0")
        annotations = dynamic_tool.annotations
        assert annotations is not None, (
            "dynamic tool annotations should survive add_tool"
        )
        self.assertEqual(annotations.title, "Diagnostic Echo")
        self.assertTrue(annotations.readOnlyHint)
        self.assertFalse(annotations.destructiveHint)
        self.assertTrue(annotations.idempotentHint)
        self.assertFalse(annotations.openWorldHint)

        mcp.local_provider.remove_tool("diagnostic.echo")
        self.assertNotIn("diagnostic.echo", _list_tool_names(mcp))

    def test_duplicate_name_and_version_raise_with_error_policy(self) -> None:
        mcp = FastMCP("dynamic-spike", on_duplicate="error")
        spike_tool = self._make_spike_tool()
        mcp.add_tool(spike_tool)

        with self.assertRaisesRegex(ValueError, r"tool:diagnostic\.echo@0\.1\.0"):
            mcp.add_tool(spike_tool)

    def test_current_fastmcp_api_uses_on_duplicate_not_legacy_name(self) -> None:
        init_params = inspect.signature(FastMCP).parameters
        self.assertIn("on_duplicate", init_params)
        self.assertNotIn("on_duplicate_tools", init_params)

    def test_add_tool_accepts_preconstructed_tool_or_callable_only(self) -> None:
        add_tool_params = inspect.signature(FastMCP.add_tool).parameters
        self.assertEqual(list(add_tool_params), ["self", "tool"])


if __name__ == "__main__":
    unittest.main()
