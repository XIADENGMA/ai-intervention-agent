"""port-in-use friendly message · ``start_web_service`` 端口冲突错误文案契约。

设计目标
========

历史 ``port_in_use`` 错误信息是：

    端口 127.0.0.1:8080 已被占用，但 health-check 未识别为本服务。
    请检查是否有其他进程占用该端口，或在配置中改用其他端口。

——文字干净，但 actionable 程度低：用户得自己去翻
``docs/troubleshooting.md`` 才能找到 ``lsof`` / ``pkill`` / env override
等具体修复路径。

本次改进把 3 条可执行解决方案内联进 error message：

1. **env override**（首推）：
   ``export AI_INTERVENTION_AGENT_WEB_UI_PORT=<新端口>``
   ——配合本项目新增的 web_ui env override 形成闭环，无需改 config.toml；
2. **永久换端口**：编辑 ``config.toml [web_ui] port=<新端口>``；
3. **查看占用**：``lsof -nP -iTCP:<port> -sTCP:LISTEN``；

并保留指向 ``docs/troubleshooting.md#1`` 的索引供深度排查。

invariant 守护
========

测试目标是锁住「friendly message 不会被悄悄回滚」这条契约，避免某次
i18n / refactor 把可执行 hint 删掉、message 回到旧版「请检查」泛泛
表述。同时也守住：

* error code **仍**是 ``port_in_use``（上层 monitoring / VS Code
  插件精确文案路径依赖该码）；
* host:port **仍**出现在 message（与 ``test_server_functions::
  test_port_in_use_message_mentions_host_and_port`` 一致）。

这些 invariant 是用户体验的安全网，回归会立刻打到 CI。
"""

from __future__ import annotations

import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from ai_intervention_agent import server, service_manager
from ai_intervention_agent.service_manager import (
    ServiceUnavailableError,
    WebUIConfig,
)

_SERVER_DIR = Path(service_manager.__file__ or ".").resolve().parent


def _make_config(host: str = "127.0.0.1", port: int = 18080) -> WebUIConfig:
    return WebUIConfig(host=host, port=port)


class TestPortInUseFriendlyMessage(unittest.TestCase):
    """``start_web_service`` 端口冲突错误 message 含可执行解决方案。"""

    def setUp(self) -> None:
        server.ServiceManager._instance = None
        server.ServiceManager._lock = threading.Lock()

    def tearDown(self) -> None:
        server.ServiceManager._instance = None

    def _raise_port_in_use(
        self, host: str = "127.0.0.1", port: int = 18080
    ) -> ServiceUnavailableError:
        """触发 port_in_use 路径，返回抛出的 ServiceUnavailableError。"""
        cfg = _make_config(host=host, port=port)
        script_dir = _SERVER_DIR
        with (
            patch.object(service_manager, "_is_port_available", return_value=False),
            patch.object(service_manager, "health_check_service", return_value=False),
            patch.object(service_manager, "NOTIFICATION_AVAILABLE", False),
            self.assertRaises(ServiceUnavailableError) as ctx,
        ):
            server.start_web_service(cfg, script_dir)
        return ctx.exception

    # ---- 1) 错误码 invariant（与历史契约保持一致）----

    def test_error_code_still_port_in_use(self) -> None:
        exc = self._raise_port_in_use()
        self.assertEqual(
            exc.code,
            "port_in_use",
            f"友好 message 不应改变 error code，实际：{exc.code!r}",
        )

    # ---- 2) host:port 仍在 message（与历史测试同一契约）----

    def test_message_still_contains_host_and_port(self) -> None:
        exc = self._raise_port_in_use(host="0.0.0.0", port=18181)
        msg = str(exc)
        self.assertIn("0.0.0.0", msg, f"message 应含 host，实际：{msg!r}")
        self.assertIn("18181", msg, f"message 应含 port，实际：{msg!r}")

    # ---- 3) friendly hint：env override 路径必须可见 ----

    def test_message_mentions_env_override(self) -> None:
        """env override 是首推方案——避免被回滚成"请改 config"的泛泛建议。

        与 ``AI_INTERVENTION_AGENT_WEB_UI_PORT`` 形成闭环，让用户不
        重启 IDE / 不编辑文件就能换端口。
        """
        exc = self._raise_port_in_use()
        msg = str(exc)
        self.assertIn(
            "AI_INTERVENTION_AGENT_WEB_UI_PORT",
            msg,
            f"message 应含 env override 示例（首推方案），实际：{msg!r}",
        )

    def test_message_mentions_config_toml(self) -> None:
        """永久换端口路径：``config.toml [web_ui] port=``。"""
        exc = self._raise_port_in_use()
        msg = str(exc)
        self.assertIn(
            "config.toml",
            msg,
            f"message 应含 config.toml 替代路径，实际：{msg!r}",
        )

    def test_message_mentions_lsof(self) -> None:
        """诊断路径：``lsof`` 给用户"是谁占了我的端口"的可执行命令。"""
        exc = self._raise_port_in_use(port=12345)
        msg = str(exc)
        self.assertIn(
            "lsof",
            msg,
            f"message 应含 lsof 诊断命令，实际：{msg!r}",
        )
        # 端口号要正确替代进 lsof 命令——避免硬编码 "8080" 等占位符
        self.assertIn(
            "12345",
            msg,
            f"lsof 提示应使用实际端口号 12345，实际：{msg!r}",
        )

    def test_message_links_to_troubleshooting_doc(self) -> None:
        """深度排查入口：``docs/troubleshooting.md`` Issue #1 的链接。"""
        exc = self._raise_port_in_use()
        msg = str(exc)
        self.assertIn(
            "docs/troubleshooting.md",
            msg,
            f"message 应指向 troubleshooting doc，实际：{msg!r}",
        )

    # ---- 4) message 仍然是 single-string（不能塞换行让上层 logger 难处理）----

    def test_message_is_single_string_not_list(self) -> None:
        exc = self._raise_port_in_use()
        msg = exc.args[0] if exc.args else ""
        self.assertIsInstance(
            msg,
            str,
            f"message 必须是 str，实际：{type(msg).__name__}",
        )

    def test_message_does_not_contain_raw_newlines(self) -> None:
        """单行 message 让 logger / Sentry 显示更紧凑；多行细节去 docs。"""
        exc = self._raise_port_in_use()
        msg = str(exc)
        self.assertNotIn(
            "\n",
            msg,
            f"message 不应含原始 \\n（单行设计），实际：{msg!r}",
        )

    # ---- 5) 健壮性：不同 host/port 组合都能命中 friendly path ----

    def test_message_for_ipv6_host(self) -> None:
        """IPv6 host（``::``）路径也走 friendly message。"""
        exc = self._raise_port_in_use(host="::", port=8443)
        msg = str(exc)
        self.assertIn("::", msg)
        self.assertIn("8443", msg)
        self.assertIn("AI_INTERVENTION_AGENT_WEB_UI_PORT", msg)


if __name__ == "__main__":
    unittest.main()
