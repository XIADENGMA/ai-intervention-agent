"""R891：浏览器页面请求 ``/api/config?html=0``，服务端不再为它渲染一份没人读的 Markdown。

现象（只有浏览器页面、没有 VS Code 的 Web UI 进程，真实 Chrome 156 + 真实进程）
=======================================================================

页面的 ``loadConfig()`` 取 ``/api/config``，响应里有 ``prompt``（Markdown 原文）和
``prompt_html``（服务端渲染好的 HTML）。页面自己用 ``marked`` 渲染 ``prompt``，``prompt_html``
一个字节都没读过；读它的只有 VS Code webview（``webview-ui.js``，走 ``sanitizePromptHtml``）。
但服务端每次都渲染：``render_markdown`` 第一次调用会 import Python-Markdown 和 Pygments
（再加上按需加载的词法分析器），一个只有浏览器页面的 Web UI 进程因此多占约 19 MiB 内存
（内存占用 40.9 → 60.1 MiB），第一次请求 82 ms（之后每次约 10 ms），响应也多出一份 HTML
（示例任务 15,019 B → 3,509 B）。

修复：``/api/config`` 认可选的查询参数 ``html``，值是 ``0`` 就不渲染，``prompt_html`` 返回空字符串，
别的字段原样；页面请求 ``/api/config?html=0``，VS Code 不传。修复后同一进程只多占约 0.6 MiB
（41.4 → 42.0 MiB），第一次请求 8.5 ms、之后每次约 4 ms。

契约
====

1. ``html=0``：三条会渲染的分支（激活任务、自动激活的第一个任务、没有任务队列时的单任务快照）
   都不调用 ``render_markdown``，``prompt_html`` 是空字符串，``prompt`` 和其它字段不变；
2. 没传、``html=1``、``html=``、``html=false``、``html=00``：都按以前渲染（只有恰好是 ``0`` 才跳过）；
3. 页面（``app.js`` 和它的压缩版）的 ``/api/config`` 请求都带 ``html=0``，页面的脚本从不读
   ``prompt_html``；VS Code 的脚本不带 ``html=0``，并且还在读 ``prompt_html``；
4. Swagger 里写明了这个参数。
"""

from __future__ import annotations

import inspect
import re
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from ai_intervention_agent.web_ui import WebFeedbackUI

REPO_ROOT = Path(__file__).resolve().parents[1]
STATIC_JS = REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "js"
VSCODE = REPO_ROOT / "packages" / "vscode"

PROMPT = "# R891 title\n\nbody **bold**"


@pytest.fixture(scope="module")
def ui() -> WebFeedbackUI:
    instance = WebFeedbackUI(
        prompt=PROMPT, task_id="r891-legacy", auto_resubmit_timeout=0, port=19891
    )
    instance.app.config["TESTING"] = True
    instance.limiter.enabled = False
    return instance


def _task(task_id: str = "r891-task") -> SimpleNamespace:
    return SimpleNamespace(
        task_id=task_id,
        status="active",
        prompt=PROMPT,
        predefined_options=["a"],
        predefined_options_defaults=[True],
        auto_resubmit_timeout=120,
        created_at=datetime(2026, 1, 1),
        get_remaining_time=lambda: 100,
    )


@contextmanager
def _queue(
    *, active: Any = None, first: Any = None, has_tasks: bool = False
) -> Iterator[MagicMock]:
    queue = MagicMock()
    queue.get_active_task.return_value = active
    queue.get_first_incomplete_task.return_value = first
    queue.has_tasks.return_value = has_tasks
    with patch("ai_intervention_agent.web_ui.get_task_queue", return_value=queue):
        yield queue


BRANCHES = {
    "active task": {"active": _task()},
    "first incomplete task": {"first": _task()},
    "single-task snapshot": {},
}


def _get(ui: WebFeedbackUI, query: str, **queue: Any) -> tuple[dict[str, Any], int]:
    with (
        _queue(**queue),
        patch.object(ui, "render_markdown", wraps=ui.render_markdown) as spy,
    ):
        resp = ui.app.test_client().get(
            "/api/config" + query, environ_base={"REMOTE_ADDR": "127.0.0.1"}
        )
    assert resp.status_code == 200
    return resp.get_json(), spy.call_count


def _stable(body: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in body.items() if k not in {"prompt_html", "server_time"}}


def _code_lines(text: str) -> str:
    """The script without its whole-line comments (the comments may talk about the field)."""
    return "\n".join(
        line
        for line in text.splitlines()
        if not line.lstrip().startswith(("//", "/*", "*"))
    )


class TestHtmlParameter:
    @pytest.mark.parametrize("branch", BRANCHES)
    def test_html_0_does_not_render(self, ui: WebFeedbackUI, branch: str) -> None:
        plain, calls = _get(ui, "?html=0", **BRANCHES[branch])

        assert calls == 0
        assert plain["prompt_html"] == ""
        assert plain["prompt"] == PROMPT
        assert plain["has_content"] is True

    @pytest.mark.parametrize("branch", BRANCHES)
    def test_everything_else_in_the_response_is_the_same(
        self, ui: WebFeedbackUI, branch: str
    ) -> None:
        plain, _ = _get(ui, "?html=0", **BRANCHES[branch])
        full, _ = _get(ui, "", **BRANCHES[branch])

        assert full["prompt_html"].startswith("<h1")
        assert _stable(plain) == _stable(full)

    @pytest.mark.parametrize("branch", BRANCHES)
    @pytest.mark.parametrize(
        "query", ["", "?html=1", "?html=", "?html=false", "?html=00"]
    )
    def test_anything_but_0_renders_as_before(
        self, ui: WebFeedbackUI, branch: str, query: str
    ) -> None:
        body, calls = _get(ui, query, **BRANCHES[branch])

        assert calls == 1
        assert body["prompt_html"].startswith("<h1")

    def test_a_finished_queue_is_unaffected(self, ui: WebFeedbackUI) -> None:
        for query in ("", "?html=0"):
            body, calls = _get(ui, query, has_tasks=True)
            assert calls == 0
            assert body["has_content"] is False
            assert body["prompt_html"] == ""

    def test_the_swagger_text_documents_the_parameter(self, ui: WebFeedbackUI) -> None:
        doc = inspect.getdoc(ui.app.view_functions["get_api_config"]) or ""
        assert "- name: html" in doc
        assert "in: query" in doc


class TestWhoAsksForWhat:
    @staticmethod
    def _config_requests(text: str) -> list[str]:
        return re.findall(r"""["'`](/api/config[^"'`]*)["'`]""", text)

    @pytest.mark.parametrize("name", ["app.js", "app.min.js"])
    def test_the_page_asks_without_html(self, name: str) -> None:
        requests = self._config_requests((STATIC_JS / name).read_text(encoding="utf-8"))
        assert requests == ["/api/config?html=0"]

    def test_no_other_script_of_the_page_fetches_the_config(self) -> None:
        offenders = {
            path.name: self._config_requests(path.read_text(encoding="utf-8"))
            for path in sorted(STATIC_JS.glob("*.js"))
            if path.name not in {"app.js", "app.min.js"}
            and any(
                not r.endswith("html=0")
                for r in self._config_requests(path.read_text(encoding="utf-8"))
            )
        }
        assert offenders == {}

    def test_the_page_never_reads_prompt_html(self) -> None:
        readers = [
            path.name
            for path in sorted(STATIC_JS.glob("*.js"))
            if "prompt_html" in _code_lines(path.read_text(encoding="utf-8"))
        ]
        assert readers == [], (
            "页面一读 prompt_html，就必须去掉 loadConfig 里的 html=0（R891）："
            + str(readers)
        )

    def test_vscode_still_asks_for_the_html_and_reads_it(self) -> None:
        sources = {
            path.name: path.read_text(encoding="utf-8")
            for path in sorted(VSCODE.glob("*"))
            if path.suffix in {".js", ".ts"}
        }
        assert "html=0" not in "".join(sources.values())
        assert "config.prompt_html" in sources["webview-ui.js"]
