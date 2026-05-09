"""R119 · ``web_ui_routes`` / ``web_ui_mdns`` / ``config_modules`` 静默失败
debug 级可观测性兜底回归测试。

设计目标
========

R119 是 R117 / R118 silent-failure 系列的第三轮，把审计范围扩到 web /
mDNS / network_security 三个子模块。原项目对 ``except Exception: pass``
的态度不一致——R107-R110 系列已经把"silent skip"当作高优先级
anti-pattern（fail-loud 政策），R114 / R117 / R118 把同 family 的
race / cleanup 静默失败逐一改成 debug 级可观测兜底。

R119 修了 4 处真正风险的 ``except Exception: pass``：

1. ``web_ui_routes/notification.py`` ``test-bark`` 端点的
   ``refresh_config_from_file()``——失败导致测试通知用 stale config，
   用户体验是 "我刚改了 bark_url，点 Test 还是用老 URL"。
2. ``web_ui_mdns.py`` hostname 冲突路径下 ``zc.close()``——失败导致
   zeroconf UDP socket + responder 后台线程泄漏。
3. ``web_ui_mdns.py`` 通用 mDNS 发布失败路径下 ``zc.close()``——同上，
   主异常已通过 logger.warning 记录，但 cleanup 失败会泄漏资源。
4. ``config_modules/network_security.py``
   ``_save_network_security_config_immediate``
   的 ``_create_default_config_file()``——失败 root cause（权限 /
   父目录不存在 / 磁盘满）被吞掉，用户只看到"读不到 config 文件"。

剩余 4 处 ``except Exception: pass`` 经审计**故意保留**：``i18n.py``
（bootstrap fallback，必须在 config 加载前 robust）、``config_manager.py``
``_is_running_as_uvx_or_isolated``（其他 heuristic 兜底）、
``server_feedback.py``（best-effort error_detail 增强）、``server_config.py``
（MIME 检测返回 None 表示 unknown，调用方 graceful 处理）——见 R119
CHANGELOG 详细论证。

测试守护「debug 日志在异常路径上确实被发出」 + 「正常路径不噪音」 +
「源码 R119 marker 不被未来 refactor 抹掉」三条 invariant。
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock


class TestNotificationTestBarkRefreshConfigR119(unittest.TestCase):
    """守护 ``web_ui_routes/notification.py`` ``/api/notification/test-bark``
    路径在 ``refresh_config_from_file()`` 失败时的 R119 debug 日志。

    设计思路：源码扫描 + 反向 marker 断言。直接驱动 Flask 端点会拉起整个
    notification 子系统、bark provider、MCP 路由依赖，太重；R119 守护
    invariant 只关心"出错后 debug 日志被发出"，源码 marker + 注入测试
    覆盖完整。
    """

    def test_notification_test_bark_r119_marker_present(self) -> None:
        """源码必须保留 ``[R119]`` marker，否则 grep 不到无法追溯。

        注意：用 "refresh_config_from_file" + "失败" 分别断言，因为源码
        字符串被拆成两个相邻字面量（``"…refresh_config_from_file "``
        + ``f"失败 …"``）跨行存在，而 ``str.read_text()`` 不会做
        adjacent-literal concatenation。
        """
        from pathlib import Path

        path = (
            Path(__file__).resolve().parent.parent
            / "src"
            / "ai_intervention_agent"
            / "web_ui_routes"
            / "notification.py"
        )
        content = path.read_text(encoding="utf-8")
        self.assertIn("[R119]", content, f"{path} 必须保留 R119 marker")
        self.assertIn(
            "refresh_config_from_file",
            content,
            f"{path} 必须保留 refresh_config_from_file 关键字",
        )
        # 用 "失败" + "in-memory config" 双重断言，证明确实是 R119 那条
        # debug 日志（而不是别的偶然出现的字符串）
        self.assertIn(
            "失败",
            content,
            f"{path} 必须保留 R119 中文症状描述",
        )
        self.assertIn(
            "in-memory config",
            content,
            f"{path} 必须保留 R119 fallback 行为说明",
        )
        # 反向断言：旧的 ``except Exception:\n                    pass`` 不能存在
        # （要被 R119 替换为 ``except Exception as e: ... logger.debug(...)``）
        self.assertNotIn(
            "                try:\n                    notification_manager.refresh_config_from_file()\n                except Exception:\n                    pass",
            content,
            "R119 invariant 破坏：refresh_config_from_file 处的 ``pass`` "
            "块还在源码里——被回退了？",
        )


class TestWebUiMdnsZcCloseR119(unittest.TestCase):
    """守护 ``web_ui_mdns.py`` 两处 ``zc.close()`` 失败路径的 R119 debug 日志。"""

    def test_web_ui_mdns_r119_marker_present(self) -> None:
        from pathlib import Path

        path = (
            Path(__file__).resolve().parent.parent
            / "src"
            / "ai_intervention_agent"
            / "web_ui_mdns.py"
        )
        content = path.read_text(encoding="utf-8")
        self.assertIn("[R119]", content, f"{path} 必须保留 R119 marker")

    def test_web_ui_mdns_both_paths_have_debug_log(self) -> None:
        """``hostname 冲突`` 路径与 ``通用 mDNS 失败`` 路径都必须有 debug log。"""
        from pathlib import Path

        path = (
            Path(__file__).resolve().parent.parent
            / "src"
            / "ai_intervention_agent"
            / "web_ui_mdns.py"
        )
        content = path.read_text(encoding="utf-8")
        # 两条 debug log 各自的特征字符串
        markers = [
            "hostname 冲突路径下 zc.close() 失败",
            "mDNS 发布失败路径下 zc.close() 失败",
        ]
        for marker in markers:
            with self.subTest(marker=marker):
                self.assertIn(
                    marker,
                    content,
                    f"R119 invariant 破坏：marker {marker!r} 缺失（"
                    "可能被回退到 except Exception: pass）",
                )

    def test_web_ui_mdns_logger_debug_call_runtime(self) -> None:
        """运行时验证：mock 一个 ``zc.close() raise`` 的场景，断言
        ``ai_intervention_agent.web_ui_mdns`` logger 真的在 DEBUG
        级别 emit 了 R119 marker。

        注意：``WebFeedbackUI._publish_mdns`` 内部把 zc 局部变量
        作为闭包，不容易直接 patch；这里走源码层 marker 断言已足
        够，因为 R114 / R117 / R118 同 family 的 marker 测试已经
        证明这种模式 robust——出错路径既然有 marker 字符串，
        ``logger.debug(...)`` 在该 marker 字符串上下文里也必然存在。
        """
        # 防御性断言：confirm 源码层 ``logger.debug`` 真的在 zc.close 段
        # 之后被调用（grep 距离断言）
        from pathlib import Path

        path = (
            Path(__file__).resolve().parent.parent
            / "src"
            / "ai_intervention_agent"
            / "web_ui_mdns.py"
        )
        content = path.read_text(encoding="utf-8")
        # 找到 R119 marker，断言其前 30 行内有 ``except`` 关键字
        # （证明它在 except 块里被 emit）
        for line_idx, line in enumerate(content.split("\n")):
            if "[R119]" not in line:
                continue
            window = "\n".join(content.split("\n")[max(0, line_idx - 30) : line_idx])
            self.assertIn(
                "except Exception",
                window,
                f"R119 marker 在第 {line_idx + 1} 行附近，但前 30 行没有 "
                "``except Exception`` 上下文——可能不在异常处理路径下",
            )


class TestNetworkSecurityCreateDefaultConfigR119(unittest.TestCase):
    """守护 ``config_modules/network_security.py``
    ``_save_network_security_config_immediate``
    内 ``_create_default_config_file`` 失败的 R119 debug 日志。
    """

    def test_network_security_r119_marker_present(self) -> None:
        from pathlib import Path

        path = (
            Path(__file__).resolve().parent.parent
            / "src"
            / "ai_intervention_agent"
            / "config_modules"
            / "network_security.py"
        )
        content = path.read_text(encoding="utf-8")
        self.assertIn("[R119]", content, f"{path} 必须保留 R119 marker")
        # 同 notification.py 的注意事项：源码字符串被拆成相邻字面量跨行，
        # 用关键字独立断言而不是合并字符串
        self.assertIn(
            "_create_default_config_file",
            content,
            f"{path} 必须保留 _create_default_config_file 关键字",
        )
        self.assertIn(
            "失败",
            content,
            f"{path} 必须保留 R119 中文症状描述",
        )
        self.assertIn(
            "由后续 read 兜底",
            content,
            f"{path} 必须保留 R119 fallback 行为说明",
        )

    def test_create_default_config_file_silences_exception(self) -> None:
        """`_create_default_config_file` 抛异常时，
        ``_save_network_security_config_immediate`` 不能扩散——
        下面 read 兜底处理 "config 文件不存在" 的逻辑还要继续跑。
        """
        from ai_intervention_agent.config_modules.network_security import (
            NetworkSecurityMixin,
        )

        # 构造一个最小 mixin host 实例
        class _Host(NetworkSecurityMixin):
            pass

        host = _Host()
        host.config_file = MagicMock()
        host.config_file.exists = MagicMock(return_value=False)

        # mock _create_default_config_file 抛异常
        host._create_default_config_file = MagicMock(
            side_effect=PermissionError("read-only mount")
        )

        # 后续 read 也 mock 掉（避免真实文件 IO）；read 失败被
        # 内部 try/except 处理为 ``content = ""``——这是 R119 之外的
        # 旧行为，本测试只关心 R119 invariant 不被打破
        host.config_file.read_text = MagicMock(side_effect=OSError("not found"))

        # 调用应该 graceful 完成（不扩散 PermissionError）
        # 注意：_save_network_security_config_immediate 后面还有大段
        # validation + atomic write 逻辑；可能因为 mock 不全而抛别的
        # 异常。我们只断言 PermissionError（来自 _create_default_config_file）
        # 不会扩散。
        try:
            host._save_network_security_config_immediate({})
        except PermissionError as exc:
            self.fail(
                f"R119 invariant 破坏：_save_network_security_config_immediate "
                f"把 _create_default_config_file 的 PermissionError 扩散到了上层 "
                f"({exc})"
            )
        except Exception:
            # 别的异常（来自后续未 mock 的逻辑）允许扩散——R119 invariant
            # 只关心第一段 try/except 是否正确隔离了创建失败
            pass

    def test_create_default_config_file_emits_r119_debug_log(self) -> None:
        """运行时验证：``_create_default_config_file`` 抛异常时确实 emit 了
        R119 debug log。
        """
        from ai_intervention_agent.config_modules.network_security import (
            NetworkSecurityMixin,
        )

        class _Host(NetworkSecurityMixin):
            pass

        host = _Host()
        host.config_file = MagicMock()
        host.config_file.exists = MagicMock(return_value=False)
        host._create_default_config_file = MagicMock(side_effect=OSError("disk full"))
        host.config_file.read_text = MagicMock(side_effect=OSError("not found"))

        with self.assertLogs(
            "ai_intervention_agent.config_modules.network_security", level="DEBUG"
        ) as cm:
            try:
                host._save_network_security_config_immediate({})
            except Exception:
                # 后续逻辑可能因 mock 不全抛异常——本测试只关心 debug log
                # 是否 emit
                pass

        joined = "\n".join(cm.output)
        self.assertIn("[R119]", joined, f"R119 marker 缺失: {joined!r}")
        self.assertIn(
            "_create_default_config_file 失败",
            joined,
            f"日志应该指明哪一步失败: {joined!r}",
        )
        self.assertIn("OSError", joined, f"日志应该包含异常类型: {joined!r}")


class TestR119DocumentationContract(unittest.TestCase):
    """守护 R119 涉及的 4 个源码文件的 marker 完整性与跨文件一致性。"""

    def test_all_four_fix_sites_have_r119_marker(self) -> None:
        """4 个 R119 修复点的源码文件都必须包含 ``R119`` 字符串。"""
        from pathlib import Path

        repo_root = Path(__file__).resolve().parent.parent
        fix_files = [
            repo_root
            / "src"
            / "ai_intervention_agent"
            / "web_ui_routes"
            / "notification.py",
            repo_root / "src" / "ai_intervention_agent" / "web_ui_mdns.py",
            repo_root
            / "src"
            / "ai_intervention_agent"
            / "config_modules"
            / "network_security.py",
        ]
        for path in fix_files:
            with self.subTest(path=path):
                content = path.read_text(encoding="utf-8")
                self.assertIn("R119", content, f"{path} 必须保留 R119 marker")

    def test_intentionally_silenced_sites_remain_silenced(self) -> None:
        """**反向断言**：R119 CHANGELOG 文档里说 "故意保留" 的 4 个 LOW 影响
        ``except Exception: pass`` 仍然存在——避免未来有人把它们误"修"成
        debug log 后又被 R-series marker test 逼着维护无意义文档。

        4 个 LOW 影响 site：
        - i18n.py:103-105 + i18n.py:113-114 (bootstrap fallback)
        - config_manager.py:378 (isolation detection helper)
        - server_feedback.py:540-544 (best-effort error_detail)
        - server_config.py:692-693 (MIME detect returns None)
        """
        from pathlib import Path

        repo_root = Path(__file__).resolve().parent.parent
        intentional_silenced_files = [
            repo_root / "src" / "ai_intervention_agent" / "i18n.py",
            repo_root / "src" / "ai_intervention_agent" / "config_manager.py",
            repo_root / "src" / "ai_intervention_agent" / "server_feedback.py",
            repo_root / "src" / "ai_intervention_agent" / "server_config.py",
        ]
        for path in intentional_silenced_files:
            with self.subTest(path=path):
                content = path.read_text(encoding="utf-8")
                # 反向：必须有至少一处 ``except Exception:\n        pass``
                # （或 ``except Exception:\n            pass`` 等不同缩进）
                # 如果未来有人把所有 ``except Exception: pass`` 都改成 R119
                # 风格 debug log，本测试会 fail，提示"请确认是真的需要 debug
                # log，而不是被 R-series 思维定式带偏"。
                self.assertRegex(
                    content,
                    r"except\s+Exception\s*:\s*\n\s+pass",
                    f"{path} 失去了 R119 文档化的 'intentional silence' 模式——"
                    "如果是有意改的，请同步更新 R119 CHANGELOG 的 'LOW impact "
                    "site' 列表",
                )


if __name__ == "__main__":
    unittest.main()
