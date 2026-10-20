"""R726 · the MCP side of local images.

The MCP process runs next to the files, so it decides what may be read: it asks
the client for its workspace folders (``roots/list``), resolves the allowed
folders, ships the bytes with the task and rewrites the prompt. These tests pin
that wiring end to end with fakes for the MCP client and the Web UI, plus a few
runs through a real fastmcp server and client (a fake of today's API cannot tell
when the SDK changes it, which is how roots stopped working on fastmcp 4 unseen):

* the configuration and the roots request are only paid for when the prompt
  contains an image reference;
* every failure (no ``ctx``, no roots support, timeouts, bad config, a crash in
  the scanner) leaves the prompt as written instead of failing the tool call;
* the task payload carries ``prompt_images`` only when there are images, with a
  longer timeout, and the push notification keeps the author's text.
"""

from __future__ import annotations

import asyncio
import base64
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastmcp import Client, FastMCP
from fastmcp.server.context import Context
from mcp.types import ListRootsResult, Root
from pydantic import FileUrl

from ai_intervention_agent import local_images as li
from ai_intervention_agent import server_feedback
from ai_intervention_agent.server_config import WebUIConfig

PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d4944415478da63f8cfc0f01f0005000201a1b0d1d40000000049454e44ae426082"
)
TASK_ID = "task-r726"


class FakeSession:
    """The part of ``ServerSession`` the roots request goes through."""

    def __init__(
        self,
        supports_roots: bool = True,
        error: Exception | None = None,
        roots: list[Any] | None = None,
        request_error: Exception | None = None,
        hang: bool = False,
    ):
        self.supports_roots = supports_roots
        self.error = error
        self.roots = roots or []
        self.request_error = request_error
        self.hang = hang
        self.asked: list[Any] = []
        self.requests: list[tuple[Any, Any]] = []

    def check_client_capability(self, capability: Any) -> bool:
        self.asked.append(capability)
        if self.error is not None:
            raise self.error
        return self.supports_roots

    async def send_request(
        self, request: Any, result_type: Any, *_: Any, **__: Any
    ) -> Any:
        self.requests.append((request, result_type))
        if self.hang:
            await asyncio.sleep(3600)
        if self.request_error is not None:
            raise self.request_error
        return SimpleNamespace(roots=self.roots)


class FakeContext:
    def __init__(
        self,
        roots: list[Any] | None = None,
        *,
        supports_roots: bool = True,
        list_error: Exception | None = None,
        capability_error: Exception | None = None,
        hang: bool = False,
    ):
        self.session = FakeSession(
            supports_roots, capability_error, roots, list_error, hang
        )
        self.infos: list[str] = []

    @property
    def list_calls(self) -> int:
        return len(self.session.requests)

    async def info(self, message: str, **_: Any) -> None:
        self.infos.append(message)


class FakeConfig:
    def __init__(self, local_image_dirs: Any = ("auto",)):
        self.local_image_dirs = local_image_dirs
        self.requested: list[str] = []

    def get_section(self, name: str) -> dict[str, Any]:
        self.requested.append(name)
        return {"local_image_dirs": self.local_image_dirs}


def root_for(path: Path) -> Root:
    return Root(uri=FileUrl(path.as_uri()))


def use_config(monkeypatch: pytest.MonkeyPatch, setting: Any = ("auto",)) -> FakeConfig:
    fake = FakeConfig(setting)
    monkeypatch.setattr(server_feedback, "get_config", lambda: fake)
    return fake


def prepare(ctx: Any, message: str) -> li.PreparedPrompt:
    return asyncio.run(server_feedback._prepare_local_images(ctx, message, TASK_ID))


def client_roots(ctx: Any) -> list[Path]:
    return asyncio.run(server_feedback._client_roots(ctx))


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "shot.png").write_bytes(PNG)
    return root


def test_without_a_context_there_are_no_roots():
    assert client_roots(None) == []


def test_a_client_without_roots_support_is_never_asked_for_them(workspace: Path):
    ctx = FakeContext([root_for(workspace)], supports_roots=False)

    assert client_roots(ctx) == []
    assert ctx.list_calls == 0


def test_the_capability_check_asks_for_roots_support(workspace: Path):
    ctx = FakeContext([root_for(workspace)])

    client_roots(ctx)

    (capability,) = ctx.session.asked
    assert capability.roots is not None


def test_the_roots_are_asked_for_with_a_roots_list_request(workspace: Path):
    ctx = FakeContext([root_for(workspace)])

    client_roots(ctx)

    ((request, result_type),) = ctx.session.requests
    assert request.method == "roots/list"
    assert result_type is ListRootsResult


def test_the_declared_roots_are_returned_as_local_paths(tmp_path: Path):
    first = tmp_path / "one"
    second = tmp_path / "with space"
    ctx = FakeContext([root_for(first), root_for(second)])

    assert client_roots(ctx) == [first, second]


def test_roots_that_are_not_local_paths_are_dropped(tmp_path: Path):
    mine = tmp_path / "mine"
    ctx = FakeContext(
        [
            SimpleNamespace(uri="https://example.com/ws"),
            SimpleNamespace(uri="file://attacker/share/ws"),
            SimpleNamespace(uri="not a uri"),
            root_for(mine),
        ]
    )

    assert client_roots(ctx) == [mine]


@pytest.mark.parametrize(
    "ctx",
    [
        FakeContext(list_error=RuntimeError("client crashed")),
        FakeContext(capability_error=RuntimeError("no session")),
    ],
    ids=["roots request raises", "capability check raises"],
)
def test_a_failing_roots_request_degrades_to_no_roots(ctx: FakeContext):
    assert client_roots(ctx) == []


def test_a_client_that_never_answers_roots_does_not_hang_the_tool(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(server_feedback, "_CLIENT_ROOTS_TIMEOUT_S", 0.05)
    ctx: Any = FakeContext(hang=True)

    async def within_a_few_seconds() -> list[Path]:
        return await asyncio.wait_for(server_feedback._client_roots(ctx), 5)

    started = time.monotonic()
    roots = asyncio.run(within_a_few_seconds())

    assert roots == []
    assert time.monotonic() - started < 2


def roots_seen_by_a_real_server(**client_options: Any) -> list[str]:
    """Run ``_client_roots`` in a tool of a real fastmcp server, asked by a real client."""
    server = FastMCP("roots-probe")

    @server.tool
    async def declared_roots(ctx: Context) -> list[str]:
        return [str(path) for path in await server_feedback._client_roots(ctx)]

    async def call() -> list[str]:
        async with Client(server, **client_options) as client:
            return list((await client.call_tool("declared_roots", {})).data)

    return asyncio.run(call())


def test_a_real_client_hands_its_roots_to_the_server(tmp_path: Path):
    first = tmp_path / "one"
    second = tmp_path / "with space"

    seen = roots_seen_by_a_real_server(
        roots=[first.as_uri(), second.as_uri()], mode="legacy"
    )

    assert seen == [str(first), str(second)]


def test_a_real_client_without_roots_support_is_not_asked(tmp_path: Path):
    assert roots_seen_by_a_real_server(mode="legacy") == []


def test_the_sessionless_protocol_falls_back_to_no_roots(tmp_path: Path):
    # The 2026-07-28 protocol, which the default "auto" mode negotiates, has no
    # server-to-client requests (roots are deprecated there): the request cannot
    # be sent, and the tool call still succeeds with the other allowed folders.
    assert roots_seen_by_a_real_server(roots=[tmp_path.as_uri()]) == []


def test_a_prompt_without_images_does_no_work_at_all(
    monkeypatch: pytest.MonkeyPatch, workspace: Path
):
    configuration_reads: list[str] = []

    def spy() -> FakeConfig:
        configuration_reads.append("read")
        return FakeConfig()

    monkeypatch.setattr(server_feedback, "get_config", spy)
    ctx = FakeContext([root_for(workspace)])
    message = "plain text with [a link](https://example.com) and `code`"

    prepared = prepare(ctx, message)

    assert prepared.prompt == message
    assert prepared.images == ()
    assert configuration_reads == []
    assert ctx.list_calls == 0


def test_remote_images_alone_leave_the_prompt_untouched(
    monkeypatch: pytest.MonkeyPatch, workspace: Path
):
    use_config(monkeypatch)
    ctx = FakeContext([root_for(workspace)])
    message = "![x](https://example.com/a.png) ![y](data:image/png;base64,AAAA)"

    prepared = prepare(ctx, message)

    assert prepared.prompt == message
    assert prepared.images == ()


def test_the_feature_can_be_switched_off(
    monkeypatch: pytest.MonkeyPatch, workspace: Path
):
    use_config(monkeypatch, [])
    ctx = FakeContext([root_for(workspace)])
    message = f"![x]({workspace}/shot.png)"

    prepared = prepare(ctx, message)

    assert prepared.prompt == message
    assert prepared.images == ()
    assert ctx.list_calls == 0


def test_an_image_inside_a_client_root_is_attached_and_the_prompt_rewritten(
    monkeypatch: pytest.MonkeyPatch, workspace: Path
):
    use_config(monkeypatch, [str(workspace)])
    ctx = FakeContext([root_for(workspace)])

    prepared = prepare(ctx, "look: ![shot](shot.png)")

    assert [image.data for image in prepared.images if image] == [PNG]
    assert prepared.prompt == f"look: ![shot](/api/tasks/{TASK_ID}/images/0)"


def test_the_default_setting_hands_the_client_roots_to_the_resolver(
    monkeypatch: pytest.MonkeyPatch, workspace: Path
):
    use_config(monkeypatch, ["auto"])
    seen: list[tuple[Any, list[Path]]] = []
    real = li.resolve_allowed_dirs

    def spy(setting: Any, client_roots: Any = (), **kwargs: Any) -> list[Path]:
        seen.append((setting, list(client_roots)))
        return real(setting, client_roots, **kwargs)

    monkeypatch.setattr(li, "resolve_allowed_dirs", spy)

    prepare(FakeContext([root_for(workspace)]), "![x](shot.png)")

    assert seen == [(["auto"], [workspace])]


def test_a_file_outside_the_allowed_folders_is_not_read(
    monkeypatch: pytest.MonkeyPatch, workspace: Path, tmp_path: Path
):
    secret = tmp_path / "secret.png"
    secret.write_bytes(PNG)
    use_config(monkeypatch, [str(workspace)])
    opened: list[str] = []
    real_open = li.os.open

    def tracking_open(path: Any, *args: Any, **kwargs: Any) -> int:
        opened.append(str(path))
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(li.os, "open", tracking_open)

    prepared = prepare(FakeContext([root_for(workspace)]), f"![s]({secret})")

    assert prepared.images == ()
    assert "image not shown" in prepared.prompt
    assert not any(path.endswith("secret.png") for path in opened)


@pytest.mark.parametrize(
    "setting",
    [None, "auto", 5, {"auto": True}],
    ids=["missing", "string", "number", "mapping"],
)
def test_a_malformed_setting_falls_back_to_the_default(
    monkeypatch: pytest.MonkeyPatch, workspace: Path, setting: Any
):
    use_config(monkeypatch, setting)

    prepared = prepare(FakeContext([root_for(workspace)]), "![x](shot.png)")

    assert [image.data for image in prepared.images if image] == [PNG]


def test_a_crash_in_the_scanner_leaves_the_prompt_untouched_and_is_logged(
    monkeypatch: pytest.MonkeyPatch, workspace: Path
):
    use_config(monkeypatch, [str(workspace)])

    def boom(*_: Any, **__: Any) -> None:
        raise RuntimeError("scanner exploded")

    monkeypatch.setattr(li, "prepare_prompt_images", boom)
    warning = MagicMock()
    monkeypatch.setattr(server_feedback.logger, "warning", warning)
    message = "![x](shot.png)"

    prepared = prepare(FakeContext([root_for(workspace)]), message)

    assert prepared.prompt == message
    assert prepared.images == ()
    warning.assert_called_once()
    assert "scanner exploded" in warning.call_args.args[0]


def test_a_broken_configuration_leaves_the_prompt_untouched(
    monkeypatch: pytest.MonkeyPatch, workspace: Path
):
    def broken() -> None:
        raise RuntimeError("config unreadable")

    monkeypatch.setattr(server_feedback, "get_config", broken)
    message = "![x](shot.png)"

    prepared = prepare(FakeContext([root_for(workspace)]), message)

    assert prepared.prompt == message
    assert prepared.images == ()


def test_slow_file_access_cannot_stall_the_tool_call(
    monkeypatch: pytest.MonkeyPatch, workspace: Path
):
    use_config(monkeypatch, [str(workspace)])
    monkeypatch.setattr(server_feedback, "_LOCAL_IMAGES_TIMEOUT_S", 0.05)

    def stuck(*_: Any, **__: Any) -> None:
        time.sleep(0.6)

    monkeypatch.setattr(server_feedback, "_read_local_images", stuck)
    message = "![x](shot.png)"
    ctx: Any = FakeContext([root_for(workspace)])

    async def timed() -> tuple[li.PreparedPrompt, float]:
        started = time.monotonic()
        prepared = await server_feedback._prepare_local_images(ctx, message, TASK_ID)
        return prepared, time.monotonic() - started

    prepared, elapsed = asyncio.run(timed())

    assert prepared.prompt == message
    assert prepared.images == ()
    assert elapsed < 0.5


class Harness:
    """Runs ``interactive_feedback`` against fakes for the Web UI and the client."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch):
        self.posted: dict[str, Any] = {}
        self.notifications: list[dict[str, Any]] = []
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"success": True}
        posted = self.posted

        class Client:
            async def post(self, url: str, **kwargs: Any) -> Any:
                posted["url"] = url
                posted.update(kwargs)
                return response

        async def noop(*_: Any, **__: Any) -> None:
            return None

        async def finished(*_: Any, **__: Any) -> dict[str, str]:
            return {"interactive_feedback": "ok"}

        notifier = MagicMock()
        notifier.send_notification.side_effect = lambda **kwargs: (
            self.notifications.append(kwargs) or "event-1"
        )
        sm = server_feedback.service_manager
        monkeypatch.setattr(
            sm,
            "get_web_ui_config",
            lambda: (WebUIConfig(host="127.0.0.1", port=12345), 30),
        )
        monkeypatch.setattr(sm, "get_async_client", lambda _config: Client())
        monkeypatch.setattr(sm, "ensure_web_ui_running", noop)
        monkeypatch.setattr(server_feedback, "wait_for_task_completion", finished)
        monkeypatch.setattr(server_feedback, "NOTIFICATION_AVAILABLE", True)
        monkeypatch.setattr(server_feedback, "notification_manager", notifier)
        monkeypatch.setattr(
            server_feedback.server_config, "_generate_task_id", lambda: TASK_ID
        )

    def run(self, message: str, ctx: Any = None) -> None:
        asyncio.run(
            server_feedback.interactive_feedback(
                message=message,
                predefined_options=None,
                feedback_placeholder=None,
                header_label=None,
                loop_id=None,
                loop_objective=None,
                loop_phase=None,
                success_criteria=None,
                iteration_label=None,
                ctx=ctx,
            )
        )

    @property
    def body(self) -> dict[str, Any]:
        return self.posted["json"]


@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch) -> Harness:
    return Harness(monkeypatch)


def test_the_task_carries_the_images_and_the_rewritten_prompt(
    monkeypatch: pytest.MonkeyPatch, harness: Harness, workspace: Path
):
    use_config(monkeypatch, [str(workspace)])

    harness.run("check ![shot](shot.png) please", FakeContext([root_for(workspace)]))

    assert harness.body["task_id"] == TASK_ID
    assert harness.body["prompt"] == (
        f"check ![shot](/api/tasks/{TASK_ID}/images/0) please"
    )
    assert harness.body["prompt_images"] == [
        {"mime_type": "image/png", "data": base64.b64encode(PNG).decode("ascii")}
    ]
    assert harness.posted["timeout"] == server_feedback._PROMPT_IMAGES_POST_TIMEOUT_S


def test_a_task_without_images_keeps_the_original_payload_shape(
    monkeypatch: pytest.MonkeyPatch, harness: Harness
):
    use_config(monkeypatch)

    harness.run("no pictures here", None)

    assert "prompt_images" not in harness.body
    assert harness.body["prompt"] == "no pictures here"
    assert harness.posted["timeout"] == 5


def test_a_prompt_whose_images_were_all_refused_sends_no_images_and_the_short_timeout(
    monkeypatch: pytest.MonkeyPatch, harness: Harness, workspace: Path, tmp_path: Path
):
    outside = tmp_path / "outside.png"
    outside.write_bytes(PNG)
    use_config(monkeypatch, [str(workspace)])

    harness.run(f"![o]({outside})", FakeContext([root_for(workspace)]))

    assert "prompt_images" not in harness.body
    assert "image not shown" in harness.body["prompt"]
    assert harness.posted["timeout"] == 5


def test_the_notification_shows_the_text_the_author_wrote(
    monkeypatch: pytest.MonkeyPatch, harness: Harness, workspace: Path
):
    use_config(monkeypatch, [str(workspace)])

    harness.run("see ![shot](shot.png)", FakeContext([root_for(workspace)]))

    (notification,) = harness.notifications
    assert notification["message"] == "see ![shot](shot.png)"
    assert "/api/tasks/" not in notification["message"]


def test_the_tool_still_works_when_the_client_has_no_context(
    monkeypatch: pytest.MonkeyPatch, harness: Harness, workspace: Path
):
    use_config(monkeypatch, [str(workspace)])

    harness.run(f"![shot]({workspace}/shot.png)", None)

    assert harness.body["prompt"] == f"![shot](/api/tasks/{TASK_ID}/images/0)"
    assert len(harness.body["prompt_images"]) == 1


def test_the_tool_description_matches_the_limits_the_code_enforces():
    description = server_feedback.interactive_feedback.__defaults__
    assert description is not None
    field = next(
        value
        for value in description
        if getattr(value, "description", None) and "Markdown image" in value.description
    )
    text = field.description

    assert (
        f"max {li.MAX_IMAGES} per message, {li.MAX_IMAGE_BYTES >> 20} MB each" in text
    )
    for extension in li._EXTENSIONS - {".jpeg"}:
        assert extension.lstrip(".") in text
