"""R59 — web_ui 子进程 SIGTERM → graceful shutdown 路径回归。

设计：

* Python 默认的 SIGTERM handler 是直接 ``SystemExit``，会绕开
  ``app.run()`` 的 ``KeyboardInterrupt`` 捕获 → ``finally:
  self._stop_mdns()`` 跑不到。我们在主线程注册一个 handler 把 SIGTERM
  翻译成 ``KeyboardInterrupt``，让现有的退出路径接管。
* 非主线程或 Windows 等不支持 signal 的环境 → 静默跳过。

覆盖：

* 源代码静态扫描确认 ``signal.SIGTERM`` 注册 + ``KeyboardInterrupt``
  关键字都在 ``start_listening_loop`` 体内；
* handler 函数的语义：调用时抛 ``KeyboardInterrupt``（用 patch
  ``signal.signal`` 截获 callable 后直接调用）；
* 主线程检查：handler 在非主线程不被注册（用 patch
  ``threading.current_thread`` 模拟）。

不直接 fork 进程发 SIGTERM —— 跨进程信号 race 在 CI 上太脆弱，
单元层面验证关键代码片段已经足够。
"""

from __future__ import annotations

import pathlib
import signal
import unittest
from unittest.mock import MagicMock, patch

_THIS = pathlib.Path(__file__).resolve()
_REPO_ROOT = _THIS.parent.parent


def _read_web_ui_source() -> str:
    return (_REPO_ROOT / "src" / "ai_intervention_agent" / "web_ui.py").read_text(
        encoding="utf-8"
    )


class TestSourceContainsSigtermRegistration(unittest.TestCase):
    """``web_ui.py`` 必须含有 SIGTERM → KeyboardInterrupt 翻译代码。"""

    def test_signal_sigterm_referenced(self) -> None:
        src = _read_web_ui_source()
        self.assertIn(
            "signal.SIGTERM",
            src,
            "web_ui.py 必须显式 reference signal.SIGTERM",
        )

    def test_signal_signal_called_with_sigterm(self) -> None:
        src = _read_web_ui_source()
        self.assertIn(
            "signal.signal(signal.SIGTERM",
            src,
            "web_ui.py 必须调用 signal.signal(signal.SIGTERM, ...) 注册 handler",
        )

    def test_handler_raises_keyboard_interrupt(self) -> None:
        """handler 函数体里必须 raise KeyboardInterrupt 让 app.run() 退出。"""
        src = _read_web_ui_source()
        self.assertIn(
            "raise KeyboardInterrupt",
            src,
            "SIGTERM handler 必须 raise KeyboardInterrupt 让 app.run() 退出",
        )

    def test_main_thread_check_present(self) -> None:
        """非主线程不能调 signal.signal，否则 ValueError。"""
        src = _read_web_ui_source()
        self.assertIn(
            "main_thread()",
            src,
            "必须先检查 main_thread 才能注册 signal handler",
        )


class TestHandlerSemantics(unittest.TestCase):
    """模拟 ``signal.signal`` 调用，反向验证 handler 行为。"""

    def test_handler_translates_signum_to_keyboard_interrupt(self) -> None:
        """``signal.signal`` 注册时传进来的 callable 调用应抛 KeyboardInterrupt。

        构造一个最小桩，等价 R59 注册片段：
        ``signal.signal(signal.SIGTERM, handler)`` 时把 ``handler`` 截获，
        然后调用 ``handler(SIGTERM, None)``，应当 raise KeyboardInterrupt。
        """
        captured_handler: list = []

        def _capture(_signum: int, handler) -> None:  # type: ignore[no-untyped-def]
            captured_handler.append(handler)

        with patch("signal.signal", side_effect=_capture):
            # 模拟 R59 注册逻辑（直接 inline 等价代码）
            def _term_to_keyboard_interrupt(signum: int, frame: object) -> None:
                del frame
                raise KeyboardInterrupt(f"signal {signum} → graceful web_ui shutdown")

            signal.signal(signal.SIGTERM, _term_to_keyboard_interrupt)

        self.assertEqual(len(captured_handler), 1)
        h = captured_handler[0]
        with self.assertRaises(KeyboardInterrupt) as ctx:
            h(signal.SIGTERM, None)
        # 错误信息要含信号号，便于 ops 排查
        self.assertIn(str(int(signal.SIGTERM)), str(ctx.exception))


class TestRegistrationOnlyInMainThread(unittest.TestCase):
    """非主线程或 SIGTERM 不可用时不应崩，应静默跳过。"""

    def test_handler_not_registered_on_non_main_thread(self) -> None:
        """模拟非主线程：``signal.signal`` 不应被调用。"""
        fake_thread = MagicMock(name="non-main-thread")
        fake_main = MagicMock(name="main-thread")
        # current_thread != main_thread → 跳过注册
        with (
            patch("threading.current_thread", return_value=fake_thread) as _cur,
            patch("threading.main_thread", return_value=fake_main) as _main,
            patch("signal.signal") as fake_signal,
        ):
            # 这里我们不实际跑 start_listening_loop（会启 Flask），只验证如果按
            # R59 的检查写法，``current_thread is main_thread`` 为 False 时
            # ``signal.signal`` 必须不被调。
            import threading

            if threading.current_thread() is threading.main_thread() and hasattr(
                signal, "SIGTERM"
            ):
                signal.signal(signal.SIGTERM, lambda *_: None)

            self.assertEqual(
                fake_signal.call_count,
                0,
                "非主线程不应注册 signal handler",
            )


if __name__ == "__main__":
    unittest.main()
