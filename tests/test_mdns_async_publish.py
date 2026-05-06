"""R20.11 mDNS 异步发布锁定测试

背景
----
``WebFeedbackUI.run()`` 中原本同步调用 ``_start_mdns_if_needed()``，其内部
``zeroconf.register_service`` 因 RFC 6762 §8 要求的 conflict-probe announcement
而**同步阻塞 ~1.7 s**（多次 250 ms multicast probe）。这把 ``app.run()`` 进入
listen 状态延迟了 ~1.7 s——浏览器/插件第一次访问 Web UI 需要等近 2 秒才有响应。

实测（``subprocess.Popen([python, '-u', web_ui.py, ...])`` 到 socket 可连接）：

* R20.10 baseline：1922 ms
* R20.11 中位数：203 ms（5 次：196.5 / 222.9 / 194.7 / 223.6 / 203.3）
* **改进：-1718 ms / -89.4%**

R20.11 实施：``run()`` 启动后台 daemon 线程跑 ``_start_mdns_if_needed``，
``app.run()`` 立即进入 listen；``_stop_mdns`` 在 finally 块中 ``join`` 线程，
防止 daemon 在主进程结束时 race 写入 ``_mdns_zeroconf``。``_start_mdns_if_needed``
方法本身**保持同步语义**——所有现有 26+ 直接测试调用该方法的单元测试无需修改。

本测试套件锁定 4 条不变量：

1. **生命周期管理**
   - ``_mdns_thread`` 属性在 ``__init__`` 后是 ``None``
   - ``run()`` 启动线程前 ``_mdns_thread`` is None
   - ``_stop_mdns`` 在 thread 仍存活时调用 ``join(timeout=2.0)``
   - ``_stop_mdns`` 后 ``_mdns_thread`` 被清理为 ``None``

2. **行为正确性**
   - daemon 线程完成后 ``_mdns_zeroconf`` 被正确设置
   - 现有 ``_start_mdns_if_needed`` 同步契约保留（直接调用仍按原方式工作）
   - ``_stop_mdns`` 在 thread join 失败时不抛异常

3. **源文本不变量**
   - ``run()`` 中必须用 ``threading.Thread(target=self._start_mdns_if_needed)``
     而不是直接 ``self._start_mdns_if_needed()``
   - thread 必须设置 ``daemon=True`` 防止 hang shutdown
   - thread 必须有命名（便于诊断）

4. **集成测试（subprocess-isolated 端到端）**
   - 完整 ``subprocess.Popen([python, '-u', web_ui.py])`` 到 socket
     可连接的 wall time 最佳采样必须 < 1200 ms（R20.11 本地中位数约 200 ms；
     GitHub Actions + coverage 曾实测到 ~1201 ms 的单次 runner 抖动。1200 ms
     仍显著低于 R20.10 同步 mDNS baseline 1922 ms，最多两次采样能抓住“又
     同步化”的回归，同时避免单次冷启动抖动误报）
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent


# ═══════════════════════════════════════════════════════════════════════════
# 1. 生命周期管理：_mdns_thread 属性的初始化、启动、停止
# ═══════════════════════════════════════════════════════════════════════════
class TestMdnsThreadLifecycle(unittest.TestCase):
    """daemon thread 在 __init__ / run() / _stop_mdns 三阶段的状态转换"""

    def setUp(self) -> None:
        from web_ui import WebFeedbackUI

        self.ui = WebFeedbackUI(
            prompt="lifecycle-test",
            task_id="lifecycle-test",
            port=18931,
        )

    def test_mdns_thread_attr_is_none_after_init(self) -> None:
        """__init__ 后 _mdns_thread 必须是 None（lifecycle 起点）"""
        self.assertIsNone(
            self.ui._mdns_thread,
            "_mdns_thread 在 __init__ 后必须是 None；如果 init 期间就启动 thread，"
            "WebFeedbackUI 实例化会变成 1.7s 操作，破坏现有 5+ 测试的实例化期望",
        )

    def test_mdns_thread_attribute_exists(self) -> None:
        """_mdns_thread 必须是显式声明的实例属性（not 仅 TYPE_CHECKING）"""
        self.assertTrue(
            hasattr(self.ui, "_mdns_thread"),
            "_mdns_thread 必须是真实的实例属性（在 __init__ 中赋值）；"
            "没有这个属性，_stop_mdns 中的 getattr 会返回 None 但 hasattr 测试会失败",
        )

    def test_stop_mdns_clears_thread_attribute(self) -> None:
        """_stop_mdns 必须把 _mdns_thread 清理为 None（防止下次 run() 看到旧 thread）"""
        # 模拟 thread 存在但已完成
        mock_thread = MagicMock(spec=threading.Thread)
        mock_thread.is_alive.return_value = False
        self.ui._mdns_thread = mock_thread

        self.ui._stop_mdns()

        self.assertIsNone(
            self.ui._mdns_thread,
            "_stop_mdns 必须把 _mdns_thread 设回 None，否则下次 run() 启动新线程"
            "时旧引用还在",
        )

    def test_stop_mdns_joins_running_thread_with_timeout(self) -> None:
        """_stop_mdns 在 thread.is_alive 时必须调用 join(timeout=...)"""
        mock_thread = MagicMock(spec=threading.Thread)
        mock_thread.is_alive.return_value = True
        self.ui._mdns_thread = mock_thread

        self.ui._stop_mdns()

        mock_thread.join.assert_called_once()
        # 必须传 timeout，否则 daemon thread 在 conflict-probe 卡住时会 hang shutdown
        call_kwargs = mock_thread.join.call_args.kwargs
        call_args = mock_thread.join.call_args.args
        raw_timeout = call_kwargs.get("timeout") or (
            call_args[0] if call_args else None
        )
        self.assertIsNotNone(
            raw_timeout,
            "_stop_mdns 调用 thread.join 必须传 timeout，否则 daemon thread"
            "在 mDNS conflict-probe 卡住时会让 Web UI shutdown hang 任意长时间",
        )
        # ty 类型收紧：上面 assertIsNotNone 后已经知道非 None
        timeout_value = float(raw_timeout)  # ty: ignore[invalid-argument-type]
        self.assertGreater(timeout_value, 0.0, "join timeout 必须 > 0")
        self.assertLessEqual(
            timeout_value,
            5.0,
            "join timeout 必须合理（≤ 5s）；过长会让用户体验到 shutdown hang",
        )

    def test_stop_mdns_skips_join_when_thread_not_alive(self) -> None:
        """thread 已结束时不应调用 join（节省调用开销）"""
        mock_thread = MagicMock(spec=threading.Thread)
        mock_thread.is_alive.return_value = False
        self.ui._mdns_thread = mock_thread

        self.ui._stop_mdns()

        mock_thread.join.assert_not_called()

    def test_stop_mdns_swallows_join_exception(self) -> None:
        """thread.join 抛异常不应让 _stop_mdns 失败（上下文是 finally 块）"""
        mock_thread = MagicMock(spec=threading.Thread)
        mock_thread.is_alive.return_value = True
        mock_thread.join.side_effect = RuntimeError("join failed")
        self.ui._mdns_thread = mock_thread

        # 不应抛
        try:
            self.ui._stop_mdns()
        except RuntimeError as e:
            self.fail(
                f"_stop_mdns 不能让 thread.join 异常逃逸（上下文是 finally 块）: {e}"
            )

    def test_stop_mdns_handles_missing_thread_attr(self) -> None:
        """如果 _mdns_thread 属性不存在（旧实例 / 反序列化），不应抛 AttributeError"""
        if hasattr(self.ui, "_mdns_thread"):
            delattr(self.ui, "_mdns_thread")

        try:
            self.ui._stop_mdns()
        except AttributeError as e:
            self.fail(
                f"_stop_mdns 必须用 getattr(self, '_mdns_thread', None) 兼容缺失属性: {e}"
            )


# ═══════════════════════════════════════════════════════════════════════════
# 2. 行为正确性：异步 register 完成后状态正确
# ═══════════════════════════════════════════════════════════════════════════
class TestAsyncMdnsRegisterBehavior(unittest.TestCase):
    """异步线程内执行 _start_mdns_if_needed 应与同步执行行为一致"""

    def setUp(self) -> None:
        from web_ui import WebFeedbackUI

        self.ui = WebFeedbackUI(
            prompt="behavior-test",
            task_id="behavior-test",
            port=18932,
        )
        self.ui.host = "0.0.0.0"
        self.ui._mdns_zeroconf = None

    def test_sync_call_to_start_mdns_still_works(self) -> None:
        """直接调用 _start_mdns_if_needed（同步契约）必须仍可工作

        现有 26+ 测试直接调用 self.ui._start_mdns_if_needed() 并立即 assert
        _mdns_zeroconf 状态——R20.11 不能破坏这个 contract。
        """
        # 通过 _get_mdns_config 返回 enabled=False 跳过实际 register（不依赖 zeroconf 库）
        with patch.object(self.ui, "_get_mdns_config", return_value={"enabled": False}):
            self.ui._start_mdns_if_needed()
            self.assertIsNone(
                self.ui._mdns_zeroconf,
                "同步调用契约：_start_mdns_if_needed 在 enabled=False 时立即返回",
            )

    def test_async_thread_target_is_start_mdns_method(self) -> None:
        """daemon thread 的 target 必须是 self._start_mdns_if_needed（不是其他闭包）"""
        # 通过 patch _start_mdns_if_needed 验证 thread 里调到了它
        called = threading.Event()
        original = self.ui._start_mdns_if_needed

        def patched_start_mdns():
            called.set()
            return original()

        with patch.object(self.ui, "_get_mdns_config", return_value={"enabled": False}):
            with patch.object(
                self.ui, "_start_mdns_if_needed", side_effect=patched_start_mdns
            ):
                # 模拟 run() 启动 thread 的行为
                self.ui._mdns_thread = threading.Thread(
                    target=self.ui._start_mdns_if_needed,
                    name="ai-agent-mdns-register",
                    daemon=True,
                )
                self.ui._mdns_thread.start()
                self.assertTrue(
                    called.wait(timeout=3.0),
                    "daemon thread 必须真正调到 _start_mdns_if_needed",
                )
                self.ui._mdns_thread.join(timeout=2.0)


# ═══════════════════════════════════════════════════════════════════════════
# 3. 源文本不变量：run() 必须用 Thread + daemon=True，禁止直接同步调用
# ═══════════════════════════════════════════════════════════════════════════
class TestSourceTextInvariants(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.web_ui_src = (PROJECT_ROOT / "web_ui.py").read_text(encoding="utf-8")
        cls.mdns_src = (PROJECT_ROOT / "web_ui_mdns.py").read_text(encoding="utf-8")

    def test_run_uses_thread_for_mdns(self) -> None:
        """run() 中必须用 Thread 异步发布 mDNS，禁止裸调用 _start_mdns_if_needed()"""
        # 找到 run() 函数体
        marker = "def run(self) -> FeedbackResult:"
        idx = self.web_ui_src.find(marker)
        self.assertGreater(idx, 0, "未找到 run() 函数定义")
        # run() 函数体大约 100 行；窗口 5000 字符足够
        window = self.web_ui_src[idx : idx + 5000]
        self.assertIn(
            "threading.Thread(",
            window,
            "run() 必须用 threading.Thread 启动 mDNS 注册——这是 R20.11 节省 1.7s "
            "spawn-to-listen 延迟的核心",
        )
        self.assertIn(
            "target=self._start_mdns_if_needed",
            window,
            "Thread target 必须是 self._start_mdns_if_needed——确保异步调用方法正确",
        )

    def test_run_thread_is_daemon(self) -> None:
        """mDNS thread 必须是 daemon，否则 Web UI 进程退出时会被卡住等线程"""
        marker = "def run(self) -> FeedbackResult:"
        idx = self.web_ui_src.find(marker)
        window = self.web_ui_src[idx : idx + 5000]
        self.assertIn(
            "daemon=True",
            window,
            "mDNS thread 必须 daemon=True，否则进程退出时会等线程完成 conflict-probe",
        )

    def test_run_does_not_directly_call_start_mdns(self) -> None:
        """禁止 run() 中保留同步调用形式 self._start_mdns_if_needed() （会破坏 R20.11）"""
        marker = "def run(self) -> FeedbackResult:"
        idx = self.web_ui_src.find(marker)
        window = self.web_ui_src[idx : idx + 5000]
        # run() 函数体内不允许出现裸 self._start_mdns_if_needed() 调用形式
        # （只能作为 thread target 出现）
        # 简化检查：确保所有 _start_mdns_if_needed 都跟在 target= 后面
        positions: list[int] = []
        search_from = 0
        while True:
            p = window.find("_start_mdns_if_needed", search_from)
            if p == -1:
                break
            positions.append(p)
            search_from = p + 1
        # 至少要有一处出现（在 Thread target=...）
        self.assertGreater(
            len(positions),
            0,
            "run() 中必须出现 _start_mdns_if_needed（作为 thread target）",
        )
        for p in positions:
            # 检查前面是否是 "target=" 形式
            preceding = window[max(0, p - 30) : p]
            self.assertIn(
                "target=self.",
                preceding,
                f"run() 中 _start_mdns_if_needed 必须仅作为 Thread target 出现（位置 {p}），"
                "禁止裸同步调用",
            )

    def test_init_declares_mdns_thread_attribute(self) -> None:
        """__init__ 中必须显式声明 _mdns_thread = None"""
        self.assertIn(
            "self._mdns_thread:",
            self.web_ui_src,
            "__init__ 必须显式声明 _mdns_thread 属性（带类型注解），"
            "否则 _stop_mdns 第一次访问会抛 AttributeError",
        )
        self.assertIn(
            "self._mdns_thread: threading.Thread | None = None",
            self.web_ui_src,
            "_mdns_thread 类型必须是 threading.Thread | None，初值 None",
        )

    def test_stop_mdns_joins_thread_with_timeout(self) -> None:
        """_stop_mdns 必须 join thread 并带 timeout（防止 shutdown hang）"""
        marker = "def _stop_mdns(self) -> None:"
        idx = self.mdns_src.find(marker)
        self.assertGreater(idx, 0, "未找到 _stop_mdns 函数定义")
        window = self.mdns_src[idx : idx + 3000]
        self.assertIn(
            ".join(timeout=",
            window,
            "_stop_mdns 必须 thread.join(timeout=...) 防止 daemon 线程让 shutdown 卡住",
        )


# ═══════════════════════════════════════════════════════════════════════════
# 4. 集成测试：subprocess-isolated 端到端 spawn-to-listen 时间
# ═══════════════════════════════════════════════════════════════════════════
class TestEndToEndSpawnToListenLatency(unittest.TestCase):
    """完整 subprocess.Popen([python, '-u', web_ui.py]) 到 socket 可连接的 wall time"""

    def _free_port(self) -> int:
        """获取一个空闲端口"""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]

    def _measure_spawn_to_listen_ms(self) -> float:
        """隔离测一次子进程从 Popen 到 socket listen 的时间。"""
        port = self._free_port()
        env = {**os.environ, "AI_INTERVENTION_AGENT_NO_BROWSER": "1"}

        t1 = time.monotonic()
        proc = subprocess.Popen(
            [
                sys.executable,
                "-u",
                "web_ui.py",
                "--prompt",
                "r20.11-int-test",
                "--port",
                str(port),
            ],
            cwd=str(PROJECT_ROOT),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            deadline = t1 + 15.0
            while time.monotonic() < deadline:
                try:
                    with socket.create_connection(("127.0.0.1", port), timeout=0.05):
                        return (time.monotonic() - t1) * 1000.0
                except (TimeoutError, ConnectionRefusedError, OSError):
                    time.sleep(0.02)

            self.fail(
                f"Web UI 子进程在 15s 内未能 listen on 127.0.0.1:{port}—— "
                "可能是 mDNS 又被同步化阻塞了，或 web_ui import 出问题"
            )
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)

    def test_spawn_to_listen_under_1200ms(self) -> None:
        """端到端冷启动到 socket listen 最佳采样必须 < 1200 ms

        预期实测中位数 ~200 ms（R20.11 后）；GitHub Actions Python 3.13 + coverage
        曾出现 ~1201 ms 的单次冷启动抖动。最多两次采样取 best-of-two，仍用
        1200 ms 阈值，能继续拦住 mDNS 又被同步化或 web_ui import 大幅回退。

        R20.10 baseline: 1922 ms（mDNS conflict-probe 同步阻塞 ~1.7s）
        R20.11 target:   best-of-two < 1200 ms（mDNS 异步发布，不阻塞 listen）
        """
        attempts = [self._measure_spawn_to_listen_ms()]
        if attempts[0] >= 1200.0:
            attempts.append(self._measure_spawn_to_listen_ms())

        best_ms = min(attempts)
        formatted_attempts = " / ".join(f"{value:.1f} ms" for value in attempts)
        self.assertLess(
            best_ms,
            1200.0,
            f"spawn-to-listen 最佳采样 {best_ms:.1f} ms 仍超过 1200 ms 上限"
            f"（attempts: {formatted_attempts}）——R20.11 baseline 是 ~200 ms 中位数；"
            f"best-of-two 仍失败时，最可能原因是 mDNS 被同步化了"
            f"（run() 中 _start_mdns_if_needed 又被裸调用而非 Thread target）",
        )


if __name__ == "__main__":
    unittest.main()
