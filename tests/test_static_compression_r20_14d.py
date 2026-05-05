"""R20.14-D 静态资源 gzip 预压缩测试。

覆盖目标
========

锁定两个层面：

A. ``scripts/precompress_static.py``（构建期工具）
   - 对 ``static/css``、``static/js``、``static/locales`` 三个目录里的大文件
     生成 ``.gz`` 副本；
   - 跳过小文件（< 4 KB）、已压缩格式（.png/.woff2 等）、和已经新鲜的 .gz；
   - ``--clean`` 模式删除 .gz；
   - ``--check`` 模式 exit 1 if 任意文件 stale；
   - 脚本是 idempotent 的（重复跑产出 byte-identical 输出，因为 mtime=0）。

B. ``web_ui_routes/static.py`` 的 ``_send_with_optional_gzip`` 协商器
   - ``Accept-Encoding: gzip`` 且 ``.gz`` sibling 存在 → 发预压缩文件 +
     ``Content-Encoding: gzip`` 头 + 原 Content-Type；
   - 其它情况（不接受 gzip / 没 .gz / IO 异常）→ 原文件 fallback；
   - 任何响应都打 ``Vary: Accept-Encoding`` 给 CDN / 中间缓存看；
   - serve_css / serve_js / serve_locales / serve_lottie 都接到这个协商器。

不覆盖（且为什么）
==================

- ``flask-compress`` 自身的行为 —— 那是上游库，已有自己的测试套；
- 真实 HTTP 客户端的 gzip 解码 —— 浏览器 / curl 早证明可用，过度测试无收益；
- 与 flask-compress 并存的双重压缩防御 —— flask-compress 本身在
  ``after_request`` 看到 ``Content-Encoding`` 已设置时就跳过，是它的契约。
"""

from __future__ import annotations

import gzip
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from unittest.mock import MagicMock

import scripts.precompress_static as precompress
from web_ui_routes.static import (
    _client_accepts_gzip,
    _send_with_optional_gzip,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


class TestShouldCompress(unittest.TestCase):
    """``_should_compress`` 的边界条件：跳过小文件、跳过已压缩扩展名。"""

    def test_skips_small_files(self) -> None:
        with TemporaryDirectory() as tmp:
            p = Path(tmp) / "tiny.js"
            p.write_bytes(b"x" * 100)
            should, reason = precompress._should_compress(p)
            self.assertFalse(should)
            self.assertEqual(reason, "skipped_small")

    def test_skips_already_compressed_extensions(self) -> None:
        with TemporaryDirectory() as tmp:
            for ext in [".gz", ".png", ".woff2", ".jpg", ".webp"]:
                p = Path(tmp) / f"big{ext}"
                p.write_bytes(b"x" * 10000)
                should, reason = precompress._should_compress(p)
                self.assertFalse(should, f"{ext} 应该被跳过")
                self.assertEqual(reason, "skipped_ext")

    def test_compresses_eligible_text_files(self) -> None:
        with TemporaryDirectory() as tmp:
            p = Path(tmp) / "main.js"
            p.write_bytes(b"function noop() {}\n" * 1000)
            should, reason = precompress._should_compress(p)
            self.assertTrue(should)
            self.assertEqual(reason, "compressed")


class TestCompressFile(unittest.TestCase):
    """``compress_file``：写盘原子性、idempotent、no-gain 反检。"""

    def test_creates_gz_sibling(self) -> None:
        with TemporaryDirectory() as tmp:
            p = Path(tmp) / "main.js"
            p.write_bytes(b"console.log('hello');\n" * 500)
            r = precompress.compress_file(p)
            self.assertEqual(r.action, "compressed")
            self.assertTrue(p.with_suffix(".js.gz").exists())
            self.assertGreater(r.original_size, r.compressed_size)
            self.assertGreater(r.saved_pct, 0)

    def test_gz_content_round_trips(self) -> None:
        with TemporaryDirectory() as tmp:
            p = Path(tmp) / "data.json"
            payload = b'{"hello": "world"}\n' * 1000
            p.write_bytes(payload)
            precompress.compress_file(p)
            gz = p.with_suffix(".json.gz")
            decompressed = gzip.decompress(gz.read_bytes())
            self.assertEqual(decompressed, payload, "gzip round-trip 必须 byte-perfect")

    def test_idempotent_with_mtime_zero(self) -> None:
        # ``compress_file`` 用 ``gzip.compress(..., mtime=0)``，重复跑应得到
        # byte-identical 输出 —— 这个 invariant 让 CI ``--check`` 可靠。
        with TemporaryDirectory() as tmp:
            p = Path(tmp) / "main.js"
            p.write_bytes(b"x" * 10000)
            precompress.compress_file(p)
            first = p.with_suffix(".js.gz").read_bytes()
            # 强制重新压缩（删 .gz 让 _is_fresh 判 stale）
            p.with_suffix(".js.gz").unlink()
            precompress.compress_file(p)
            second = p.with_suffix(".js.gz").read_bytes()
            self.assertEqual(first, second, "mtime=0 让两次压缩输出 byte-identical")

    def test_skips_when_gz_already_fresh(self) -> None:
        with TemporaryDirectory() as tmp:
            p = Path(tmp) / "main.js"
            p.write_bytes(b"x" * 10000)
            r1 = precompress.compress_file(p)
            self.assertEqual(r1.action, "compressed")
            r2 = precompress.compress_file(p)
            self.assertEqual(
                r2.action,
                "skipped_fresh",
                "已新鲜的 .gz 不应被重压（避免 CI mtime 漂移）",
            )

    def test_recompresses_when_source_newer(self) -> None:
        import os
        import time

        with TemporaryDirectory() as tmp:
            p = Path(tmp) / "main.js"
            p.write_bytes(b"x" * 10000)
            precompress.compress_file(p)
            gz = p.with_suffix(".js.gz")
            # 把 .gz 的 mtime 拨到过去，模拟「源文件已更新」
            old = gz.stat().st_mtime - 100
            os.utime(gz, (old, old))
            time.sleep(0.01)
            p.write_bytes(b"y" * 10000)
            r = precompress.compress_file(p)
            self.assertEqual(r.action, "compressed", "源比 .gz 新时必须重压")

    def test_skips_when_no_gain(self) -> None:
        # 边界：随机字节（已经 high-entropy）gzip 后通常比原文件大。
        # 此时不应留下一个比原文件还大的 .gz 副本。
        with TemporaryDirectory() as tmp:
            p = Path(tmp) / "random.bin.css"  # .css 让 _should_compress 通过
            # 用 ``os.urandom`` 模拟：gzip 通常会膨胀 ~0.03%
            import os

            p.write_bytes(os.urandom(8192))
            r = precompress.compress_file(p)
            # 要么 skipped_no_gain，要么 compressed（urandom 偶尔运气好压得动）
            self.assertIn(r.action, ("skipped_no_gain", "compressed"))
            if r.action == "skipped_no_gain":
                self.assertFalse(
                    p.with_suffix(".css.gz").exists(),
                    "no_gain 路径必须不写 .gz 文件，不能误导 serve_* 协商",
                )


class TestCleanDir(unittest.TestCase):
    """``--clean`` 模式：删除 .gz，保留源文件。"""

    def test_clean_removes_only_gz(self) -> None:
        with TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "main.js").write_bytes(b"// js")
            (d / "main.js.gz").write_bytes(b"\x1f\x8b\x08\x00")  # gzip magic
            (d / "main.css").write_bytes(b"/* css */")
            (d / "data.json.gz").write_bytes(b"\x1f\x8b\x08\x00")

            results = precompress.clean_dir(d)
            self.assertEqual(len(results), 2)
            self.assertTrue(all(r.action == "cleaned" for r in results))
            # 源文件仍在
            self.assertTrue((d / "main.js").exists())
            self.assertTrue((d / "main.css").exists())
            # .gz 都没了
            self.assertFalse((d / "main.js.gz").exists())
            self.assertFalse((d / "data.json.gz").exists())

    def test_clean_on_missing_dir_is_safe(self) -> None:
        # 防御性：目录不存在时 clean 应返回空列表，不 raise
        results = precompress.clean_dir(Path("/non/existent/path"))
        self.assertEqual(results, [])


class TestRunIntegration(unittest.TestCase):
    """``run()`` 端到端：扫多个目录、汇总 results。"""

    def test_run_scans_multiple_directories(self) -> None:
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            css = base / "css"
            js = base / "js"
            css.mkdir()
            js.mkdir()
            (css / "main.css").write_bytes(b"body { color: red; }" * 1000)
            (js / "app.js").write_bytes(b"console.log('hi');" * 1000)
            # 一个不该被压的
            (js / "small.js").write_bytes(b"// tiny")

            out = precompress.run(directories=[css, js], verbose=False)
            actions = [r.action for r in out["results"]]
            self.assertIn("compressed", actions)
            self.assertIn("skipped_small", actions)
            self.assertTrue((css / "main.css.gz").exists())
            self.assertTrue((js / "app.js.gz").exists())
            self.assertFalse((js / "small.js.gz").exists())

    def test_run_check_mode_does_not_write(self) -> None:
        with TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "main.js").write_bytes(b"x" * 10000)
            out = precompress.run(directories=[d], check=True)
            actions = [r.action for r in out["results"]]
            self.assertIn(
                "needs_compress",
                actions,
                "check 模式必须报告 needs_compress 而不是真的写 .gz",
            )
            self.assertFalse((d / "main.js.gz").exists(), "check 模式不应写盘")

    def test_main_check_returns_1_when_stale(self) -> None:
        with TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "main.js").write_bytes(b"x" * 10000)
            rc = precompress._main(["--check", "--dir", str(d)])
            self.assertEqual(rc, 1, "check 模式发现 stale 时必须 exit 1（CI gate 用）")

    def test_main_check_returns_0_when_all_fresh(self) -> None:
        # R21.4：``--check`` 同时验证 gzip 和 br 两份产物，所以 setup 必须把
        # 两种副本都备齐才能让 ``_main(["--check"])`` 返 0。R20.14-D 时代只造
        # ``.gz`` 就够了；保留这条测试是验证「fresh 路径全绿时 _main 返 0」
        # 的契约，不是验 R20.14-D 的 single-encoding 行为。
        with TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "main.js").write_bytes(b"x" * 10000)
            precompress.compress_file(d / "main.js")
            if precompress.BROTLI_AVAILABLE:
                precompress.compress_file_br(d / "main.js")
            rc = precompress._main(["--check", "--dir", str(d)])
            self.assertEqual(rc, 0)


class TestClientAcceptsGzip(unittest.TestCase):
    """``_client_accepts_gzip``：解析 Accept-Encoding 的最小逻辑。"""

    def _req(self, accept_encoding: str | None) -> object:
        # 不用 Flask 真的起 app，构造一个有 ``.headers`` 字典的极简 mock
        m = MagicMock()
        m.headers = MagicMock()
        m.headers.get = MagicMock(return_value=accept_encoding or "")
        return m

    def test_gzip_token_accepted(self) -> None:
        self.assertTrue(_client_accepts_gzip(self._req("gzip")))
        self.assertTrue(_client_accepts_gzip(self._req("gzip, deflate, br")))
        self.assertTrue(_client_accepts_gzip(self._req("br, gzip")))

    def test_wildcard_accepted(self) -> None:
        # ``Accept-Encoding: *`` 在 RFC 7231 里表示「我接受任何」
        self.assertTrue(_client_accepts_gzip(self._req("*")))
        self.assertTrue(_client_accepts_gzip(self._req("identity, *")))

    def test_q_value_ignored_simple_form(self) -> None:
        # 我们简化解析：``gzip;q=0.5`` 仍然被识别为支持 gzip
        # （仅当 ``gzip;q=0`` 才理论上应该被拒，但实践中浏览器极少这么发）
        self.assertTrue(_client_accepts_gzip(self._req("gzip;q=0.5")))

    def test_no_gzip_token(self) -> None:
        self.assertFalse(_client_accepts_gzip(self._req("br")))
        self.assertFalse(_client_accepts_gzip(self._req("deflate")))
        self.assertFalse(_client_accepts_gzip(self._req("")))
        self.assertFalse(_client_accepts_gzip(self._req(None)))


class TestSendWithOptionalGzip(unittest.TestCase):
    """``_send_with_optional_gzip``：协商正确性 + Vary 头处理。

    我们通过 Flask test_client 真实跑路由：``WebFeedbackUI`` 起一份 app，
    在 ``static/js`` 下放一个临时 .js + .gz 副本，然后 GET 它，验证响应。
    """

    @classmethod
    def setUpClass(cls) -> None:
        # 准备一个临时 static/js fixture：放一个真实的 .js + 真实 .gz 副本
        cls.tmpdir = TemporaryDirectory()
        cls.js_dir = Path(cls.tmpdir.name) / "static" / "js"
        cls.js_dir.mkdir(parents=True)
        js_content = b"console.log('hello');" * 100
        (cls.js_dir / "fixture.js").write_bytes(js_content)
        gz_content = gzip.compress(js_content, compresslevel=9, mtime=0)
        (cls.js_dir / "fixture.js.gz").write_bytes(gz_content)
        # 不带 .gz 的另一个文件，验证 fallback
        (cls.js_dir / "no_gz.js").write_bytes(js_content)
        cls.original_content = js_content
        cls.compressed_content = gz_content

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmpdir.cleanup()

    def _make_app(self) -> Any:
        # 极简 Flask app，仅注册测试用路由
        from flask import Flask

        app = Flask(__name__)

        @app.route("/static/js/<filename>")
        def serve_js(filename: str) -> Any:
            return _send_with_optional_gzip(
                self.js_dir, filename, mimetype="application/javascript"
            )

        return app

    def test_gzip_accepted_returns_compressed_with_correct_headers(self) -> None:
        app = self._make_app()
        client = app.test_client()
        resp = client.get("/static/js/fixture.js", headers={"Accept-Encoding": "gzip"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers.get("Content-Encoding"), "gzip")
        # Content-Type 必须是 JS，不是 application/gzip
        self.assertEqual(
            resp.headers.get("Content-Type", "").split(";")[0],
            "application/javascript",
        )
        # Vary 必须包含 Accept-Encoding
        self.assertIn("Accept-Encoding", resp.headers.get("Vary", ""))
        # body 必须是预压缩的字节，不是原始 JS
        self.assertEqual(resp.data, self.compressed_content)
        # 反向验证：解压后等于原文
        self.assertEqual(gzip.decompress(resp.data), self.original_content)

    def test_no_gzip_in_accept_encoding_returns_uncompressed(self) -> None:
        app = self._make_app()
        client = app.test_client()
        resp = client.get("/static/js/fixture.js", headers={"Accept-Encoding": "br"})
        self.assertEqual(resp.status_code, 200)
        self.assertNotEqual(resp.headers.get("Content-Encoding"), "gzip")
        self.assertEqual(resp.data, self.original_content)
        # 即使没用 gzip，Vary 仍要打（CDN 才能正确分桶）
        self.assertIn("Accept-Encoding", resp.headers.get("Vary", ""))

    def test_no_gz_sibling_falls_back_to_uncompressed(self) -> None:
        # client 接受 gzip，但 .gz sibling 不存在 → 透明 fallback
        app = self._make_app()
        client = app.test_client()
        resp = client.get("/static/js/no_gz.js", headers={"Accept-Encoding": "gzip"})
        self.assertEqual(resp.status_code, 200)
        # flask-compress 在测试 app 里没启，所以 Content-Encoding 应为 None
        self.assertNotEqual(resp.headers.get("Content-Encoding"), "gzip")
        self.assertEqual(resp.data, self.original_content)


class TestStaticRoutesIntegration(unittest.TestCase):
    """端到端：``WebFeedbackUI`` 真起来，``serve_*`` 路由消费 .gz。

    用 repo 真实的 ``static/js`` 目录（precompress_static.py 已经把 .gz 都
    生成好了），通过 test_client 验证。
    """

    def setUp(self) -> None:
        # 锁定 R20.14-D 实现成立的前提：``static/js/`` 至少要有一个 .gz 存在
        # （precompress_static.py 已跑过）。如果没有 .gz，整个测试族都没意义。
        gz_files = list((REPO_ROOT / "static" / "js").glob("*.js.gz"))
        if not gz_files:
            self.skipTest(
                "static/js/*.js.gz 缺失；先跑 "
                "`uv run python scripts/precompress_static.py`"
            )
        self.sample_gz = gz_files[0]
        # 派生原文件名
        self.sample_basename = self.sample_gz.name.removesuffix(".gz")

    def _make_ui(self) -> Any:
        from web_ui import WebFeedbackUI

        return WebFeedbackUI(prompt="test", port=0)

    def test_serve_js_sends_gz_when_accept_encoding_gzip(self) -> None:
        ui = self._make_ui()
        client = ui.app.test_client()
        resp = client.get(
            f"/static/js/{self.sample_basename}",
            headers={"Accept-Encoding": "gzip"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            resp.headers.get("Content-Encoding"),
            "gzip",
            f"GET /static/js/{self.sample_basename} with Accept-Encoding: gzip 必须返回预压缩",
        )
        # body 是预压缩字节
        self.assertEqual(resp.data, self.sample_gz.read_bytes())

    def test_serve_js_decompresses_to_match_original(self) -> None:
        ui = self._make_ui()
        client = ui.app.test_client()
        resp = client.get(
            f"/static/js/{self.sample_basename}",
            headers={"Accept-Encoding": "gzip"},
        )
        decompressed = gzip.decompress(resp.data)
        original = (REPO_ROOT / "static" / "js" / self.sample_basename).read_bytes()
        self.assertEqual(
            decompressed,
            original,
            "预压缩 .gz 解压后必须与原文 byte-identical（precompress 逻辑正确性）",
        )

    def test_serve_js_no_accept_encoding_returns_uncompressed(self) -> None:
        ui = self._make_ui()
        client = ui.app.test_client()
        # 显式不带 Accept-Encoding，让 _client_accepts_gzip 走否定分支。
        # ``flask-compress`` 在 ``WebFeedbackUI`` 里启用，但它只在
        # ``Accept-Encoding`` 包含 gzip 时才压缩，不会和我们的协商打架。
        resp = client.get(
            f"/static/js/{self.sample_basename}",
            headers={"Accept-Encoding": "identity"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertNotEqual(
            resp.headers.get("Content-Encoding"),
            "gzip",
            "identity-only 客户端不应收到 gzip body",
        )

    def test_serve_locales_route_exists_and_returns_json(self) -> None:
        # R20.14-D 新增的 /static/locales/<filename>.json 路由
        ui = self._make_ui()
        client = ui.app.test_client()
        resp = client.get(
            "/static/locales/en.json", headers={"Accept-Encoding": "gzip"}
        )
        self.assertEqual(resp.status_code, 200)
        # 必须是 JSON Content-Type（哪怕走的是 .gz 路径）
        self.assertIn(
            "application/json",
            resp.headers.get("Content-Type", ""),
            "locales 路由必须返回 application/json，不是 application/gzip",
        )

    def test_serve_locales_rejects_non_json(self) -> None:
        ui = self._make_ui()
        client = ui.app.test_client()
        resp = client.get("/static/locales/evil.txt")
        self.assertEqual(
            resp.status_code,
            404,
            "locales 路由必须只接受 .json，避免意外暴露其他扩展名",
        )

    def test_vary_header_set_on_compressed_response(self) -> None:
        ui = self._make_ui()
        client = ui.app.test_client()
        resp = client.get(
            f"/static/js/{self.sample_basename}",
            headers={"Accept-Encoding": "gzip"},
        )
        self.assertIn(
            "Accept-Encoding",
            resp.headers.get("Vary", ""),
            "Vary: Accept-Encoding 必须打，否则 CDN 会跨客户端错误分桶",
        )


class TestSourceInvariants(unittest.TestCase):
    """源码不变量：避免后续重构悄悄打回这层优化。"""

    STATIC_PATH = REPO_ROOT / "web_ui_routes" / "static.py"
    PRECOMP_PATH = REPO_ROOT / "scripts" / "precompress_static.py"

    def test_static_uses_optional_gzip_helper(self) -> None:
        src = self.STATIC_PATH.read_text(encoding="utf-8")
        # serve_css / serve_js / serve_locales / serve_lottie 必须使用新 helper
        for route in ("serve_css", "serve_js", "serve_locales", "serve_lottie"):
            idx = src.find(f"def {route}")
            self.assertGreaterEqual(idx, 0, f"{route} 路由不应被删")
            body = src[idx : idx + 2500]
            self.assertIn(
                "_send_with_optional_gzip",
                body,
                f"{route} 必须用 _send_with_optional_gzip 协商；"
                "纯 send_from_directory 会丢掉 R20.14-D 的预压缩收益",
            )

    def test_precompress_uses_mtime_zero(self) -> None:
        # idempotent / reproducible build 依赖 mtime=0
        src = self.PRECOMP_PATH.read_text(encoding="utf-8")
        self.assertIn(
            "mtime=0",
            src,
            "precompress 必须用 mtime=0 让两次跑产出 byte-identical 输出",
        )

    def test_precompress_min_size_threshold_documented(self) -> None:
        src = self.PRECOMP_PATH.read_text(encoding="utf-8")
        self.assertIn(
            "MIN_SIZE_BYTES",
            src,
            "MIN_SIZE_BYTES 阈值必须显式配置，让 reviewer 一眼看到「为什么有些文件没被压」",
        )

    def test_precompress_skip_extensions_includes_gz(self) -> None:
        # 防御：SKIP_EXTENSIONS 必须包含 .gz，否则会出现 .gz.gz 嵌套
        src = self.PRECOMP_PATH.read_text(encoding="utf-8")
        self.assertIn('".gz"', src, "SKIP_EXTENSIONS 必须包含 .gz 防嵌套")

    def test_static_helper_sets_vary_header(self) -> None:
        src = self.STATIC_PATH.read_text(encoding="utf-8")
        idx = src.find("def _send_with_optional_gzip")
        self.assertGreaterEqual(idx, 0)
        body = src[idx : idx + 2500]
        self.assertIn(
            "Accept-Encoding",
            body,
            "_send_with_optional_gzip 必须设置 Vary: Accept-Encoding",
        )
        self.assertIn(
            "Vary",
            body,
            "Vary 头必须显式设置，CDN 才能跨 Accept-Encoding 正确分桶",
        )


class TestRepoBaselineGzPresence(unittest.TestCase):
    """smoke：repo 里至少一个 ``static/js/*.js.gz`` 实际存在。

    这条测试是「precompress_static.py 必须在 repo 落地后真的被运行过一次」
    的兜底；如果 .gz 文件被 .gitignore 排除掉了，本测试会立刻报错。
    """

    def test_at_least_one_gz_in_static_js(self) -> None:
        gz_files = list((REPO_ROOT / "static" / "js").glob("*.js.gz"))
        self.assertGreater(
            len(gz_files),
            0,
            "static/js/ 必须至少有一个 .js.gz；"
            "若是新 clone 的 repo，跑 ``uv run python scripts/precompress_static.py`` 生成；"
            "若是 .gitignore 把它们删了，需要把规则改成允许 .gz",
        )

    def test_largest_gz_is_smaller_than_source(self) -> None:
        # 找 static/js/ 下最大的 .gz，断言它的大小确实小于源
        gz_files = list((REPO_ROOT / "static" / "js").glob("*.js.gz"))
        if not gz_files:
            self.skipTest("没 .gz 可校验")
        for gz in gz_files:
            source = gz.with_suffix("")  # foo.js.gz → foo.js
            if not source.exists():
                continue
            self.assertLess(
                gz.stat().st_size,
                source.stat().st_size,
                f"{gz.name} 比源文件大 —— 该 .gz 应该被删掉，"
                "compress_file 的 no_gain 反检逻辑可能没有正确生效",
            )


if __name__ == "__main__":
    unittest.main()
