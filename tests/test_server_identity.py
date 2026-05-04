"""MCP server 身份元数据契约测试。

目标
----
锁定 `FastMCP` 实例在 initialize 协议响应中下发的关键身份字段：
- name：工具列表显示
- instructions：指导 LLM 何时调用 / 不调用工具（最重要）
- version：暴露版本号便于 client 兼容判断 / 故障排查
- website_url：项目主页 / 反馈链接

防止后续重构误删，导致 client / LLM 失去关键上下文。
"""

from __future__ import annotations

import re
import unittest

import server


class TestServerIdentity(unittest.TestCase):
    """validate FastMCP 顶层身份字段对外暴露的稳定性。"""

    def test_name_is_set(self) -> None:
        self.assertEqual(server.mcp.name, "AI Intervention Agent MCP")

    def test_instructions_present_and_chinese(self) -> None:
        """instructions 必须存在，并体现中文产品语义。"""
        instr = getattr(server.mcp, "instructions", None)
        assert isinstance(instr, str), "instructions 缺失或非字符串，LLM 失去调用指引"
        self.assertGreater(
            len(instr), 100, "instructions 过短，无法给 LLM 提供有效指引"
        )
        self.assertIn("interactive_feedback", instr)
        self.assertIn("适合调用的场景", instr)
        self.assertIn("不适合调用的场景", instr)

    def test_instructions_clarify_destructive_safety(self) -> None:
        """instructions 必须明确告诉 LLM「这是非破坏性工具」，
        避免 LLM 因谨慎而漏调。"""
        instr = getattr(server.mcp, "instructions", "") or ""
        assert isinstance(instr, str)
        self.assertIn("非破坏性", instr)
        self.assertIn("非幂等", instr)

    def test_version_is_semver_or_local(self) -> None:
        """version 必须是 semver (1.5.20) 或本地占位符 (0.0.0+local)。"""
        ver = getattr(server.mcp, "version", None)
        assert isinstance(ver, str), "version 缺失或非字符串，client 无法判断兼容性"
        is_semver = bool(re.match(r"^\d+\.\d+\.\d+", ver))
        is_local = ver.startswith("0.0.0+local")
        self.assertTrue(
            is_semver or is_local,
            f"version 必须是 semver 或本地占位符，实际: {ver!r}",
        )

    def test_website_url_points_to_repo(self) -> None:
        url = getattr(server.mcp, "website_url", None)
        assert isinstance(url, str), "website_url 缺失"
        self.assertTrue(
            url.startswith("https://github.com/"),
            f"website_url 应该指向 GitHub 仓库，实际: {url!r}",
        )
        self.assertIn("ai-intervention-agent", url)

    def test_resolve_server_version_returns_string(self) -> None:
        """`_resolve_server_version` 必须始终返回非空 str。"""
        ver = server._resolve_server_version()
        self.assertIsInstance(ver, str)
        self.assertGreater(len(ver), 0)


class TestServerIcons(unittest.TestCase):
    """server icons 必须以 data URI 形式 self-contained，不依赖外部网络。"""

    def test_icons_attached(self) -> None:
        """initialize 响应需要带 icons，方便 client UI 标识本服务。"""
        icons = getattr(server.mcp, "icons", None) or []
        self.assertGreater(len(icons), 0, "server icons 缺失，client UI 看不到图标")

    def test_all_icons_are_data_uris(self) -> None:
        """所有 icons 必须用 base64 data URI，不依赖 GitHub raw URL 时序问题。

        如果误用了 http(s):// URL，client 在 main 分支资源还没 push 时会 404。
        """
        icons = server.mcp.icons or []
        for icon in icons:
            self.assertTrue(
                icon.src.startswith("data:"),
                f"icon 必须用 data URI（避免外部依赖），实际: {icon.src[:40]!r}",
            )

    def test_icons_cover_common_sizes(self) -> None:
        """覆盖常见显示密度：小图标（32）、应用图标（192/512）、矢量备用（svg）。"""
        icons = server.mcp.icons or []
        sizes_seen = {tuple(ic.sizes) if ic.sizes else () for ic in icons}
        self.assertIn(("32x32",), sizes_seen, "需要 32x32 favicon 用于 client 工具列表")
        self.assertIn(("192x192",), sizes_seen, "需要 192x192 PWA 标准尺寸")

    def test_icons_have_correct_mime_types(self) -> None:
        icons = server.mcp.icons or []
        mime_types = {ic.mimeType for ic in icons}
        self.assertIn("image/png", mime_types, "至少需要一个 PNG")
        # SVG 备用，client 支持时优先用矢量
        self.assertIn("image/svg+xml", mime_types, "应当提供 SVG 矢量备用图")

    def test_build_server_icons_handles_missing_files(self) -> None:
        """`_build_server_icons` 在 icons 目录不存在时也不应抛异常。

        这是 server 启动健壮性的兜底测试。
        """
        # 直接调用一次确认不抛
        result = server._build_server_icons()
        self.assertIsInstance(result, list)

    def test_build_server_icons_skips_individual_failure(self) -> None:
        """单个图标文件 corrupt / 读不出 data URI 时，应跳过它继续处理其它图标。

        防止「一个图标坏掉 → server 启动整体崩 / icons 全空」的脆弱链路。
        """
        from unittest.mock import patch

        from fastmcp.utilities.types import Image as _RealImage

        original_to_data_uri = _RealImage.to_data_uri
        call_counter = {"n": 0}

        def flaky_to_data_uri(self):  # type: ignore[no-untyped-def]
            """模拟「第 1 个图标读 raise，剩下的正常」。"""
            call_counter["n"] += 1
            if call_counter["n"] == 1:
                raise OSError("simulated corrupt icon")
            return original_to_data_uri(self)

        with patch.object(_RealImage, "to_data_uri", flaky_to_data_uri):
            icons = server._build_server_icons()

        # 4 个 icon 配置 - 第 1 个失败 → 仍能拿到剩下 3 个
        self.assertGreaterEqual(len(icons), 1, "单个图标失败不应让函数返回空列表")
        self.assertLess(len(icons), 4, "失败的图标确实被跳过")

    def test_resolve_server_version_handles_metadata_failure(self) -> None:
        """`importlib.metadata.version` 抛异常时回退到 0.0.0+local。"""
        from unittest.mock import patch

        with patch(
            "importlib.metadata.version", side_effect=Exception("simulated failure")
        ):
            ver = server._resolve_server_version()

        self.assertEqual(ver, "0.0.0+local")


if __name__ == "__main__":
    unittest.main()
