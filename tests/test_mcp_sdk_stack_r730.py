"""R730 · the MCP SDK stack the tests run is the stack users install.

``uvx ai-intervention-agent`` resolves its dependencies on every start, while CI
installs from ``uv.lock``. The project used to declare ``fastmcp>=3.0.0`` with no
upper bound and never declared ``mcp``, although it imports it. The lock stayed on
fastmcp 3 / mcp 1 while users already ran fastmcp 4 / mcp 2, and nothing went red
when ``Context.list_roots`` disappeared (images stopped resolving against the
client's workspace folders) or when two deprecation notices began to reach stderr
on every start.

What is pinned:

* both packages are declared, each with a floor and a ceiling that closes the
  major line, so a new SDK major cannot reach users before the tests ran on it;
* the installed versions and the versions in ``uv.lock`` sit inside those ranges,
  so the tests really run on what the ranges allow;
* through a real fastmcp server and client (not a fake of today's API) the tool
  hints, the server icons and an image block still leave the process under their
  protocol names, and ``ctx.info`` is still delivered while the SDK's one known
  deprecation notice about it is silenced and nothing else is.
"""

from __future__ import annotations

import asyncio
import base64
import importlib.metadata
import os
import subprocess
import sys
import tomllib
import warnings
from pathlib import Path
from typing import Any

import pytest
from fastmcp import Client, FastMCP
from fastmcp.server.context import Context
from mcp import MCPDeprecationWarning
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version

from ai_intervention_agent import server, server_config, server_feedback

REPO = Path(__file__).resolve().parent.parent
SDK_PACKAGES = ("fastmcp", "mcp")
MODES = ("legacy", "auto")


def declared(name: str) -> Requirement:
    project = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    matches = [
        requirement
        for requirement in map(Requirement, project["project"]["dependencies"])
        if canonicalize_name(requirement.name) == name
    ]
    assert len(matches) == 1, f"{name} must be declared exactly once: {matches}"
    return matches[0]


@pytest.mark.parametrize("name", SDK_PACKAGES)
def test_each_sdk_package_has_a_floor_and_a_ceiling_one_major_up(name: str):
    specifiers = {
        spec.operator: Version(spec.version) for spec in declared(name).specifier
    }

    assert set(specifiers) == {">=", "<"}, (
        f"{declared(name)} needs a floor and a ceiling"
    )
    assert specifiers["<"] == Version(str(specifiers[">="].major + 1))


@pytest.mark.parametrize("name", SDK_PACKAGES)
def test_the_installed_version_is_inside_the_declared_range(name: str):
    installed = Version(importlib.metadata.version(name))

    assert declared(name).specifier.contains(installed, prereleases=True), (
        f"{name} {installed} is outside {declared(name)}: the venv has drifted from "
        "pyproject.toml, so the tests are not running on what users get"
    )


@pytest.mark.parametrize("name", SDK_PACKAGES)
def test_the_lock_pins_a_version_inside_the_declared_range(name: str):
    lock = tomllib.loads((REPO / "uv.lock").read_text(encoding="utf-8"))
    pinned = [
        Version(package["version"])
        for package in lock["package"]
        if canonicalize_name(package["name"]) == name
    ]

    assert pinned, f"{name} is not in uv.lock"
    for version in pinned:
        assert declared(name).specifier.contains(version, prereleases=True), (
            f"uv.lock pins {name} {version}, outside {declared(name)}: CI would test "
            "a stack that users cannot get"
        )


# --- what leaves the process uses the protocol's names -------------------------


@pytest.mark.parametrize("mode", MODES)
def test_the_tool_hints_go_out_under_their_protocol_names(mode: str):
    async def list_tools() -> list[Any]:
        async with Client(server.mcp, mode=mode) as client:
            return list(await client.list_tools())

    (tool,) = [
        tool
        for tool in asyncio.run(list_tools())
        if tool.name == "interactive_feedback"
    ]
    annotations = tool.model_dump(mode="json", by_alias=True, exclude_none=True)[
        "annotations"
    ]

    assert {key: annotations[key] for key in annotations if key.endswith("Hint")} == {
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    }


def test_the_server_icons_go_out_with_a_mime_type():
    async def server_info() -> dict[str, Any]:
        async with Client(server.mcp, mode="legacy") as client:
            assert client.initialize_result is not None
            return client.initialize_result.server_info.model_dump(
                mode="json", by_alias=True, exclude_none=True
            )

    icons = asyncio.run(server_info())["icons"]

    assert {icon["mimeType"] for icon in icons} == {"image/png", "image/svg+xml"}
    assert all(icon["src"].startswith("data:") for icon in icons)


def test_an_image_block_goes_out_as_mime_type_and_base64_data():
    data = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16).decode()

    block, _ = server_config._process_image(
        {"data": data, "content_type": "image/png"}, 0
    )

    assert block is not None
    assert block.model_dump(mode="json", by_alias=True, exclude_none=True) == {
        "type": "image",
        "data": data,
        "mimeType": "image/png",
    }


# --- ctx.info ----------------------------------------------------------------------


def emit_through_a_real_session(
    mode: str, *, with_our_filter: bool
) -> tuple[list[Any], list[warnings.WarningMessage]]:
    """Send ``ctx.info`` from a tool of a real server; return what the client got
    and every warning raised on the way. The filter state is rebuilt from scratch
    so that only ``with_our_filter`` decides whether the notice is hidden."""
    probe = FastMCP("info-probe")

    @probe.tool
    async def say(ctx: Context) -> str:
        await server_feedback._emit_ctx_info(ctx, "task created", task_id="t-1")
        return "done"

    received: list[Any] = []

    async def on_log(message: Any) -> None:
        received.append(message)

    async def call() -> None:
        async with Client(probe, mode=mode, log_handler=on_log) as client:
            await client.call_tool("say", {})

    with warnings.catch_warnings(record=True) as caught:
        warnings.resetwarnings()
        warnings.simplefilter("always")
        if with_our_filter:
            server_feedback._silence_logging_capability_deprecation()
        asyncio.run(call())
    return received, caught


@pytest.mark.parametrize("mode", MODES)
def test_ctx_info_still_reaches_the_client_and_raises_no_warning(mode: str):
    received, caught = emit_through_a_real_session(mode, with_our_filter=True)

    assert [str(message.data) for message in received] == [
        str({"msg": "task created", "extra": {"task_id": "t-1"}})
    ]
    assert [
        str(warning.message)
        for warning in caught
        if "deprecat" in str(warning.message).lower()
    ] == []


@pytest.mark.parametrize("mode", MODES)
def test_the_sdk_still_warns_about_the_logging_capability_without_the_filter(mode: str):
    """Why the filter exists. When this fails the SDK no longer warns (or says it
    differently): delete ``_silence_logging_capability_deprecation``."""
    _, caught = emit_through_a_real_session(mode, with_our_filter=False)

    notices = [
        str(warning.message)
        for warning in caught
        if issubclass(warning.category, MCPDeprecationWarning)
    ]
    assert len(notices) == 1
    assert notices[0].startswith("The logging capability is deprecated")


def test_the_filter_hides_that_one_notice_and_nothing_else():
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        server_feedback._silence_logging_capability_deprecation()

        warnings.warn(
            "The logging capability is deprecated as of 2026-07-28 (SEP-2577).",
            MCPDeprecationWarning,
            stacklevel=1,
        )
        with pytest.raises(MCPDeprecationWarning):
            warnings.warn(
                "The roots capability is deprecated as of 2026-07-28 (SEP-2577).",
                MCPDeprecationWarning,
                stacklevel=1,
            )
        with pytest.raises(DeprecationWarning):
            warnings.warn(
                "The logging capability is deprecated as of 2026-07-28 (SEP-2577).",
                DeprecationWarning,
                stacklevel=1,
            )


def test_importing_the_module_installs_the_filter(tmp_path: Path):
    """The server never calls the helper by hand: importing the module must do it.

    A fresh interpreter with every warning turned into an error (``-W error``): the
    notice raised after the import is silent only if the import installed the filter.
    """
    code = (
        "import warnings\n"
        "import ai_intervention_agent.server_feedback\n"
        "from mcp.shared.exceptions import MCPDeprecationWarning\n"
        "warnings.warn('The logging capability is deprecated as of 2026-07-28 "
        "(SEP-2577).', MCPDeprecationWarning)\n"
        "print('silent')\n"
    )
    environment = {
        **os.environ,
        "AI_INTERVENTION_AGENT_CONFIG_FILE": str(tmp_path / "config.toml"),
    }

    done = subprocess.run(
        [sys.executable, "-W", "error", "-c", code],
        capture_output=True,
        text=True,
        timeout=120,
        env=environment,
        check=False,
    )

    assert (done.returncode, done.stdout.strip()) == (0, "silent"), done.stderr
