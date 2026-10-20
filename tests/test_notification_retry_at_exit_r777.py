"""R777：进程退出时重试定时器恰好触发，不能再打 ERROR 加整段 traceback。

现象
====

发送失败的通知会用 ``threading.Timer`` 排一次重试（``retry_delay`` 秒之后）。进程
正好在这段时间里退出——MCP 客户端关闭、IDE 关窗口都会——定时器线程是 daemon，退出
流程里它还活着，到点就去跑 ``_process_event``，``self._executor.submit`` 抛出
``RuntimeError: cannot schedule new futures after shutdown``，日志里是：

    ERROR   处理通知事件失败: <id> - cannot schedule new futures after shutdown
    Traceback (most recent call last): ...（整段，十几帧）
    WARNING 处理通知事件异常，将在 2s 后重试 (2/3)
    WARNING 处理通知事件异常，将在 2s 后重试 (3/3)

线程池明明没有被 ``NotificationManager.shutdown()`` 关过：R114 的二次确认
（``_shutdown_called`` 为真才静默）认不出这一种。原因在 CPython：退出时先跑
``threading._shutdown``，它的 ``concurrent.futures.thread._python_exit`` 叫醒所有
线程池的 worker，worker 发现解释器在退出，就把各自的 ``executor._shutdown`` 标成
``True``；``NotificationManager.shutdown()`` 挂在 ``atexit`` 上，要等 ``threading``
那一步结束之后才跑，这一段（MCP 服务里是终止 Web UI 子进程的 100 多毫秒，还有 Bark
在途请求的 join 时间）``_shutdown_called`` 仍是 ``False``。

真实 stdio MCP 服务 + Bark 一直不应答的复现里，退出时看到了上面这组日志。

修复
====

``_process_event`` 的 ``submit`` 被拒绝、``_shutdown_called`` 为假时，再问一句
``_interpreter_is_exiting()``：``threading._shutdown`` 会把主线程标成已结束，
``threading.main_thread().is_alive()`` 为 ``False`` 就是退出流程已经开始。是的话和
R114 一样静默跳过（DEBUG，带 ``[R777]`` 标记），不进外层 ``except``，也就不再排重试。
应用还在正常运行时线程池被人关掉（主线程活着、``_shutdown_called`` 为假）仍然是
ERROR——R114 的反向防御不能丢。

测试矩阵
========

A. 退出流程里 ``submit`` 被拒绝：静默跳过，没有 ERROR / WARNING，没有排重试；
B. 同样的拒绝发生在应用正常运行时：仍然是 ERROR 加 ``处理通知事件失败``；
C. ``_interpreter_is_exiting()`` 跟着主线程的存活状态走；
D. 真实解释器退出：子进程里让重试定时器恰好在 ``atexit`` 阶段触发，stderr 里没有
   ``处理通知事件失败`` / ``Traceback`` / ``cannot schedule new futures``，并且
   ``atexit`` 阶段里 ``threading.main_thread().is_alive()`` 确实是 ``False``（这个
   判断依据本身的前提）。

A、D 在旧代码上失败。
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import textwrap
import threading
import unittest
from unittest.mock import MagicMock, patch

from ai_intervention_agent import notification_manager as nm_module
from ai_intervention_agent.notification_manager import NotificationType
from tests.test_notification_shutdown_race_r114 import _make_event, _make_manager

_LOGGER_NAME = "ai_intervention_agent.notification_manager"


class TestAnExecutorFlaggedByTheInterpreter(unittest.TestCase):
    def setUp(self) -> None:
        self.mgr = _make_manager()
        provider = MagicMock()
        provider.send.return_value = True
        self.mgr.register_provider(NotificationType.WEB, provider)
        # What CPython's worker does at interpreter exit: the executor is closed,
        # NotificationManager.shutdown() has not been called.
        self.mgr._executor.shutdown(wait=False)
        self.assertFalse(self.mgr._shutdown_called)

    def tearDown(self) -> None:
        try:
            self.mgr.shutdown(wait=True)
        except Exception:
            pass

    def test_a_refused_submit_while_exiting_is_skipped_quietly(self) -> None:
        event = _make_event(id="r777_exiting", max_retries=3)

        with (
            patch.object(nm_module, "_interpreter_is_exiting", return_value=True),
            self.assertLogs(_LOGGER_NAME, level="DEBUG") as logs,
        ):
            self.mgr._process_event(event)

        self.assertTrue(
            any("[R777]" in line for line in logs.output),
            f"the skip should leave a DEBUG line: {logs.output}",
        )
        loud = [line for line in logs.output if line.startswith(("ERROR", "WARNING"))]
        self.assertEqual(loud, [], "exit-time skip must not log ERROR or WARNING")
        self.assertEqual(event.retry_count, 0, "no retry may be counted")
        self.assertEqual(self.mgr._delayed_timers, {}, "no retry may be scheduled")

    def test_the_same_refusal_while_the_app_runs_is_still_an_error(self) -> None:
        event = _make_event(id="r777_running", max_retries=0)

        with self.assertLogs(_LOGGER_NAME, level="ERROR") as logs:
            self.mgr._process_event(event)

        self.assertTrue(
            any("处理通知事件失败" in line for line in logs.output),
            f"a closed pool while the app runs must stay visible: {logs.output}",
        )


class TestTheExitProbe(unittest.TestCase):
    def test_it_is_false_while_the_program_runs(self) -> None:
        self.assertFalse(nm_module._interpreter_is_exiting())

    def test_it_follows_the_main_thread(self) -> None:
        main = MagicMock()
        main.is_alive.return_value = False
        with patch.object(threading, "main_thread", return_value=main):
            self.assertTrue(nm_module._interpreter_is_exiting())
        main.is_alive.return_value = True
        with patch.object(threading, "main_thread", return_value=main):
            self.assertFalse(nm_module._interpreter_is_exiting())


_CHILD = textwrap.dedent(
    """
    import atexit
    import logging
    import sys
    import threading
    import time

    logging.basicConfig(
        level=logging.DEBUG,
        stream=sys.stderr,
        format="%(levelname)s %(name)s %(message)s",
    )

    from ai_intervention_agent.notification_manager import (
        NotificationTrigger,
        NotificationType,
        notification_manager as manager,
    )


    class AlwaysFails:
        def send(self, *args, **kwargs):
            return False


    manager.config.enabled = True
    manager.config.retry_delay = 1
    manager.config.retry_count = 3
    manager.config.fallback_enabled = False
    manager.register_provider(NotificationType.SOUND, AlwaysFails())
    manager.send_notification(
        title="t",
        message="m",
        trigger=NotificationTrigger.IMMEDIATE,
        types=[NotificationType.SOUND],
        skip_unavailable=False,
    )


    def hold_the_exit_window_open():
        # atexit handlers run after threading._shutdown() has flagged the executors
        # and before NotificationManager.shutdown() (registered earlier, so it runs later).
        print("main thread alive in atexit:", threading.main_thread().is_alive(), flush=True)
        time.sleep(2.5)


    atexit.register(hold_the_exit_window_open)
    """
)


class TestARealInterpreterExit(unittest.TestCase):
    def test_a_retry_firing_while_the_process_exits_makes_no_noise(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            env = {
                **os.environ,
                "HOME": home,
                "XDG_CONFIG_HOME": os.path.join(home, ".config"),
                "AI_INTERVENTION_AGENT_CONFIG_FILE": os.path.join(home, "config.toml"),
                "PYTHONDONTWRITEBYTECODE": "1",
            }
            proc = subprocess.run(
                [sys.executable, "-c", _CHILD],
                cwd=home,
                env=env,
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )

        self.assertEqual(proc.returncode, 0, proc.stderr[-3000:])
        self.assertIn("main thread alive in atexit: False", proc.stdout)
        # The R777 DEBUG line quotes the executor's message, so look for what the
        # old code produced: an ERROR record and its traceback.
        errors = [
            line
            for line in proc.stderr.splitlines()
            if line.startswith("ERROR") or " - ERROR - " in line
        ]
        self.assertEqual(errors, [], proc.stderr[-3000:])
        self.assertNotIn("Traceback", proc.stderr, proc.stderr[-3000:])
        self.assertNotIn("处理通知事件失败", proc.stderr, proc.stderr[-3000:])


if __name__ == "__main__":
    unittest.main()
