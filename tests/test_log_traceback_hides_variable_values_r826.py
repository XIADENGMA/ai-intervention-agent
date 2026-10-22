"""R826：日志里的 traceback 不能把变量的值也打出来。

现象（真实 stdio MCP 服务 + 真实通知通道，端到端复现）
====================================================

``enhanced_logging`` 给 loguru 加 stderr sink 时没有传 ``diagnose``，用的是 loguru
的默认值 ``True``：每条带 ``exc_info`` 的日志，traceback 里每一帧都会把**那一行代码里
出现的变量的值**印在下面（``│ └ NotificationEvent(id=…, message="…", …)``）。

* ``LogSanitizer`` 只处理 ``record["message"]``，traceback 是 loguru 另外渲染的，
  脱敏和“日志里只记长度不记内容”（``task.created … message_len=22``）这两条约定，
  到了 traceback 这里统统失效；
* Bark 推送遇到网络错误（离线、DNS、超时，最常见的失败）时，``logger.error(…,
  exc_info=True)`` 的 traceback 往上追溯到调用栈，把整个 ``NotificationEvent`` 的
  标题、正文（也就是 AI 给用户看的提示）和 metadata 都印了出来；
* 这些行写进 MCP 服务器的 stderr（Cursor 的 MCP 日志面板，用户提 issue 时多半整段
  贴上去）和 Web UI 子进程的 ``web_ui.log``（落盘，最大 5 MB）；
* 一次 ``port_in_use`` 的报错就是 420 行，绝大部分是这些变量转储。

契约
====

1. 带 ``exc_info`` 的日志仍然打出完整 traceback（异常类型、消息、每一帧的文件、行号、
   函数名和代码行），只是不再印变量的值；
2. 这一点由 sink 自己保证，不依赖每个调用点记得脱敏：``src/`` 里每一个 loguru
   ``add(...)`` 都必须显式写 ``diagnose=False``，以后再加 sink（比如写文件的）也一样。

测试矩阵
========

A. 真起子进程（sink 在 import 时绑定 ``sys.__stderr__``，进程内的 capture 看不到），
   在一帧里放着密钥和用户答案，经 stdlib ``logging`` 记一条带 ``exc_info`` 的错误：
   traceback 在、值不在；另一个进程里用 loguru 自己的默认 sink 记同一个异常，确实会把
   值印出来（证明这个场景有能力暴露，不是空测试；对照不能放在同一个进程里，loguru 共用
   一份 handler，对照那条日志也会走到本项目的 sink，把“traceback 还在”测成空转）；
B. 同样的检查走真实的 Bark 通道：网络错误的 traceback 里没有通知的正文；
C. 扫描 ``src/`` 下所有 loguru ``add(...)`` 调用都带 ``diagnose=False``，且至少有一个
   （防止扫描空转）。
"""

from __future__ import annotations

import ast
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = REPO_ROOT / "src" / "ai_intervention_agent"

SECRET = "TOKEN-aaaa-bbbb-cccc-1234"
ANSWER = "the user's private answer"
NOTIFICATION_TEXT = "Message body that is the user's private text"
DEVICE_KEY = "DEVKEY_s3cr3t_ABCDEF1234567890"


def _run(script: str, tmp_path: Path) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    # 子进程只该读自己 import 时的默认配置，不碰开发机上的 config.toml
    env["AI_INTERVENTION_AGENT_CONFIG_FILE"] = str(tmp_path / "config.toml")
    # 脚本要落成文件：``python -c`` 没有源文件，traceback 里既没有代码行也没有变量值，
    # 对照 sink 也就什么都看不到
    probe = tmp_path / "probe.py"
    probe.write_text(textwrap.dedent(script), encoding="utf-8")
    return subprocess.run(
        [sys.executable, str(probe)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        cwd=tmp_path,
        env=env,
        check=False,
    )


# 两个脚本走同一组调用栈（一帧里放着密钥和用户答案），只有最后“怎么记日志”不同：
# 一个用本项目的 sink（stdlib logging → ``InterceptHandler`` → loguru），一个用 loguru
# 自己的默认 sink 做对照。对照放在另一个进程里：同一个进程里的 loguru 共用一份 handler，
# 对照那条日志会同时走到本项目的 sink 上，把“traceback 还在”这一条测成空转。
_FRAMES = f"""
    SECRET = {SECRET!r}
    ANSWER = {ANSWER!r}


    def parse(value, text):
        raise ValueError("bad value")


    def handle(secret_token, answer_text):
        return parse(secret_token, answer_text)
"""

APP_SCRIPT = (
    """
    import logging

    from ai_intervention_agent import enhanced_logging  # noqa: F401  (installs the stderr sink)
"""
    + _FRAMES
    + """

    try:
        handle(SECRET, ANSWER)
    except ValueError:
        logging.getLogger("ai_intervention_agent.r826").error("handling failed", exc_info=True)
"""
)

CONTROL_SCRIPT = (
    """
    from loguru import logger  # loguru's own default sink and options
"""
    + _FRAMES
    + """

    try:
        handle(SECRET, ANSWER)
    except ValueError:
        logger.opt(exception=True).error("handling failed")
"""
)


# 模块级 fixture：pytest 9.1 不再接受实例方法形式的 class 作用域 fixture（R763 的守卫会扫）
@pytest.fixture(scope="module")
def app(tmp_path_factory: pytest.TempPathFactory) -> subprocess.CompletedProcess[str]:
    return _run(APP_SCRIPT, tmp_path_factory.mktemp("r826_app"))


@pytest.fixture(scope="module")
def control(
    tmp_path_factory: pytest.TempPathFactory,
) -> subprocess.CompletedProcess[str]:
    return _run(CONTROL_SCRIPT, tmp_path_factory.mktemp("r826_control"))


class TestTracebackKeepsTheFramesAndDropsTheValues:
    def test_both_scripts_ran(
        self,
        app: subprocess.CompletedProcess[str],
        control: subprocess.CompletedProcess[str],
    ):
        assert app.returncode == 0, app.stderr[-2000:]
        assert control.returncode == 0, control.stderr[-2000:]

    def test_loguru_with_its_defaults_prints_the_values_for_these_frames(
        self, control: subprocess.CompletedProcess[str]
    ):
        # otherwise "the values are absent" below proves nothing
        assert SECRET in control.stderr and ANSWER in control.stderr, control.stderr[
            -2000:
        ]

    def test_the_traceback_is_still_there(self, app: subprocess.CompletedProcess[str]):
        err = app.stderr
        assert "handling failed" in err
        assert "Traceback (most recent call last)" in err
        assert "ValueError: bad value" in err
        for needle in (
            "in handle",
            "in parse",
            "return parse(secret_token, answer_text)",
        ):
            assert needle in err, (
                f"{needle!r} missing from the traceback:\n{err[-2000:]}"
            )

    def test_the_values_of_the_variables_are_not(
        self, app: subprocess.CompletedProcess[str]
    ):
        err = app.stderr
        assert SECRET not in err, "a secret value reached the log through the traceback"
        assert ANSWER not in err, (
            "the user's answer reached the log through the traceback"
        )
        # the variable dump is the "│ └ <repr>" arrows loguru draws under a code line
        assert "└ " not in err and "│ " not in err, err[-2000:]


class TestRealBarkFailureDoesNotPrintTheNotification:
    SCRIPT = f"""
        import sys

        from ai_intervention_agent.notification_models import (
            NotificationEvent,
            NotificationTrigger,
            NotificationType,
        )
        from ai_intervention_agent.notification_providers import BarkNotificationProvider


        class Cfg:
            bark_enabled = True
            bark_url = "http://127.0.0.1:9/push"  # the discard port: connection refused
            bark_device_key = {DEVICE_KEY!r}
            bark_icon = ""
            bark_action = "none"
            bark_url_template = ""
            bark_timeout = 2


        provider = BarkNotificationProvider(Cfg())
        event = NotificationEvent(
            id="r826",
            title="Title",
            message={NOTIFICATION_TEXT!r},
            trigger=NotificationTrigger.IMMEDIATE,
            types=[NotificationType.BARK],
            metadata={{}},
        )
        try:
            print("SENT=" + str(provider.send(event)))
        finally:
            provider.close()
    """

    def test_the_network_error_is_logged_with_its_traceback_but_without_the_text(
        self, tmp_path: Path
    ):
        outcome = _run(self.SCRIPT, tmp_path)
        assert outcome.returncode == 0, outcome.stderr[-2000:]
        assert "SENT=False" in outcome.stdout
        err = outcome.stderr
        assert "Bark通知发送网络错误" in err
        assert "Traceback (most recent call last)" in err
        assert "httpx.ConnectError" in err
        assert NOTIFICATION_TEXT not in err, "the notification text reached the log"
        assert DEVICE_KEY not in err, "the device key reached the log"


def _loguru_aliases(tree: ast.AST) -> set[str]:
    """The names a module gives loguru's logger: ``from loguru import logger [as x]``."""
    aliases: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "loguru":
            for item in node.names:
                if item.name == "logger":
                    aliases.add(item.asname or item.name)
    return aliases


def _loguru_add_calls() -> list[tuple[Path, ast.Call]]:
    found: list[tuple[Path, ast.Call]] = []
    for path in sorted(SRC_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        aliases = _loguru_aliases(tree)
        if not aliases:
            continue
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "add"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id in aliases
            ):
                found.append((path, node))
    return found


class TestEverySinkIsDeclaredWithoutDiagnose:
    def test_the_scan_finds_the_sink(self):
        # only calls on a name bound by ``from loguru import logger`` count: ``set.add``
        # and friends are not sinks
        assert any(
            path.name == "enhanced_logging.py" for path, _ in _loguru_add_calls()
        ), "the scan no longer sees the stderr sink; fix the scan, not the contract"

    def test_every_loguru_add_passes_diagnose_false(self):
        offenders = []
        for path, call in _loguru_add_calls():
            keywords = {kw.arg: kw.value for kw in call.keywords if kw.arg}
            value = keywords.get("diagnose")
            if not (isinstance(value, ast.Constant) and value.value is False):
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{call.lineno}")
        assert not offenders, (
            "loguru sinks must pass diagnose=False (its default prints variable values, "
            "bypassing LogSanitizer): " + ", ".join(offenders)
        )
