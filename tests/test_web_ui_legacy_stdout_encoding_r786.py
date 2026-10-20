"""R786：stdout 编码装不下中文 / emoji 的环境里，Web UI 子进程照常启动。

现象（真实 stdio MCP 服务 + 真实 Web UI 子进程，端到端复现）
============================================================

MCP 服务用 ``subprocess.Popen(..., stdout=DEVNULL, stderr=<日志文件>)`` 拉起 Web UI 子进程。子进程
的 ``sys.stdout`` 仍然是一个文本流，编码取自本机语言环境：

* Windows 上重定向后的输出用 ANSI 代码页（西文 cp1252、简体中文 cp936 / GBK、日文 cp932 ……），
  不是 UTF-8；
* ``LANG=C`` 之类、Python 的 UTF-8 兜底被关掉的容器里是 ASCII。

``WebFeedbackUI.run()`` 在真正 ``app.run()`` 之前用 ``print`` 输出一串中文提示（``Web反馈界面已启动``、
``监听地址``……），其中还有 emoji（``🔄 页面将保持打开``）。``sys.stdout`` 的错误处理是 ``strict``，
编码不了就抛 ``UnicodeEncodeError``，子进程在**服务器启动之前**就退出了。MCP 一侧看到的只是健康检查
一直不通过，15 秒后报"Web 服务启动超时，请检查端口是否被占用"，端口其实是空的；
回给调用方的是兜底的重调提示，任务根本没建出来。

用 ``PYTHONIOENCODING`` 在 macOS 上模拟这几种编码，跑真实的 MCP 服务和 Web UI：

====================================  ===========================================  ==============
子进程 stdout 编码                    子进程的 traceback                           调用结果
====================================  ===========================================  ==============
cp936（简体中文 Windows）             ``print("🔄 页面将保持…")`` 抛 UnicodeEncodeError   15 秒后失败
cp1252（西文 Windows）                第一句 ``print("\\nWeb反馈界面已启动")`` 就抛        15 秒后失败
ASCII（``LC_ALL=C PYTHONUTF8=0``）    同上                                          15 秒后失败
====================================  ===========================================  ==============

仓库的 CI 只有 Linux 和 macOS，开发机上 stdout 是 UTF-8，所以一直没暴露。

同一个原因还让 ``ai-intervention-agent --print-config`` 在管道或重定向后失败：文档里的用法是
``ai-intervention-agent --print-config | jq``，输出用 ``json.dumps(..., ensure_ascii=False)``，默认配置里
有中文（``resubmit_prompt`` 等），stdout 是 cp1252 / ASCII 时抛 ``UnicodeEncodeError``，一个字节都没输出
（实测 exit 1、stdout 0 字节）。

修复
====

三处，各管一种情况：

1. MCP 服务拉起子进程时，给它的环境加 ``PYTHONIOENCODING=utf-8:backslashreplace``：子进程的
   标准输出 / 错误一律是 UTF-8，且任何字符都不会让 ``print`` 抛异常；它的 stderr 写进的日志文件
   本来就是 UTF-8（父进程用 ``encoding="utf-8"`` 打开的），这一来内容和编码也一致了（以前 Windows 上
   子进程按 ANSI 代码页写，日志文件里是两种编码混在一起）；
2. ``WebFeedbackUI.run()`` 开头把 ``sys.stdout`` / ``sys.stderr`` 的错误处理改成 ``backslashreplace``：
   不经过上面的启动器、直接在编码受限的终端里运行（``python -m ai_intervention_agent.web_ui > out.txt``）时，
   打印不出来的字符显示成转义序列，而不是让进程崩掉。提示只是给人看的，不该决定服务器起不起得来；
3. ``--print-config`` 先看 stdout 的编码写不写得下这段 JSON：写得下就保持中文原样（UTF-8 终端里
   可读），写不下就改用 ``\\uXXXX`` 转义——转义后仍是合法 JSON，``jq`` 照样能读。

测试矩阵
========

A. 启动器给子进程的环境带 ``PYTHONIOENCODING``，其余环境变量原样继承，``os.environ`` 本身不被改；
B. ``run()`` 在只认 ASCII 的 strict 标准输出下不抛异常，提示以转义序列的形式写出；
C. 真实的子进程：stdout 重定向到 ``DEVNULL``（和启动器一样），``PYTHONIOENCODING`` 分别是 cp936、cp1252、
   ascii，``run()`` 正常返回、stderr 里没有 traceback；
D. ``--print-config``：cp1252 / ASCII 的 stdout 下输出是合法 JSON，中文默认值解码后还在；UTF-8 的 stdout
   下中文保持原样、不被转义。

A、B、C 和 D 的前两条在旧代码上失败（cp936 失败在 emoji 那一行，其余失败在第一行或 ``print`` 那一行）；
D 的第三条（UTF-8）新旧代码都通过，用来保证没有把可读的输出变成转义。
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import textwrap
import threading
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from ai_intervention_agent import service_manager, web_ui
from ai_intervention_agent.server_config import WebUIConfig

SCRIPT_DIR = Path(service_manager.__file__).resolve().parent


class _Spawn:
    def __init__(self) -> None:
        self.calls: list[tuple[list[str], dict[str, Any]]] = []

    def health(self, config: Any) -> bool:
        return bool(self.calls)

    def popen(self, args: list[str], **kwargs: Any) -> MagicMock:
        self.calls.append((args, kwargs))
        process = MagicMock()
        process.pid = 4242
        process.poll.return_value = None
        return process


@pytest.fixture
def spawn() -> Any:
    state = _Spawn()
    service_manager.ServiceManager._instance = None
    service_manager.ServiceManager._lock = threading.Lock()
    with (
        patch.object(service_manager, "NOTIFICATION_AVAILABLE", False),
        patch.object(service_manager, "health_check_service", state.health),
        patch.object(service_manager, "_is_port_available", lambda host, port: True),
        patch.object(service_manager.subprocess, "Popen", state.popen),
        patch.object(service_manager, "_get_web_ui_log_path", return_value=None),
    ):
        yield state
    service_manager.ServiceManager._instance = None


class TestTheLauncher:
    def test_the_child_gets_a_utf8_stdout_that_never_raises(
        self, spawn: _Spawn
    ) -> None:
        service_manager.start_web_service(
            WebUIConfig(host="127.0.0.1", port=18999), SCRIPT_DIR
        )

        assert len(spawn.calls) == 1
        env = spawn.calls[0][1]["env"]
        assert env["PYTHONIOENCODING"] == "utf-8:backslashreplace"

    def test_the_rest_of_the_environment_is_inherited(
        self, spawn: _Spawn, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("AIIA_R786_MARKER", "kept")
        monkeypatch.setenv("PYTHONIOENCODING", "latin-1")

        service_manager.start_web_service(
            WebUIConfig(host="127.0.0.1", port=18999), SCRIPT_DIR
        )

        env = spawn.calls[0][1]["env"]
        assert env["AIIA_R786_MARKER"] == "kept"
        assert env["PATH"] == os.environ["PATH"]
        # 这个进程自己的环境不被改
        assert os.environ["PYTHONIOENCODING"] == "latin-1"


def _quiet_ui(monkeypatch: pytest.MonkeyPatch) -> web_ui.WebFeedbackUI:
    ui = web_ui.WebFeedbackUI("hello", host="127.0.0.1", port=18999)
    monkeypatch.setattr(ui.app, "run", lambda **kwargs: None)
    monkeypatch.setattr(ui, "_start_mdns_if_needed", lambda: None)
    return ui


class TestRunUnderAnAsciiStdout:
    def test_it_does_not_raise_and_writes_escapes(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        raw = io.BytesIO()
        strict = io.TextIOWrapper(raw, encoding="ascii", errors="strict")
        monkeypatch.setattr(sys, "stdout", strict)
        monkeypatch.setattr(web_ui.signal, "signal", lambda *args, **kwargs: None)

        _quiet_ui(monkeypatch).run()

        strict.flush()
        written = raw.getvalue().decode("ascii")
        assert "Web" in written
        # 中文以转义序列的形式写出，emoji 也是
        assert "\\u53cd\\u9988" in written
        assert "\\U0001f504" in written


CHILD = textwrap.dedent(
    """
    import signal
    from ai_intervention_agent import web_ui

    signal.signal = lambda *args, **kwargs: None
    ui = web_ui.WebFeedbackUI("hello", host="127.0.0.1", port=18999)
    ui.app.run = lambda **kwargs: None
    ui._start_mdns_if_needed = lambda: None
    ui.run()
    """
)


@pytest.mark.parametrize("encoding", ["cp936", "cp1252", "ascii"])
def test_a_real_child_with_a_legacy_stdout_starts(
    encoding: str, tmp_path: Path
) -> None:
    env = {
        **os.environ,
        "PYTHONIOENCODING": encoding,
        "AI_INTERVENTION_AGENT_CONFIG_FILE": str(tmp_path / "config.toml"),
    }

    done = subprocess.run(
        [sys.executable, "-c", CHILD],
        env=env,
        cwd=tmp_path,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        timeout=120,
        check=False,
    )

    assert b"Traceback" not in done.stderr, done.stderr.decode("ascii", "replace")
    assert done.returncode == 0


PRINT_CONFIG = (
    "import sys; from ai_intervention_agent.server import main; "
    "main(['--print-config'])"
)


def _print_config(
    tmp_path: Path, **extra_env: str
) -> subprocess.CompletedProcess[bytes]:
    env = {
        **os.environ,
        "AI_INTERVENTION_AGENT_CONFIG_FILE": str(tmp_path / "config.toml"),
        **extra_env,
    }
    return subprocess.run(
        [sys.executable, "-c", PRINT_CONFIG],
        env=env,
        cwd=tmp_path,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        timeout=120,
        check=False,
    )


class TestPrintConfig:
    """``--print-config | jq``：stdout 编码装不下中文时输出仍是合法 JSON。"""

    @pytest.mark.parametrize("encoding", ["cp1252", "ascii"])
    def test_the_output_is_valid_json_under_a_legacy_stdout(
        self, encoding: str, tmp_path: Path
    ) -> None:
        done = _print_config(tmp_path, PYTHONIOENCODING=encoding)

        assert done.returncode == 0, done.stderr.decode("ascii", "replace")
        payload = json.loads(done.stdout.decode(encoding))
        assert "请立即调用" in payload["sections"]["feedback"]["resubmit_prompt"]

    def test_a_utf8_stdout_keeps_the_chinese_readable(self, tmp_path: Path) -> None:
        done = _print_config(tmp_path, PYTHONIOENCODING="utf-8")

        assert done.returncode == 0, done.stderr.decode("utf-8", "replace")
        text = done.stdout.decode("utf-8")
        assert "请立即调用" in text
        assert "\\u8bf7" not in text
