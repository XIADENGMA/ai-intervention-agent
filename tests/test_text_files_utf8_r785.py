"""R785：包里读写文本文件一律显式用 UTF-8，不跟本机的语言环境走。

现象
====

``NotificationManager`` 把"还没投递完的通知"写进配置目录下的 ``notification_inflight.json``
（R136，进程被杀后下次启动能看到上次丢了几条）。写文件这一行是::

    tmp.write_text(json.dumps(payload, ensure_ascii=False, separators=...))

``write_text`` 没有传 ``encoding``，用的是本机语言环境的编码；而 ``json.dumps(ensure_ascii=False)``
把中文原样交给它。读的一侧（``_load_persisted_inflight_events``）明确用 UTF-8。两边一错开：

* 西文 Windows（cp1252）、``LANG=C`` 的容器、老 Linux 区域设置：``write_text`` 抛
  ``UnicodeEncodeError``，被外层 ``except Exception`` 吞成一条 DEBUG 日志——持久化悄悄没做；
* 中文 Windows（GBK）：写出的是 GBK 字节，读的一侧按 UTF-8 解码失败（``UnicodeDecodeError`` 不是
  ``OSError``，没被 ``except OSError`` 接住，只靠调用方最外层的 ``except Exception`` 兜底）——
  文件在、内容却读不回来。

两种情况下"上次重启时有几条通知没发出去"都看不到了，而这个项目的通知标题和正文大多是中文。
macOS 和 UTF-8 的 Linux 上不会触发，所以开发机和 CI 都看不出来。

修复
====

写文件时显式传 ``encoding="utf-8"``，和读的一侧、和包里其余所有文本文件的读写一致。

另加一条源码扫描：包里每个文本模式的 ``open`` / ``Path.open`` / ``os.fdopen`` /
``read_text`` / ``write_text`` / ``subprocess(text=True)`` 都必须写明 ``encoding``。以后再有人漏掉，
在 macOS 上也会被测试抓到，不用等 Windows 用户报问题。

测试
====

* 用 ``LC_ALL=C PYTHONUTF8=0 PYTHONCOERCECLOCALE=0`` 起一个子进程，让 ``locale`` 编码变成 ASCII
  （任何 POSIX 系统都有 C 区域设置），带中文的事件照常落盘、读得回来、字节是合法的 UTF-8；
* 源码扫描（和它的自检）。
"""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

PACKAGE = Path(__file__).resolve().parent.parent / "src" / "ai_intervention_agent"

TEXT_IO_NAMES = {"open", "fdopen", "read_text", "write_text"}
SUBPROCESS_NAMES = {"run", "Popen", "check_output", "check_call", "call"}

CHILD = textwrap.dedent(
    """
    import json, locale, sys
    from pathlib import Path
    from unittest.mock import patch

    folder = Path(sys.argv[1])
    from ai_intervention_agent import notification_manager as nm
    from ai_intervention_agent.notification_models import (
        NotificationEvent, NotificationPriority, NotificationTrigger, NotificationType,
    )

    with patch.object(nm, "_get_inflight_file_dir", return_value=folder):
        manager = nm.NotificationManager()
        manager._inflight_persisted_ids = set()
        event = NotificationEvent(
            id="evt-r785",
            title="新任务：请确认",
            message="是否继续执行？（选项：继续 / 取消）",
            trigger=NotificationTrigger.IMMEDIATE,
            types=[NotificationType.WEB],
            max_retries=3,
            priority=NotificationPriority.NORMAL,
        )
        with manager._queue_lock:
            manager._event_queue.append(event)
        manager._track_event_inflight(event)
        loaded = manager._load_persisted_inflight_events()
        manager.shutdown()

    print(json.dumps({
        "encoding": locale.getpreferredencoding(False),
        "loaded": loaded,
    }, ensure_ascii=True))
    """
)


def run_child(folder: Path) -> dict:
    config = folder / "config.toml"
    env = {
        **os.environ,
        "LC_ALL": "C",
        "PYTHONUTF8": "0",
        "PYTHONCOERCECLOCALE": "0",
        "AI_INTERVENTION_AGENT_CONFIG_FILE": str(config),
    }
    env.pop("LANG", None)
    done = subprocess.run(
        [sys.executable, "-c", CHILD, str(folder)],
        env=env,
        cwd=folder,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        check=True,
    )
    return json.loads(done.stdout.strip().splitlines()[-1])


class TestTheInflightFileUnderAnAsciiLocale:
    def test_a_chinese_event_is_persisted_and_read_back(self, tmp_path: Path) -> None:
        result = run_child(tmp_path)
        if result["encoding"].lower().replace("-", "").replace("_", "") in {
            "utf8",
            "cp65001",
        }:
            pytest.skip("this platform ignores LC_ALL: the locale encoding is UTF-8")

        loaded = result["loaded"]
        assert [entry["id"] for entry in loaded] == ["evt-r785"]
        assert loaded[0]["title"] == "新任务：请确认"
        assert loaded[0]["message"] == "是否继续执行？（选项：继续 / 取消）"

    def test_the_file_on_disk_is_valid_utf8(self, tmp_path: Path) -> None:
        run_child(tmp_path)

        # 子进程退出前 shutdown 不会删文件；事件还在"未完成"集合里
        raw = (tmp_path / "notification_inflight.json").read_bytes()
        assert "新任务：请确认" in raw.decode("utf-8")


MODULES_WITH_OPEN = {"io", "gzip", "bz2", "lzma", "codecs", "os"}


def _call_name(func: ast.expr) -> str | None:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _mode_of(node: ast.Call) -> str | None:
    """``open`` 类调用写明的模式；没写（或不是字面量）时返回 ``None``，按默认的文本模式算。"""
    for keyword in node.keywords:
        if keyword.arg == "mode" and isinstance(keyword.value, ast.Constant):
            return str(keyword.value.value)
    func = node.func
    is_path_method = (
        isinstance(func, ast.Attribute)
        and func.attr == "open"
        and not (
            isinstance(func.value, ast.Name) and func.value.id in MODULES_WITH_OPEN
        )
    )
    index = 0 if is_path_method else 1
    if len(node.args) > index:
        argument = node.args[index]
        if isinstance(argument, ast.Constant):
            return str(argument.value)
    return None


def undeclared_text_io(source: str) -> list[tuple[int, str]]:
    """没有写 ``encoding`` 的文本 I/O 调用点：``[(行号, 描述)]``。"""
    found: list[tuple[int, str]] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = _call_name(func)
        keywords = {keyword.arg for keyword in node.keywords}
        if name in {"read_text", "write_text"}:
            if "encoding" not in keywords:
                found.append((node.lineno, f"{name}() without encoding"))
        elif name in {"open", "fdopen"}:
            # os.open(path, flags) 是底层文件描述符，不是文本文件
            if (
                name == "open"
                and isinstance(func, ast.Attribute)
                and isinstance(func.value, ast.Name)
                and func.value.id == "os"
            ):
                continue
            mode = _mode_of(node)
            if mode is not None and "b" in mode:
                continue
            if "encoding" not in keywords:
                found.append((node.lineno, f"{name}(mode={mode!r}) without encoding"))
        elif (
            name in SUBPROCESS_NAMES
            and keywords & {"text", "universal_newlines"}
            and "encoding" not in keywords
        ):
            found.append(
                (node.lineno, f"subprocess {name}(text=True) without encoding")
            )
    return found


class TestNoTextFileFollowsTheLocale:
    def test_every_text_io_call_in_the_package_names_an_encoding(self) -> None:
        offenders = {}
        for path in sorted(PACKAGE.rglob("*.py")):
            found = undeclared_text_io(path.read_text(encoding="utf-8"))
            if found:
                offenders[str(path.relative_to(PACKAGE))] = found

        assert offenders == {}

    def test_the_scan_catches_what_it_is_meant_to_catch(self) -> None:
        source = textwrap.dedent(
            """
            from pathlib import Path
            import os, subprocess

            Path("a").write_text("x")                    # caught
            Path("a").read_text()                        # caught
            open("a")                                    # caught
            open("a", "w")                               # caught
            Path("a").open("w")                          # caught
            os.fdopen(1, "w")                            # caught
            subprocess.run(["x"], text=True)             # caught

            Path("a").write_text("x", encoding="utf-8")
            open("a", encoding="utf-8")
            open("a", "rb")
            Path("a").open("wb")
            os.open("a", os.O_RDONLY)
            subprocess.run(["x"], capture_output=True)
            """
        )

        expected = [
            number
            for number, line in enumerate(source.splitlines(), start=1)
            if line.rstrip().endswith("# caught")
        ]
        assert len(expected) == 7
        assert sorted(line for line, _ in undeclared_text_io(source)) == expected
