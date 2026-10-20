"""R780：任务 ID 是内部标识符，必须"无聊"——不依赖目录名里有什么字符、也不依赖目录还在不在。

现象（真实 stdio MCP 服务 + 真实 Web UI 子进程，端到端复现）
============================================================

任务 ID 由 ``_generate_task_id`` 生成：``<当前目录名>-<uuid4>``。目录名原样拼进去，
而这个 ID 之后要进 URL 路径、查询串、CSS 属性选择器、HTML 属性和日志。两个后果：

1. 目录名里含 ``#`` 或 ``?``（``C#-demo``、``what?``）时，MCP 服务轮询
   ``GET /api/tasks/C#-demo-<uuid>``：``#`` 之后被当作 URL 片段丢掉，请求实际落在
   ``/api/tasks/C``，Web UI 回 404，``wait_for_task_completion`` 把 404 当成"任务丢了"，
   2.5 秒后就把"请重新调用"的提示返回给 AI——没有等用户；任务还留在 Web UI 里
   （幽灵任务）。AI 收到的是重调提示，会立刻再调一次，同样的事再来一遍，形成快速循环。
   带空格的目录名在同一个实验里一切正常，所以这个问题只在特定字符上冒出来。
   Bark 的点击链接 ``?task_id={task_id}`` 同理：``#``、``&``、空格都会让链接指向别处或失效。
2. 服务进程启动之后工作目录被删掉（临时工程目录、``git worktree remove``），
   ``Path.cwd()`` 抛 ``FileNotFoundError``；它只为了一个展示用的前缀，却让
   ``interactive_feedback`` 在建任务之前就失败，每次调用都是 0 秒返回重调提示，
   直到服务重启。代码库里别处（``dir_settings.safe_cwd``、``config_manager``）早就
   容忍目录不存在，这一处是漏网的。

修复
====

* ``_generate_task_id`` 的前缀只保留字母、数字（任何语言）、依附在它们后面的组合符号和
  ``._-``，其余字符一律换成 ``-`` 并合并、去掉首尾的 ``-``；空前缀回落到 ``task``。
  工作目录不存在时同样回落到 ``task``（用 ``dir_settings.safe_cwd``）。
* 纵深防御：两处拼 ``/api/tasks/<id>`` 的 Python 代码、Bark 的 ``{task_id}`` 占位、
  Web UI 里还没做编码的 4 处 ``fetch`` 都对 ID 做百分号编码（VS Code 的 webview
  早就这么做，这是补齐一致性；正常 ID 编码后原样不变）。
* Web UI 子进程继承 MCP 服务的工作目录。以脚本方式启动时 Flask 为了推算一个本应用
  用不到的 ``instance_path`` 会调 ``os.getcwd()``，``app.run()`` 又会为了找 ``.env``
  再调一次：工作目录被删掉后子进程在这两处崩溃，MCP 服务白等 15 秒，报的还是
  "请检查端口是否被占用"。现在显式给出 ``instance_path``，并以 ``load_dotenv=False``
  启动——这同时让项目目录里的 ``.env``（密钥、代理、``FLASK_*``）不再被悄悄读进
  Web UI 进程。

契约
====

1. 生成的 ID 对任何目录名都不含 URL / HTML / 选择器敏感字符，ASCII 目录名的 ID
   不需要任何编码就能直接放进 URL；
2. 可读性：字母数字（含中文）和组合符号保留，``._-`` 保留；
3. 工作目录不存在或不可读时，前缀是 ``task``，``interactive_feedback`` 照常建任务；
4. 任何 ID（含需要编码的）拼进 Web UI URL 时都经过百分号编码；
5. Bark 点击链接里的 ``task_id`` 经过百分号编码，普通 ID 不变；
6. Web UI 应用在工作目录不存在时也能构造，且不读取工作目录里的 ``.env``。

测试矩阵
========

A. 前缀清洗：逐类字符（URL 结构字符、引号和尖括号、空白与控制符、emoji、中文、重音符号）；
B. 目录不存在：模拟 ``Path.cwd`` 抛错、真删目录（非 Windows）、``interactive_feedback`` 端到端；
C. 两处 Python URL 都对 ID 编码；
D. Bark 渲染出的链接对 ID 编码；
E. Web UI 应用按脚本方式（``__main__``）在没有工作目录时构造；``app.run`` 带
   ``load_dotenv=False``（AST 检查，避免真的起服务）；
F. 源码：Web UI 与 VS Code webview 里每处 ``/api/tasks/<id>`` 的 ID 都包着
   ``encodeURIComponent``（今后新增的 ``fetch`` 忘了编码会在这里失败）。

85 个测试里 48 个在旧代码上失败：清洗用例中含需要替换的字符的那些、三个"没有工作目录"
的单元用例和端到端用例、两处 Python URL、Bark 的特殊字符用例和 ``{base_url}`` 不被
编码的用例、E 的三个用例、F 里 ``app.js`` 和 ``multi_task.js`` 两个文件；其余是对照
（普通目录名不变、普通 ID 不被改动、VS Code webview 本来就编码、扫描规则本身）。
"""

from __future__ import annotations

import ast
import asyncio
import os
import re
import shutil
import sys
import types
import unicodedata
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import quote

import pytest

import ai_intervention_agent.server_feedback as server
import ai_intervention_agent.web_ui as web_ui
from ai_intervention_agent.server_config import WebUIConfig, _generate_task_id
from tests.test_bark_click_url_mcp_path_r778 import EXTERNAL, _bark_provider, _event
from tests.test_notification_off_event_loop_r776 import TASK_ID, _Harness

REPO_ROOT = Path(__file__).resolve().parent.parent
UUID_RE = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
# 出现在 ID 里就可能破坏 URL 路径 / 查询串 / HTML 属性 / CSS 选择器的字符
UNSAFE = set("#?%/\\\"'<>&+;=[]{}()|^`~*!@$,:") | set(" \t\r\n\x00\x1b")


def _in_project(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    """让 ``_generate_task_id`` 以为当前目录叫 ``name``（不真建目录，跨平台）。"""
    folder = Path("/work") / name if name else Path("/")
    monkeypatch.setattr(Path, "cwd", classmethod(lambda _cls: folder))


def _prefix(task_id: str) -> str:
    match = re.fullmatch(rf"(.*)-({UUID_RE})", task_id)
    assert match, f"ID 的形状不对: {task_id!r}"
    return match.group(1)


class TestThePrefixIsCleaned:
    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("plain", "plain"),
            ("with.dots_and-dashes", "with.dots_and-dashes"),
            ("my project", "my-project"),
            ("a   b", "a-b"),
            ("C#-demo", "C-demo"),
            ("what?", "what"),
            ("100%", "100"),
            ("R&D+tools", "R-D-tools"),
            ('say "hi"', "say-hi"),
            ("a<b>c'd", "a-b-c-d"),
            ("tab\there\nnewline\x00nul", "tab-here-newline-nul"),
            ("🚀 launch", "launch"),
            ("emoji ❤️ here", "emoji-here"),
            ("-edge-", "edge"),
            ("###", "task"),
            ("", "task"),
            ("我的项目", "我的项目"),
            ("проект №1", "проект-1"),
            ("Café", "Café"),
            ("Cafe\u0301", "Cafe\u0301"),
        ],
    )
    def test_each_kind_of_character(
        self, monkeypatch: pytest.MonkeyPatch, name: str, expected: str
    ) -> None:
        _in_project(monkeypatch, name)

        task_id = _generate_task_id()

        assert _prefix(task_id) == expected
        uuid.UUID(task_id[-36:])

    @pytest.mark.parametrize(
        "name",
        [
            "C#-demo",
            "what?",
            "100%",
            "a b",
            'q"uote',
            "a<b>",
            "x&y",
            "p+q",
            "back\\slash",
            "semi;colon",
            "[brackets]",
            "(parens)",
            "tab\tchar",
            "line\nbreak",
            "weird `~!@$^*|{}=,:",
        ],
    )
    def test_nothing_that_could_break_a_url_or_an_attribute_survives(
        self, monkeypatch: pytest.MonkeyPatch, name: str
    ) -> None:
        _in_project(monkeypatch, name)

        task_id = _generate_task_id()

        assert not UNSAFE & set(task_id), task_id
        assert quote(task_id, safe="") == task_id

    def test_an_ascii_project_needs_no_encoding_at_all(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _in_project(monkeypatch, "My Project (v2) #final?")

        task_id = _generate_task_id()

        assert task_id.isascii()
        assert quote(task_id, safe="") == task_id

    def test_ids_stay_unique(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _in_project(monkeypatch, "C#-demo")

        assert len({_generate_task_id() for _ in range(200)}) == 200

    def test_no_character_is_dropped_silently_from_readable_names(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        name = "Résumé 履歴書 über"
        _in_project(monkeypatch, name)

        prefix = _prefix(_generate_task_id())

        assert prefix == "Résumé-履歴書-über"
        assert all(unicodedata.category(ch)[0] in "LMN" or ch == "-" for ch in prefix)


class TestWithoutAWorkingDirectory:
    def test_a_failing_cwd_falls_back_to_task(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def gone(*_args: Any, **_kwargs: Any) -> Path:
            raise FileNotFoundError(2, "No such file or directory")

        monkeypatch.setattr(Path, "cwd", classmethod(gone))

        assert _prefix(_generate_task_id()) == "task"

    def test_an_unreadable_cwd_falls_back_to_task(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def denied(*_args: Any, **_kwargs: Any) -> Path:
            raise PermissionError(13, "Permission denied")

        monkeypatch.setattr(Path, "cwd", classmethod(denied))

        assert _prefix(_generate_task_id()) == "task"

    @pytest.mark.skipif(
        sys.platform == "win32", reason="Windows 不允许删除进程的当前目录"
    )
    def test_a_deleted_working_directory(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        doomed = tmp_path / "doomed"
        doomed.mkdir()
        monkeypatch.chdir(doomed)
        shutil.rmtree(doomed)
        with pytest.raises(OSError):
            os.getcwd()

        try:
            assert _prefix(_generate_task_id()) == "task"
        finally:
            os.chdir(tmp_path)

    def test_interactive_feedback_still_creates_the_task(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        real_generate = _generate_task_id
        harness = _Harness(monkeypatch)
        monkeypatch.setattr(server.server_config, "_generate_task_id", real_generate)

        def gone(*_args: Any, **_kwargs: Any) -> Path:
            raise FileNotFoundError(2, "No such file or directory")

        monkeypatch.setattr(Path, "cwd", classmethod(gone))

        async def main() -> list[Any]:
            return await harness.call()

        result = asyncio.run(main())

        assert "the answer" in result[0].text
        assert len(harness.waited) == 1
        assert _prefix(harness.waited[0]) == "task"


class TestTheWebUiDoesNotNeedTheWorkingDirectory:
    """``python web_ui.py`` 起来的子进程继承 MCP 服务的工作目录。

    脚本方式启动时 Flask 的包名是 ``__main__``，``find_spec("__main__")`` 抛
    ``ValueError``，Flask 就退回 ``os.getcwd()`` 去推算一个本应用根本用不到的
    ``instance_path``；之后 ``app.run()`` 又会为了找 ``.env`` 再问一次。工作目录被
    删掉后子进程在这两处崩溃，MCP 服务白等 15 秒，报的还是"请检查端口是否被占用"。
    显式给出 ``instance_path``、关掉 ``load_dotenv`` 就不再问系统。
    """

    @staticmethod
    def _script_mode(monkeypatch: pytest.MonkeyPatch) -> None:
        """``python web_ui.py`` 留下的样子：``__main__`` 有 ``__file__``、``__spec__`` 是 None。

        用真的 ``sys.modules["__main__"]`` 会随 pytest 的启动方式（脚本、``-m``、xdist
        worker）变，所以这里换成固定的替身；``find_spec`` 对它照常抛 ``ValueError``。
        """
        script = types.ModuleType("__main__")
        script.__file__ = web_ui.__file__
        script.__spec__ = None
        monkeypatch.setattr(web_ui, "__name__", "__main__")
        monkeypatch.setitem(sys.modules, "__main__", script)

    def test_the_app_is_built_with_the_working_directory_gone(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._script_mode(monkeypatch)

        def gone() -> str:
            raise FileNotFoundError(2, "No such file or directory")

        monkeypatch.setattr(os, "getcwd", gone)

        ui = web_ui.WebFeedbackUI(prompt="r780", host="127.0.0.1", port=0)

        assert os.path.isabs(ui.app.instance_path)

    def test_the_instance_path_does_not_depend_on_the_working_directory(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        self._script_mode(monkeypatch)
        monkeypatch.chdir(tmp_path)

        ui = web_ui.WebFeedbackUI(prompt="r780", host="127.0.0.1", port=0)

        assert not Path(ui.app.instance_path).is_relative_to(tmp_path)

    def test_the_server_is_started_without_loading_dotenv_files(self) -> None:
        """``app.run()`` 默认会读工作目录（及上级）的 ``.env`` / ``.flaskenv`` 灌进环境。

        那是 Flask 命令行工具的习惯，不是这个应用想要的：MCP 服务通常就在用户的项目
        目录里启动，项目的 ``.env``（密钥、代理、``FLASK_*``）会悄悄进入 Web UI 进程；
        工作目录不存在时 ``find_dotenv`` 还会直接抛 ``FileNotFoundError``。
        """
        tree = ast.parse(Path(web_ui.__file__).read_text(encoding="utf-8"))
        runs = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "run"
            and isinstance(node.func.value, ast.Attribute)
            and node.func.value.attr == "app"
        ]

        assert len(runs) == 1
        keywords = {kw.arg: kw.value for kw in runs[0].keywords}
        flag = keywords.get("load_dotenv")
        assert isinstance(flag, ast.Constant)
        assert flag.value is False


class _Response:
    def __init__(self, status_code: int = 200, payload: dict[str, Any] | None = None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self) -> dict[str, Any]:
        return self._payload


class _UrlClient:
    """记录请求的 URL；任务一查就是已完成，SSE 不可用（只走轮询）。"""

    def __init__(self) -> None:
        self.gets: list[str] = []
        self.posts: list[str] = []

    async def get(self, url: str, **_kwargs: Any) -> _Response:
        await asyncio.sleep(0)
        self.gets.append(url)
        return _Response(
            200,
            {
                "success": True,
                "task": {
                    "status": "completed",
                    "result": {"interactive_feedback": "ok"},
                },
            },
        )

    async def post(self, url: str, **_kwargs: Any) -> _Response:
        await asyncio.sleep(0)
        self.posts.append(url)
        return _Response(200)

    def stream(self, *_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("SSE is not part of this test")


ODD_ID = "C#-my proj&x?y%41-" + "0123456789ab"
ENCODED_ID = "C%23-my%20proj%26x%3Fy%2541-0123456789ab"


class TestPythonUrlsEncodeTheTaskId:
    def test_the_poll_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = _UrlClient()
        sm = server.service_manager
        monkeypatch.setattr(
            sm,
            "get_web_ui_config",
            lambda: (WebUIConfig(host="127.0.0.1", port=18998), 30),
        )
        monkeypatch.setattr(sm, "get_async_client", lambda _config: client)

        async def main() -> Any:
            return await server.wait_for_task_completion(ODD_ID, timeout=30)

        result = asyncio.run(main())

        assert result == {"interactive_feedback": "ok"}
        assert client.gets
        assert client.gets[0] == f"http://127.0.0.1:18998/api/tasks/{ENCODED_ID}"

    def test_the_close_url(self) -> None:
        client = _UrlClient()

        async def main() -> None:
            await server._close_orphan_task_best_effort(
                ODD_ID, "127.0.0.1", 18998, client=client
            )

        asyncio.run(main())

        assert client.posts == [
            f"http://127.0.0.1:18998/api/tasks/{ENCODED_ID}/close",
        ]

    def test_an_ordinary_id_is_left_as_it_is(self) -> None:
        client = _UrlClient()

        async def main() -> None:
            await server._close_orphan_task_best_effort(
                TASK_ID, "127.0.0.1", 18998, client=client
            )

        asyncio.run(main())

        assert client.posts == [f"http://127.0.0.1:18998/api/tasks/{TASK_ID}/close"]


class TestTheBarkLinkEncodesTheTaskId:
    @pytest.mark.parametrize(
        ("task_id", "encoded"),
        [
            ("C#-demo-1", "C%23-demo-1"),
            ("my proj-1", "my%20proj-1"),
            ("R&D-1", "R%26D-1"),
            ("a?b=c-1", "a%3Fb%3Dc-1"),
            ("我的-1", quote("我的-1", safe="")),
        ],
    )
    def test_special_characters_are_percent_encoded(
        self, task_id: str, encoded: str
    ) -> None:
        provider, session = _bark_provider("{base_url}/?task_id={task_id}")

        assert provider.send(_event(task_id=task_id, base_url=EXTERNAL)) is True

        session.post.assert_called_once()
        assert session.post.call_args.kwargs["json"]["url"] == (
            f"{EXTERNAL}/?task_id={encoded}"
        )

    def test_an_ordinary_id_is_unchanged(self) -> None:
        provider, session = _bark_provider("{base_url}/?task_id={task_id}")

        assert provider.send(_event(task_id=TASK_ID, base_url=EXTERNAL)) is True

        assert session.post.call_args.kwargs["json"]["url"] == (
            f"{EXTERNAL}/?task_id={TASK_ID}"
        )

    def test_the_base_url_is_never_encoded(self) -> None:
        provider, session = _bark_provider("{base_url}/x/{task_id}")

        assert provider.send(_event(task_id="a b", base_url=EXTERNAL)) is True

        assert session.post.call_args.kwargs["json"]["url"] == f"{EXTERNAL}/x/a%20b"

    def test_a_missing_task_id_still_renders(self) -> None:
        provider, session = _bark_provider("{base_url}/?task_id={task_id}")
        event = _event(base_url=EXTERNAL)
        event.metadata = {"base_url": EXTERNAL}

        assert provider.send(event) is True

        assert session.post.call_args.kwargs["json"]["url"] == f"{EXTERNAL}/?task_id="


WEB_SOURCES = [
    *sorted(
        p
        for p in (REPO_ROOT / "src/ai_intervention_agent/static/js").glob("*.js")
        if not p.name.endswith(".min.js")
    ),
    REPO_ROOT / "packages/vscode/webview-ui.js",
]
TEMPLATE_SITE = re.compile(r"/api/tasks/\$\{([^}]*)\}")
CONCAT_SITE = re.compile(r"""["']/api/tasks/["']\s*\+\s*([^+;,]+?)\s*[+;,]""")


def _task_url_sites(source: str) -> list[str]:
    """每处 ``/api/tasks/<id>`` 里 ID 的表达式（模板字符串和字符串拼接两种写法）。"""
    return TEMPLATE_SITE.findall(source) + CONCAT_SITE.findall(source)


class TestWebFrontendsEncodeTheTaskId:
    def test_the_scan_sees_the_known_sites(self) -> None:
        total = sum(
            len(_task_url_sites(p.read_text(encoding="utf-8"))) for p in WEB_SOURCES
        )
        assert total >= 12, "扫描规则失效：应能找到 Web UI 和 webview 里的全部站点"

    @pytest.mark.parametrize("path", WEB_SOURCES, ids=lambda p: p.name)
    def test_every_task_url_wraps_the_id_in_encode_uri_component(
        self, path: Path
    ) -> None:
        sites = _task_url_sites(path.read_text(encoding="utf-8"))

        raw = [s for s in sites if not s.strip().startswith("encodeURIComponent(")]

        assert not raw, f"{path.name} 里这些 ID 没有编码就拼进了 URL: {raw}"


def test_the_scan_rule_itself_catches_a_missing_encoding() -> None:
    bad = 'fetch(`/api/tasks/${taskId}/submit`); fetch("/api/tasks/" + id + "/x");'
    good = (
        "fetch(`/api/tasks/${encodeURIComponent(taskId)}/submit`);"
        ' fetch("/api/tasks/" + encodeURIComponent(id) + "/x");'
    )

    assert _task_url_sites(bad) == ["taskId", "id"]
    assert _task_url_sites(good) == [
        "encodeURIComponent(taskId)",
        "encodeURIComponent(id)",
    ]
