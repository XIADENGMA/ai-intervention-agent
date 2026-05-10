"""R112 — ``/fonts/`` / ``/icons/`` 路由扩展名白名单防御回归。

背景
----

R112 修复发现：

* ``serve_sounds`` 路由：白名单 ``.mp3 / .wav / .ogg``（拒绝 ``.txt``
  ``.bak`` 等→ 404）
* ``serve_lottie`` 路由：白名单 ``.json``（拒绝其他后缀→ 404）
* ``serve_locale``（``/api/locales/``）路由：白名单 ``.json``
* ``serve_fonts`` / ``serve_icons`` 路由：**完全没白名单**——
  ``send_from_directory`` 仅防路径穿越，不防"任意文件类型对外暴露"

R112 把 fonts / icons 加进白名单家族，与 sounds / lottie / locales 同构：

* fonts：``.woff / .woff2 / .ttf / .otf / .eot / .ttc``
* icons：``.png / .ico / .svg / .webmanifest / .jpg / .jpeg / .gif``

意图：未来如果 ``fonts/`` ``icons/`` 目录里被误放进 ``README.md`` /
``.bak`` / ``.tmp`` 等非目标资源，白名单兜底返回 404，避免意外信息泄露。

测试设计（核心：可反向注入）
----------------------------

简单 ``assertEqual(404)`` 不能区分"白名单 reject"和"文件不存在 404"，
所以必须**真实创建**文件后才能验证白名单。本测试 monkey-patch
``_project_root`` 指向临时目录，里面放置：

* 白名单内文件 (``test.woff2``, ``icon-72.png``)：应能被 serve（200）
* 白名单外文件 (``leaked.txt``, ``README.md``)：白名单应**拒绝**（404）

反向注入验证：移除 R112 ``abort(404)`` 后，``leaked.txt`` 会变成 200
（这才是真 silent leak），证明白名单确实在阻挡而非"碰巧目录不存在"。
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any


class _R112TestBase(unittest.TestCase):
    _port: int = 19112
    _ui: Any = None
    _client: Any = None
    _tmp: tempfile.TemporaryDirectory[str] | None = None
    _tmp_root: Path

    @classmethod
    def setUpClass(cls) -> None:
        from ai_intervention_agent.web_ui import WebFeedbackUI

        cls._tmp = tempfile.TemporaryDirectory()
        cls._tmp_root = Path(cls._tmp.name)

        # 创建白名单内 + 白名单外文件
        fonts_dir = cls._tmp_root / "fonts"
        fonts_dir.mkdir()
        (fonts_dir / "test.woff2").write_bytes(b"fake-woff2-data")
        (fonts_dir / "test.woff").write_bytes(b"fake-woff-data")
        (fonts_dir / "test.ttf").write_bytes(b"fake-ttf-data")
        # 白名单外 — 必须真存在，才能让"反向注入"暴露 silent leak
        (fonts_dir / "leaked.txt").write_text(
            "SECRET_API_KEY=abc123\nDB_PASSWORD=hunter2\n"
        )
        (fonts_dir / "config.bak").write_text("legacy backup data")
        (fonts_dir / "binary").write_bytes(b"\x00\x01\x02")

        icons_dir = cls._tmp_root / "icons"
        icons_dir.mkdir()
        (icons_dir / "icon-72.png").write_bytes(b"fake-png-data")
        (icons_dir / "icon.svg").write_bytes(b"<svg/>")
        (icons_dir / "favicon.ico").write_bytes(b"fake-ico")
        (icons_dir / "manifest.webmanifest").write_text("{}")
        # 白名单外
        (icons_dir / "leaked.txt").write_text(
            "SECRET_TOKEN=xyz\nINTERNAL_NOTE=todo-cleanup\n"
        )
        (icons_dir / "README.md").write_text("# internal docs\nDO NOT SHIP")
        (icons_dir / "script.py").write_text("import os; os.system('rm -rf /')")
        (icons_dir / "image.png.bak").write_bytes(b"backup of image.png")

        cls._ui = WebFeedbackUI(
            prompt="r112-extension-whitelist-test",
            task_id="r112-base",
            port=cls._port,
        )
        # monkey-patch project_root 指向 tmp，让路由读 tmp 文件
        cls._ui._project_root = cls._tmp_root
        cls._ui.app.config["TESTING"] = True
        cls._ui.limiter.enabled = False
        cls._client = cls._ui.app.test_client()

    @classmethod
    def tearDownClass(cls) -> None:
        if cls._tmp is not None:
            cls._tmp.cleanup()


class TestFontsExtensionWhitelistR112(_R112TestBase):
    """``/fonts/<filename>`` 扩展名白名单回归。"""

    def test_woff_allowed_serves_content(self) -> None:
        resp = self._client.get("/fonts/test.woff")
        self.assertEqual(resp.status_code, 200, "白名单内 .woff 应正常 serve")
        self.assertEqual(resp.data, b"fake-woff-data")
        resp.close()

    def test_woff2_allowed_serves_content(self) -> None:
        resp = self._client.get("/fonts/test.woff2")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data, b"fake-woff2-data")
        resp.close()

    def test_ttf_allowed_serves_content(self) -> None:
        resp = self._client.get("/fonts/test.ttf")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data, b"fake-ttf-data")
        resp.close()

    def test_txt_blocked_even_when_file_exists(self) -> None:
        """**核心 R112 反向注入断言**：``leaked.txt`` **真实存在**于
        ``fonts/`` 目录内，没有白名单就会 200 + 泄露内容；R112 白名单必须
        返回 404 防止任何字节泄露。"""
        resp = self._client.get("/fonts/leaked.txt")
        self.assertEqual(
            resp.status_code,
            404,
            "R112 白名单应阻止 .txt（即使 fonts/ 里真有这个文件）",
        )
        self.assertNotIn(
            b"SECRET_API_KEY",
            resp.data,
            "**严重**：响应体不应包含敏感字符串（白名单失效证据）",
        )
        resp.close()

    def test_bak_blocked_even_when_file_exists(self) -> None:
        resp = self._client.get("/fonts/config.bak")
        self.assertEqual(resp.status_code, 404)
        self.assertNotIn(b"legacy backup data", resp.data)
        resp.close()

    def test_no_extension_blocked(self) -> None:
        resp = self._client.get("/fonts/binary")
        self.assertEqual(resp.status_code, 404)
        resp.close()

    def test_uppercase_extension_allowed(self) -> None:
        """大小写不敏感（``.lower()`` 内部规范化），即使文件不存在也确认
        白名单不在入口处拒绝（200 if 文件存在 / 404 if 不存在）。"""
        resp = self._client.get("/fonts/UPPER.WOFF2")
        # 文件不存在 → 404 from send_from_directory，但不是白名单 reject
        # （这一条不能区分，仅作"白名单不会大小写敏感拒绝"的负向断言）
        self.assertEqual(resp.status_code, 404)
        resp.close()


class TestIconsExtensionWhitelistR112(_R112TestBase):
    """``/icons/<filename>`` 扩展名白名单回归。"""

    def test_png_allowed_serves_content(self) -> None:
        resp = self._client.get("/icons/icon-72.png")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data, b"fake-png-data")
        resp.close()

    def test_svg_allowed_serves_content(self) -> None:
        resp = self._client.get("/icons/icon.svg")
        self.assertEqual(resp.status_code, 200)
        resp.close()

    def test_ico_allowed_serves_content(self) -> None:
        resp = self._client.get("/icons/favicon.ico")
        self.assertEqual(resp.status_code, 200)
        resp.close()

    def test_webmanifest_allowed_serves_content(self) -> None:
        """``manifest.webmanifest`` 通过 ``/icons/`` 路由直接拉是现役支持
        模式（见 ``icons/manifest.webmanifest`` 实际文件）。"""
        resp = self._client.get("/icons/manifest.webmanifest")
        self.assertEqual(resp.status_code, 200)
        resp.close()

    def test_txt_blocked_even_when_file_exists(self) -> None:
        """**核心 R112 反向注入断言**：``leaked.txt`` **真实存在**于
        ``icons/`` 目录内，没有白名单就会 200 + 泄露 token；R112 必须返
        回 404。"""
        resp = self._client.get("/icons/leaked.txt")
        self.assertEqual(resp.status_code, 404)
        self.assertNotIn(b"SECRET_TOKEN", resp.data)
        resp.close()

    def test_md_blocked_even_when_file_exists(self) -> None:
        resp = self._client.get("/icons/README.md")
        self.assertEqual(resp.status_code, 404)
        self.assertNotIn(b"DO NOT SHIP", resp.data)
        resp.close()

    def test_py_blocked_even_when_file_exists(self) -> None:
        """``.py`` 源文件——绝不能被 serve（即使路径合法且文件存在）。"""
        resp = self._client.get("/icons/script.py")
        self.assertEqual(resp.status_code, 404)
        self.assertNotIn(b"rm -rf", resp.data)
        resp.close()

    def test_double_extension_blocked_when_last_unsafe(self) -> None:
        """``image.png.bak``：最后一段 ``.bak`` → 必拒绝（防止"伪装成
        png 实则 .bak"的误读取）。"""
        resp = self._client.get("/icons/image.png.bak")
        self.assertEqual(resp.status_code, 404)
        self.assertNotIn(b"backup of image.png", resp.data)
        resp.close()


if __name__ == "__main__":
    unittest.main()
