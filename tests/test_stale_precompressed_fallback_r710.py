"""R710 回归护栏：过期的 .br/.gz 预压缩副本必须回退到源文件。

背景（R709 验证过程中被真实咬到）：

``_send_with_optional_gzip`` 此前挑选压缩副本只查 ``is_file()``。
源文件更新而 ``.br``/``.gz`` 未重建的窗口期（dev 改代码只跑
minify 没跑 precompress、部署产物不完整），支持 Brotli 的浏览器会
拿到**旧内容**——而 URL 带着新的 ``?v=<mtime>`` 版本号 +
``Cache-Control: public, max-age=31536000, immutable``，旧字节被钉死
在浏览器缓存里长达一年，之后修好 ``.br`` 也无法自愈（URL 不变不再
发请求）。实测表现：R709 的 JS 修复已在磁盘与 identity 响应中，但
浏览器反复加载到无修复的旧代码。

R710 契约：压缩副本 mtime **不旧于**源文件才允许使用；过期副本直接
回退 identity 源文件——宁可这一次不压缩，也绝不把陈旧字节配着新版本
号发出去。
"""

from __future__ import annotations

import gzip
import os
import unittest
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from ai_intervention_agent.web_ui_routes.static import _send_with_optional_gzip


def _make_app(js_dir: Path) -> Any:
    from flask import Flask

    app = Flask(__name__)

    @app.route("/static/js/<filename>")
    def serve_js(filename: str) -> Any:
        return _send_with_optional_gzip(
            js_dir, filename, mimetype="application/javascript"
        )

    return app


class TestStaleCompressedFallback(unittest.TestCase):
    """副本过期 → identity；副本新鲜 → 压缩。"""

    def _write_fixture(
        self, js_dir: Path, *, gz_older_than_source: bool
    ) -> tuple[bytes, bytes]:
        source = b"console.log('fresh source');" * 200
        stale = b"console.log('stale compiled');" * 200
        js_path = js_dir / "fixture.js"
        gz_path = js_dir / "fixture.js.gz"
        js_path.write_bytes(source)
        gz_path.write_bytes(gzip.compress(stale, compresslevel=9, mtime=0))
        now = js_path.stat().st_mtime
        if gz_older_than_source:
            # .gz 落后源文件 100 秒（minify 后没跑 precompress 的窗口）
            os.utime(gz_path, (now - 100, now - 100))
        else:
            os.utime(gz_path, (now + 100, now + 100))
        return source, gzip.compress(stale, compresslevel=9, mtime=0)

    def test_stale_gz_falls_back_to_identity_source(self) -> None:
        with TemporaryDirectory() as tmp:
            js_dir = Path(tmp)
            source, _stale_gz = self._write_fixture(js_dir, gz_older_than_source=True)
            client = _make_app(js_dir).test_client()
            with closing(
                client.get(
                    "/static/js/fixture.js",
                    headers={"Accept-Encoding": "gzip"},
                )
            ) as resp:
                self.assertEqual(resp.status_code, 200)
                self.assertNotEqual(resp.headers.get("Content-Encoding"), "gzip")
                self.assertEqual(
                    resp.data,
                    source,
                    "过期 .gz 必须回退 identity 源文件，绝不能把旧字节"
                    "配着新版本号发出去（immutable 缓存会钉死一年）",
                )

    def test_fresh_gz_still_served_compressed(self) -> None:
        with TemporaryDirectory() as tmp:
            js_dir = Path(tmp)
            _source, stale_gz = self._write_fixture(js_dir, gz_older_than_source=False)
            client = _make_app(js_dir).test_client()
            with closing(
                client.get(
                    "/static/js/fixture.js",
                    headers={"Accept-Encoding": "gzip"},
                )
            ) as resp:
                self.assertEqual(resp.status_code, 200)
                self.assertEqual(resp.headers.get("Content-Encoding"), "gzip")
                self.assertEqual(resp.data, stale_gz)

    def test_stale_br_skipped_but_fresh_gz_used(self) -> None:
        # br 过期、gz 新鲜 → 跳过 br 用 gz（逐级新鲜度判定）
        with TemporaryDirectory() as tmp:
            js_dir = Path(tmp)
            source = b"console.log('fresh source');" * 200
            js_path = js_dir / "fixture.js"
            js_path.write_bytes(source)
            now = js_path.stat().st_mtime

            br_path = js_dir / "fixture.js.br"
            br_path.write_bytes(b"stale-brotli-bytes")
            os.utime(br_path, (now - 100, now - 100))

            gz_bytes = gzip.compress(source, compresslevel=9, mtime=0)
            gz_path = js_dir / "fixture.js.gz"
            gz_path.write_bytes(gz_bytes)
            os.utime(gz_path, (now + 100, now + 100))

            client = _make_app(js_dir).test_client()
            with closing(
                client.get(
                    "/static/js/fixture.js",
                    headers={"Accept-Encoding": "br, gzip"},
                )
            ) as resp:
                self.assertEqual(resp.status_code, 200)
                self.assertEqual(resp.headers.get("Content-Encoding"), "gzip")
                self.assertEqual(resp.data, gz_bytes)


if __name__ == "__main__":
    unittest.main()
