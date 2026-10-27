"""R892：超过 20 万字符的消息不再做服务端 Markdown 渲染，退回转义后的 ``<pre><code>`` 纯文本。

现象（Web UI 进程内直接调用 ``render_markdown``，M3 Max，Python 3.13.15）
=====================================================================

Python-Markdown 处理“一大段不含空行的文本”是超线性的，Pygments 的行内样式还会把带语言标注的
代码块撑得很大。同一个进程里：

- 40 万字符 ≈ 0.44 s；100 万字符（MCP 工具的 ``MAX_MESSAGE_LENGTH`` 上限）≈ 2.0 s，进程多占约
  50 MiB；
- 40 万字符的 Python 围栏代码块 ≈ 1.2 s，响应 9.2 MB（正文本身 0.4 MB）；
- 500 万字符（``POST /api/tasks`` 的硬上限是 10 MB，``MAX_MESSAGE_LENGTH`` 只管 MCP 工具）：
  45 s 还没渲染完，一个线程占满一个核，进程 41 MiB → 480 MiB。

渲染在 ``_md_lock`` 里，所以这段时间里别的消息的渲染也在排队；``/api/config``、``/api/update`` 都
会调用它，VS Code 面板每次刷新都会取 ``/api/config``。

修复：``len(text) > _MD_RENDER_MAX_CHARS``（200,000 个字符）时直接返回
``<pre class="aiia-plain-prompt"><code>…转义后的原文…</code></pre>``，不走 Markdown、不进缓存。
内容完整，只是没有格式。同样的消息（真实 Web UI 的 ``GET /api/config``）：40 万字符 0.44 s → 11 ms，
100 万 2.0 s → 18 ms，40 万字符的 Python 围栏 1.23 s、9.2 MB → 16 ms、1.1 MB，500 万 45 s 超时 → 46 ms。

回退的标记故意只用 ``pre`` 和 ``code``、``pre`` 上只有 ``class``：VS Code webview 的
``sanitizePromptHtml`` 会删掉 ``style`` 属性，换行不能靠内联样式，靠 ``webview.css`` 里已有的
``.markdown-content pre code { white-space: pre-wrap }``。

契约
====

1. 阈值是 200,000 个字符，恰好等于阈值还渲染，多一个字符就退回；
2. 退回的输出只有 ``pre``（带一个 ``class``）和 ``code`` 两个标签，原文经 HTML 解析后一字不差，
   里面的 ``</code></pre><img onerror=…>`` 之类被转义，不会变成标签，Markdown 语法也不会被解释；
3. 退回不创建 ``markdown.Markdown`` 实例（不 import Markdown / Pygments）、不进缓存，也不拿
   ``_md_lock``；
4. 正常长度的消息还是渲染并缓存；空文本还是 ``""``；
5. 标记用到的标签和属性都在 VS Code 的 ``sanitizePromptHtml`` 白名单里，``webview.css`` 里的
   ``pre code`` 规则会折行；
6. 经 ``/api/config``：超长的任务消息拿到退回的 HTML，``prompt`` 原文不变。
"""

from __future__ import annotations

import re
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from ai_intervention_agent import web_ui
from ai_intervention_agent.web_ui import (
    _MD_RENDER_MAX_CHARS,
    WebFeedbackUI,
    _render_plain_text_fallback,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
WEBVIEW_UI_JS = REPO_ROOT / "packages" / "vscode" / "webview-ui.js"
WEBVIEW_CSS = REPO_ROOT / "packages" / "vscode" / "webview.css"

FALLBACK_OPEN = '<pre class="aiia-plain-prompt"><code>'
NASTY = (
    "line one\n<b>bold</b> & \"quotes\" 'single' </code></pre><img src=x onerror=alert(1)>\n"
    "# not a heading\n- not a list\n```python\nprint(1)\n```\n[link](http://x)\n"
    "<script>alert(1)</script>\n中文 ✓ 😀\n"
)


@pytest.fixture
def ui(monkeypatch: pytest.MonkeyPatch) -> WebFeedbackUI:
    """每个测试一个干净的渲染状态（还没有 Markdown 实例、缓存是空的）。"""
    instance = WebFeedbackUI(prompt="r892", task_id="r892", port=19892)
    instance.app.config["TESTING"] = True
    instance.limiter.enabled = False
    monkeypatch.setattr(instance, "md", None)
    monkeypatch.setattr(instance, "_md_cache", {})
    return instance


class _Tags(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tags: list[tuple[str, dict[str, str | None]]] = []
        self.text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags.append((tag, dict(attrs)))

    def handle_data(self, data: str) -> None:
        self.text.append(data)


def _parse(markup: str) -> _Tags:
    parser = _Tags()
    parser.feed(markup)
    parser.close()
    return parser


def _long(text: str = NASTY) -> str:
    return text + "x" * (_MD_RENDER_MAX_CHARS + 1 - len(text))


class TestThreshold:
    def test_the_limit_is_two_hundred_thousand_characters(self) -> None:
        assert _MD_RENDER_MAX_CHARS == 200_000

    def test_exactly_the_limit_is_still_rendered(
        self, ui: WebFeedbackUI, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(web_ui, "_MD_RENDER_MAX_CHARS", 1000)
        text = "# t\n\n" + "x" * 995
        assert len(text) == 1000

        out = ui.render_markdown(text)

        assert out.startswith("<h1")
        assert ui.md is not None

    def test_one_more_character_falls_back(
        self, ui: WebFeedbackUI, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(web_ui, "_MD_RENDER_MAX_CHARS", 1000)
        text = "# t\n\n" + "x" * 996
        assert len(text) == 1001

        out = ui.render_markdown(text)

        assert out.startswith(FALLBACK_OPEN)

    def test_the_real_limit_applies_to_a_real_message(self, ui: WebFeedbackUI) -> None:
        text = _long()
        assert len(text) == _MD_RENDER_MAX_CHARS + 1

        start = time.perf_counter()
        out = ui.render_markdown(text)
        took = time.perf_counter() - start

        assert out.startswith(FALLBACK_OPEN)
        # rendering 200,001 characters of this shape as Markdown takes well over a second
        # elsewhere; the fallback is an escape and a concatenation
        assert took < 1.0

    def test_empty_text_is_still_empty(self, ui: WebFeedbackUI) -> None:
        assert ui.render_markdown("") == ""


class TestFallbackOutput:
    def test_only_pre_and_code_with_one_class(self) -> None:
        parsed = _parse(_render_plain_text_fallback(NASTY))

        assert parsed.tags == [("pre", {"class": "aiia-plain-prompt"}), ("code", {})]

    def test_the_text_survives_the_round_trip_unchanged(self) -> None:
        parsed = _parse(_render_plain_text_fallback(NASTY))

        assert "".join(parsed.text) == NASTY

    def test_markup_in_the_text_is_escaped_not_interpreted(self) -> None:
        out = _render_plain_text_fallback(NASTY)

        assert "<img" not in out and "<script" not in out and "<b>" not in out
        assert "&lt;/code&gt;&lt;/pre&gt;&lt;img src=x onerror=alert(1)&gt;" in out
        assert out.startswith(FALLBACK_OPEN) and out.endswith("</code></pre>")
        assert out.count("</code></pre>") == 1

    def test_markdown_syntax_is_left_alone(self) -> None:
        out = _render_plain_text_fallback("# not a heading\n- not a list\n**x**")

        assert (
            out == FALLBACK_OPEN + "# not a heading\n- not a list\n**x**</code></pre>"
        )

    def test_there_is_no_inline_style_for_the_webview_sanitizer_to_strip(self) -> None:
        assert "style=" not in _render_plain_text_fallback(NASTY)


class TestNoMarkdownWork:
    def test_the_fallback_makes_no_markdown_instance_and_no_cache_entry(
        self, ui: WebFeedbackUI
    ) -> None:
        out = ui.render_markdown(_long())

        assert out.startswith(FALLBACK_OPEN)
        assert ui.md is None
        assert ui._md_cache == {}

    def test_the_fallback_does_not_wait_for_the_render_lock(
        self, ui: WebFeedbackUI
    ) -> None:
        results: list[str] = []
        with ui._md_lock:
            worker = threading.Thread(
                target=lambda: results.append(ui.render_markdown(_long())), daemon=True
            )
            worker.start()
            worker.join(timeout=5)
            finished = not worker.is_alive()
        worker.join(timeout=5)

        assert finished, "an oversized message waited behind the Markdown render lock"
        assert results and results[0].startswith(FALLBACK_OPEN)

    def test_a_normal_message_is_rendered_and_cached(self, ui: WebFeedbackUI) -> None:
        out = ui.render_markdown("# hello\n\n**bold**")

        assert out.startswith("<h1") and "<strong>bold</strong>" in out
        assert ui._md_cache == {"# hello\n\n**bold**": out}
        assert ui.render_markdown("# hello\n\n**bold**") is out


def _js_set(source: str, opening: str) -> set[str]:
    start = source.index(opening) + len(opening)
    return set(re.findall(r"'([\w-]+)'", source[start : source.index("])", start)]))


class TestTheWebviewKeepsTheMarkup:
    def test_every_tag_and_attribute_is_on_the_sanitizer_allow_list(self) -> None:
        source = WEBVIEW_UI_JS.read_text(encoding="utf-8")
        allowed_tags = _js_set(source, "const ALLOWED_TAGS = new Set([")
        block_start = source.index("const ALLOWED_ATTR = {")
        attr_block = source[block_start : source.index("\n      }\n", block_start)]
        allowed_attrs = {
            tag: set(re.findall(r"'([\w-]+)'", body))
            for tag, body in re.findall(r"(\w+): new Set\(\[([^\]]*)\]\)", attr_block)
        }

        parsed = _parse(_render_plain_text_fallback(NASTY))

        for tag, attrs in parsed.tags:
            assert tag in allowed_tags
            assert set(attrs) <= allowed_attrs.get(tag, set()), (tag, attrs)

    def test_the_stylesheet_wraps_long_lines_in_pre_code(self) -> None:
        css = re.sub(
            r"/\*.*?\*/", "", WEBVIEW_CSS.read_text(encoding="utf-8"), flags=re.S
        )
        declarations: dict[str, str] = {}
        for selector, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
            if " ".join(selector.split()) == ".markdown-content pre code":
                for part in body.split(";"):
                    if ":" in part:
                        name, value = part.split(":", 1)
                        declarations[name.strip()] = value.strip()

        assert declarations.get("white-space") == "pre-wrap"
        assert declarations.get("overflow-wrap") == "anywhere"


def _task(prompt: str) -> SimpleNamespace:
    return SimpleNamespace(
        task_id="r892-task",
        status="active",
        prompt=prompt,
        predefined_options=[],
        predefined_options_defaults=[],
        auto_resubmit_timeout=120,
        created_at=datetime(2026, 1, 1),
        get_remaining_time=lambda: 100,
    )


@contextmanager
def _queue_with(task: Any) -> Iterator[MagicMock]:
    queue = MagicMock()
    queue.get_active_task.return_value = task
    with patch("ai_intervention_agent.web_ui.get_task_queue", return_value=queue):
        yield queue


class TestThroughTheRoute:
    def test_api_config_serves_the_fallback_for_a_huge_task_message(
        self, ui: WebFeedbackUI
    ) -> None:
        prompt = _long()
        with _queue_with(_task(prompt)):
            resp = ui.app.test_client().get(
                "/api/config", environ_base={"REMOTE_ADDR": "127.0.0.1"}
            )

        body = resp.get_json()
        assert resp.status_code == 200
        assert body["prompt"] == prompt
        assert body["prompt_html"].startswith(FALLBACK_OPEN)
        assert "".join(_parse(body["prompt_html"]).text) == prompt
        assert ui.md is None
