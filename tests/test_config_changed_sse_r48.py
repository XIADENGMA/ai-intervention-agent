"""R48 ``config_changed`` SSE 推送回归契约。

覆盖：
1. ``_emit_config_changed_to_sse_bus`` 真的会调用 ``_sse_bus.emit('config_changed', ...)``
   一次，且只发轻量字典（不带敏感配置内容）。
2. ``_ensure_config_changed_sse_callback_registered`` 是 idempotent（双检 lock 模式）：
   - 首次调用注册 callback、置 flag；
   - 重复调用不再注册；
   - 注册时若 ``get_config`` 抛异常，flag 保持 False 且不抛出。
3. 端到端：``ConfigManager._trigger_config_change_callbacks`` 触发回调
   → SSE bus 收到 ``config_changed`` 事件（payload 含 ``reason`` / ``hint``）。
4. 前端 / VSCode 扩展端 listener 已通过源码静态扫描确认存在。

设计原则：
- 整个测试不依赖 web_ui 子进程 / Flask app；通过 lazy import + monkey patch
  让 ``_emit_config_changed_to_sse_bus`` 走 fake bus，避免真的去触发 web_ui 路由。
- 所有用到 ``web_ui._CONFIG_CHANGED_SSE_CALLBACK_REGISTERED`` 模块级 flag
  的测试用 ``setUp`` / ``tearDown`` 保存恢复，避免污染其它测试。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import ai_intervention_agent.web_ui as web_ui
import ai_intervention_agent.web_ui_config_sync as web_ui_config_sync

# ============================================================================
# 1. _emit_config_changed_to_sse_bus 行为契约
# ============================================================================


class TestEmitConfigChangedSendsSSEEvent(unittest.TestCase):
    """``_emit_config_changed_to_sse_bus`` 必须调用 ``_sse_bus.emit`` 恰好一次。"""

    def setUp(self) -> None:
        # R50-B：每个用例前重置 debounce state，避免上个用例刚 emit 完
        # 让本用例落进 250ms 抑制窗口里。
        web_ui_config_sync._last_emit_monotonic = 0.0

    def test_emit_is_called_with_event_type_and_payload(self) -> None:
        with patch("ai_intervention_agent.web_ui_routes.task._sse_bus") as fake_bus:
            web_ui_config_sync._emit_config_changed_to_sse_bus()
        fake_bus.emit.assert_called_once()
        args, _kwargs = fake_bus.emit.call_args
        # 第一个位置参数：event_type
        self.assertEqual(args[0], "config_changed")
        # 第二个位置参数：payload dict
        payload = args[1]
        self.assertIsInstance(payload, dict)
        self.assertIn("reason", payload)
        self.assertIn("hint", payload)
        self.assertEqual(payload["reason"], "config_file_modified")

    def test_payload_does_not_leak_config_values(self) -> None:
        """payload 不应包含任何敏感字段（``bark_url`` / ``device_key`` / 路径等）。"""
        with patch("ai_intervention_agent.web_ui_routes.task._sse_bus") as fake_bus:
            web_ui_config_sync._emit_config_changed_to_sse_bus()
        args, _ = fake_bus.emit.call_args
        payload = args[1]
        forbidden_substrings = ("bark_url", "device_key", "token", "password", "secret")
        for key in payload:
            for forbidden in forbidden_substrings:
                self.assertNotIn(
                    forbidden,
                    key.lower(),
                    f"config_changed payload key {key!r} 不应包含 {forbidden!r}",
                )
            # value 也扫一遍
            value = str(payload[key])
            for forbidden in forbidden_substrings:
                self.assertNotIn(
                    forbidden,
                    value.lower(),
                    f"config_changed payload value 含敏感字串 {forbidden!r}",
                )

    def test_emit_failure_is_swallowed(self) -> None:
        """``_sse_bus.emit`` 抛异常时主流程不应崩（不阻塞其它 callback）。"""
        with patch("ai_intervention_agent.web_ui_routes.task._sse_bus") as fake_bus:
            fake_bus.emit.side_effect = RuntimeError("simulated SSE bus down")
            try:
                web_ui_config_sync._emit_config_changed_to_sse_bus()
            except Exception as exc:
                self.fail(f"_emit_config_changed_to_sse_bus 不应让异常扩散：{exc!r}")


# ============================================================================
# 2. _ensure_config_changed_sse_callback_registered 是 idempotent
# ============================================================================


class TestEnsureCallbackRegistration(unittest.TestCase):
    """``_ensure_config_changed_sse_callback_registered`` 必须 idempotent。"""

    def setUp(self) -> None:
        self._original_flag = web_ui._CONFIG_CHANGED_SSE_CALLBACK_REGISTERED
        web_ui._CONFIG_CHANGED_SSE_CALLBACK_REGISTERED = False

    def tearDown(self) -> None:
        web_ui._CONFIG_CHANGED_SSE_CALLBACK_REGISTERED = self._original_flag

    def test_first_call_registers_callback(self) -> None:
        fake_cfg = MagicMock()
        with patch("ai_intervention_agent.web_ui.get_config", return_value=fake_cfg):
            web_ui_config_sync._ensure_config_changed_sse_callback_registered()
        fake_cfg.register_config_change_callback.assert_called_once_with(
            web_ui_config_sync._emit_config_changed_to_sse_bus
        )
        self.assertTrue(web_ui._CONFIG_CHANGED_SSE_CALLBACK_REGISTERED)

    def test_repeat_call_is_no_op(self) -> None:
        fake_cfg = MagicMock()
        with patch("ai_intervention_agent.web_ui.get_config", return_value=fake_cfg):
            web_ui_config_sync._ensure_config_changed_sse_callback_registered()
            web_ui_config_sync._ensure_config_changed_sse_callback_registered()
            web_ui_config_sync._ensure_config_changed_sse_callback_registered()
        # register 应只被调用一次
        self.assertEqual(fake_cfg.register_config_change_callback.call_count, 1)

    def test_get_config_failure_keeps_flag_false_and_does_not_raise(self) -> None:
        with patch(
            "ai_intervention_agent.web_ui.get_config",
            side_effect=RuntimeError("no config"),
        ):
            try:
                web_ui_config_sync._ensure_config_changed_sse_callback_registered()
            except Exception as exc:
                self.fail(f"注册失败不应抛异常给 caller：{exc!r}")
        self.assertFalse(
            web_ui._CONFIG_CHANGED_SSE_CALLBACK_REGISTERED,
            "注册失败时 flag 应保持 False，让下次调用还能重试",
        )


# ============================================================================
# 3. 端到端：ConfigManager 触发 callback → SSE bus 收到事件
# ============================================================================


class TestEndToEndCallbackChain(unittest.TestCase):
    """``ConfigManager._trigger_config_change_callbacks`` → ``_sse_bus.emit``。"""

    def setUp(self) -> None:
        self._original_flag = web_ui._CONFIG_CHANGED_SSE_CALLBACK_REGISTERED
        web_ui._CONFIG_CHANGED_SSE_CALLBACK_REGISTERED = False
        # R50-B：重置 debounce state，避免和别的用例打架
        web_ui_config_sync._last_emit_monotonic = 0.0

    def tearDown(self) -> None:
        web_ui._CONFIG_CHANGED_SSE_CALLBACK_REGISTERED = self._original_flag

    def test_full_chain_sse_emit(self) -> None:
        """注册回调后，``_trigger_config_change_callbacks`` 应让 SSE bus emit。

        用真实 ``ConfigManager`` 实例（不会触发 web_ui 子进程，是纯内存对象）
        加 fake SSE bus 来端到端验证。
        """
        from ai_intervention_agent.config_manager import ConfigManager

        cfg = ConfigManager()
        try:
            # 把 web_ui.get_config 指向我们的测试实例
            with patch("ai_intervention_agent.web_ui.get_config", return_value=cfg):
                web_ui_config_sync._ensure_config_changed_sse_callback_registered()

            # 触发回调链
            with patch("ai_intervention_agent.web_ui_routes.task._sse_bus") as fake_bus:
                cfg._trigger_config_change_callbacks()
            fake_bus.emit.assert_called_once()
            self.assertEqual(fake_bus.emit.call_args[0][0], "config_changed")
        finally:
            cfg.shutdown()


# ============================================================================
# 4. 前端 + VSCode 扩展端 listener 静态扫描
# ============================================================================


class TestFrontendListenersExist(unittest.TestCase):
    """``static/js/multi_task.js`` 和 ``packages/vscode/extension.ts`` 必须监听 ``config_changed``。"""

    def test_multi_task_js_has_listener(self) -> None:
        source = (
            REPO_ROOT
            / "src"
            / "ai_intervention_agent"
            / "static"
            / "js"
            / "multi_task.js"
        ).read_text(encoding="utf-8")
        # 同时接受单/双引号字面量：测试锁住「listener 存在」语义，而不是引号风格。
        # Prettier 默认 `singleQuote: false` 会把整个文件改成双引号；当文件被
        # 大规模 reformat 时不应让本测试假阴。
        self.assertRegex(
            source,
            r"addEventListener\(['\"]config_changed['\"]",
            "multi_task.js 必须监听 config_changed SSE 事件，给浏览器用户提示",
        )

    def test_multi_task_js_uses_existing_toast_helper(self) -> None:
        source = (
            REPO_ROOT
            / "src"
            / "ai_intervention_agent"
            / "static"
            / "js"
            / "multi_task.js"
        ).read_text(encoding="utf-8")
        # 锁住 "复用现有 toast helper" 这个不变量；
        # 既不要私自塞一个 alert()，也不要无声吞掉提示
        self.assertIn(
            "_showToast",
            source,
            "config_changed 必须通过 _showToast 给用户可见提示，而不是 alert / 静默忽略",
        )

    def test_vscode_extension_has_listener(self) -> None:
        source = (REPO_ROOT / "packages" / "vscode" / "extension.ts").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            "config_changed",
            source,
            "extension.ts 必须识别 config_changed 事件，给状态栏提示",
        )

    def test_vscode_extension_uses_status_bar_message(self) -> None:
        source = (REPO_ROOT / "packages" / "vscode" / "extension.ts").read_text(
            encoding="utf-8"
        )
        # 锁定 "用 setStatusBarMessage 而不是 showInformationMessage"
        # showInformationMessage 会弹 modal 打断用户，不符合"提示但不打断"的设计
        # 用源码扫描的方式锁住 config_changed 事件处理体里一定调用 setStatusBarMessage
        if "config_changed" in source:
            # 找到 config_changed 处理块
            cc_idx = source.index("config_changed")
            window = source[cc_idx : cc_idx + 1500]
            self.assertIn(
                "setStatusBarMessage",
                window,
                "extension.ts 中 config_changed 块必须用 setStatusBarMessage（非阻塞）",
            )


# ============================================================================
# 5. web_ui.py 在首个真实请求路径注册 _ensure_config_changed_sse_callback_registered
# ============================================================================


class TestWebUIRuntimeHooksRegisterCallback(unittest.TestCase):
    """``WebFeedbackUI`` 必须在 runtime hook 路径调用 config_changed 注册 helper。

    通过源码静态扫描验证（避免起 Flask app 的副作用）。
    """

    def test_web_ui_imports_helper(self) -> None:
        source = (REPO_ROOT / "src" / "ai_intervention_agent" / "web_ui.py").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            "_ensure_config_changed_sse_callback_registered",
            source,
            "web_ui.py 必须 import _ensure_config_changed_sse_callback_registered",
        )

    def test_web_ui_calls_helper_in_runtime_hook(self) -> None:
        source = (REPO_ROOT / "src" / "ai_intervention_agent" / "web_ui.py").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            "def _ensure_base_config_runtime_hooks_registered",
            source,
            "web_ui.py 必须保留首个请求触发的 base config runtime hook",
        )
        occurrences = source.count("_ensure_config_changed_sse_callback_registered")
        self.assertGreaterEqual(
            occurrences,
            2,
            f"web_ui.py 应至少出现 2 次 _ensure_config_changed_sse_callback_registered "
            f"（1 处 import + 1 处调用），实际 {occurrences}",
        )


if __name__ == "__main__":
    unittest.main()
