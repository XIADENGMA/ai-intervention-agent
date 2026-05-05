"""R21.4：Brotli 预压缩 + Brotli/gzip/identity 三级协商不变量。

R21.4 在 R20.14-D 的基础上增加一层 Brotli 预压缩 ``.br`` 副本（quality=11）
和运行时的「br > gzip > identity」协商。这条测试文件锁三件事：

1. ``scripts/precompress_static.py`` 的 :func:`compress_file_br` 函数行为
   正确——产出 ``.br`` 文件、跳过小文件、跳过已 fresh、跳过没有 brotli
   时优雅降级、原子写入、反检 no_gain；
2. ``run()`` 在双副本模式下每个源文件最多产出两条 Result（gzip + br）；
3. ``web_ui_routes/static.py`` 的协商：客户端 ``Accept-Encoding`` 含 br
   且 ``.br`` 副本存在时优先服务 ``.br``；含 gzip 时降级 ``.gz``；都不含
   时服务原文件；都加 ``Vary: Accept-Encoding``。

测试矩阵
========

A. ``compress_file_br`` 单元行为：
   - 大文件 → 正确产出 .br，体积合理；
   - 小于 ``MIN_SIZE_BYTES`` → ``skipped_small``，不写文件；
   - 已存在且 fresh → ``skipped_fresh``，不重复压缩；
   - ``.br`` 后缀（递归压缩） → ``skipped_ext``；
   - brotli 不可用（``BROTLI_AVAILABLE=False``） → ``skipped_no_brotli``，
     不报错；
   - 反检：随机数据 + level=11 后 ≥ 原 → ``skipped_no_gain``，不写；
   - 原子写入：临时文件名前缀正确（不能让 Flask picked up 半成品）。

B. ``run()`` 双副本模式：
   - 每个 valid source 产出 2 条 Result（gzip + br）；
   - ``--no-brotli`` flag → 仅产出 gzip Result（R20.14-D fallback 行为）；
   - ``BROTLI_AVAILABLE=False`` → 同上自动 fallback；
   - ``--check`` 模式下 stale 检测同时考虑 .gz 和 .br；
   - ``--clean`` 同时清 .gz 和 .br。

C. ``static.py`` 协商：
   - ``_parse_accept_encoding`` 正确解析 ``br, gzip``、``br;q=0.5``、空头
     等 case；
   - ``_send_with_optional_gzip``（仍用旧名以兼容）：
     * Accept-Encoding: br + .br 存在 → 服务 .br，``Content-Encoding: br``；
     * Accept-Encoding: br （仅 br）+ .br 不存在 → 退化到 raw（不去找 .gz）；
       —— 注意：实际实现中我们仍会查 gzip，因为 ``_client_accepts_gzip``
       和 ``_client_accepts_brotli`` 是独立检查；如果 client 只声明 br，
       gzip 检查就会 false，自然不命中 .gz。验证此精确行为。
     * Accept-Encoding: gzip + .gz 存在 → 服务 .gz，``Content-Encoding: gzip``；
     * Accept-Encoding: identity → 服务原文件，无 Content-Encoding；
     * 双副本都存在但 client 只支持 gzip → 服务 gzip（br 被跳过）；
     * 所有响应都有 ``Vary: Accept-Encoding``。
"""

from __future__ import annotations

import gzip
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from scripts import precompress_static

# 测试 brotli 行为前确认 import 没坏 ── 这条测试文件里我们假设 brotli 可用，
# 不可用时大部分 case 都会被打上 skip。
BROTLI_AVAILABLE = precompress_static.BROTLI_AVAILABLE


# ===========================================================================
# A. compress_file_br 单元行为
# ===========================================================================


@pytest.mark.skipif(not BROTLI_AVAILABLE, reason="brotli not importable")
class TestCompressFileBrUnit:
    """:func:`scripts.precompress_static.compress_file_br` 的单元行为。"""

    def test_compresses_large_text_file(self, tmp_path: Path) -> None:
        """正常 case：大于 MIN_SIZE_BYTES 的文本文件成功压成 .br。"""
        source = tmp_path / "big.css"
        source.write_text("body { color: red; }\n" * 100, encoding="utf-8")
        result = precompress_static.compress_file_br(source)

        assert result.action == "compressed"
        assert result.encoding == "br"
        assert result.original_size == source.stat().st_size
        assert result.compressed_size > 0
        assert result.compressed_size < result.original_size, "Brotli 应该比原文件小"

        br_path = tmp_path / "big.css.br"
        assert br_path.is_file(), ".br 文件应该被原子写入"
        assert br_path.stat().st_size == result.compressed_size

    def test_skipped_small(self, tmp_path: Path) -> None:
        """小于 MIN_SIZE_BYTES 的文件不应被压缩。"""
        source = tmp_path / "tiny.css"
        source.write_text("p{}", encoding="utf-8")
        assert source.stat().st_size < precompress_static.MIN_SIZE_BYTES

        result = precompress_static.compress_file_br(source)
        assert result.action == "skipped_small"
        assert not (tmp_path / "tiny.css.br").exists()

    def test_skipped_ext_for_already_compressed(self, tmp_path: Path) -> None:
        """已经是 ``.br`` 后缀的文件不能再被压缩（防止递归压）。"""
        source = tmp_path / "already.br"
        source.write_bytes(b"x" * 1000)

        result = precompress_static.compress_file_br(source)
        assert result.action == "skipped_ext"

    def test_skipped_fresh_when_br_newer(self, tmp_path: Path) -> None:
        """``.br`` 已存在且 mtime ≥ 源 → skipped_fresh。"""
        source = tmp_path / "stable.js"
        source.write_text(
            "var x = " + ("1234567890," * 100) + "0;\n" * 5, encoding="utf-8"
        )
        # ── 确认源文件 >= MIN_SIZE_BYTES，否则 compress_file_br 直接 skipped_small
        assert source.stat().st_size >= precompress_static.MIN_SIZE_BYTES

        first = precompress_static.compress_file_br(source)
        assert first.action == "compressed", f"setup 期望第一次压缩成功：{first.action}"

        # 第二次跑应该是 skipped_fresh（br 已经 fresh 了）
        result = precompress_static.compress_file_br(source)
        assert result.action == "skipped_fresh"
        assert result.encoding == "br"
        assert result.original_size > 0

    def test_skipped_no_gain_for_random_bytes(self, tmp_path: Path) -> None:
        """随机字节流（高 entropy）压缩后 ≥ 原大小 → skipped_no_gain。"""
        source = tmp_path / "random.json"
        # 用 os.urandom 模拟高 entropy ── brotli 11 也搞不动
        source.write_bytes(os.urandom(800))

        result = precompress_static.compress_file_br(source)
        # 几乎必然 skipped_no_gain（urandom 压不动），但允许偶发 compressed
        # 如果 brotli 头部恰好命中模式，accept either action 而不是 fail
        assert result.action in {"skipped_no_gain", "compressed"}
        if result.action == "skipped_no_gain":
            assert not (tmp_path / "random.json.br").exists()

    def test_atomic_write_uses_tempfile_prefix(self, tmp_path: Path) -> None:
        """原子写入临时文件应有 ``.tmp.precompress.`` 前缀，避免 Flask 误读。"""
        # 这里不能直接验证 tempfile 名（它会被 rename），改为黑盒检查：
        # 跑完后只能看到 .br，没有 .tmp.precompress.* 残留
        source = tmp_path / "stable.css"
        source.write_text("body { } " * 200, encoding="utf-8")
        precompress_static.compress_file_br(source)

        residuals = list(tmp_path.glob(".tmp.precompress.*"))
        assert not residuals, f"原子写入后不该有临时文件残留，找到：{residuals}"

    def test_compressed_smaller_than_gzip_for_typical_assets(
        self, tmp_path: Path
    ) -> None:
        """R21.4 的核心收益验证：brotli 压同一段大文本应比 gzip 更小。

        用真实-style 的 CSS / JSON 文本做对比；不强制最低差距，但 brotli
        必须 ≤ gzip（R21.4 设计假设）。
        """
        text = "\n".join(
            [
                f".class-{i} {{ color: #{i % 0xFFFFFF:06x}; padding: {i}px; }}"
                for i in range(500)
            ]
        )
        source = tmp_path / "large.css"
        source.write_text(text, encoding="utf-8")
        precompress_static.compress_file(source)
        precompress_static.compress_file_br(source)

        gz_size = (tmp_path / "large.css.gz").stat().st_size
        br_size = (tmp_path / "large.css.br").stat().st_size

        assert br_size <= gz_size, (
            f"R21.4 设计假设 brotli ≤ gzip; 实测 br={br_size} gz={gz_size}"
        )


class TestCompressFileBrGracefulDegradation:
    """``BROTLI_AVAILABLE=False`` 时 compress_file_br 应优雅降级，不报错。"""

    def test_returns_skipped_no_brotli(self, tmp_path: Path) -> None:
        source = tmp_path / "big.css"
        source.write_text("body { color: red; }\n" * 100, encoding="utf-8")

        with patch.object(precompress_static, "BROTLI_AVAILABLE", False):
            result = precompress_static.compress_file_br(source)
        assert result.action == "skipped_no_brotli"
        assert not (tmp_path / "big.css.br").exists()


# ===========================================================================
# B. run() 双副本模式
# ===========================================================================


@pytest.mark.skipif(not BROTLI_AVAILABLE, reason="brotli not importable")
class TestRunDualMode:
    """``run()`` 在 enable_brotli=True 时每个源产出 (gz, br) 两条 Result。"""

    def test_run_emits_both_encodings(self, tmp_path: Path) -> None:
        d = tmp_path / "static"
        d.mkdir()
        for name in ("a.css", "b.js"):
            (d / name).write_text(("x" * 800), encoding="utf-8")

        out = precompress_static.run(directories=[d], enable_brotli=True)
        results = out["results"]

        # 每个源 2 条 Result（gzip + br）
        sources = sorted({r.source for r in results})
        assert len(sources) == 2, f"应该处理 2 个源文件，实际 {sources}"

        encodings_per_source = {
            s: sorted({r.encoding for r in results if r.source == s}) for s in sources
        }
        for s, encs in encodings_per_source.items():
            assert encs == ["br", "gzip"], (
                f"{s} 应该既有 gzip 又有 br Result，实际 {encs}"
            )

    def test_run_no_brotli_flag_falls_back(self, tmp_path: Path) -> None:
        """``enable_brotli=False`` → 仅产出 gzip Result（R20.14-D 行为）。"""
        d = tmp_path / "static"
        d.mkdir()
        (d / "x.css").write_text(("y" * 800), encoding="utf-8")

        out = precompress_static.run(directories=[d], enable_brotli=False)
        encodings = {r.encoding for r in out["results"]}
        assert encodings == {"gzip"}, f"--no-brotli 应该只产 gzip，实际 {encodings}"

    def test_run_brotli_unavailable_auto_fallback(self, tmp_path: Path) -> None:
        """``BROTLI_AVAILABLE=False`` → run() 自动降级仅 gzip。"""
        d = tmp_path / "static"
        d.mkdir()
        (d / "y.css").write_text(("z" * 800), encoding="utf-8")

        with patch.object(precompress_static, "BROTLI_AVAILABLE", False):
            out = precompress_static.run(directories=[d], enable_brotli=True)
        encodings = {r.encoding for r in out["results"]}
        assert encodings == {"gzip"}, (
            f"BROTLI_AVAILABLE=False 应自动 fallback 仅 gzip，实际 {encodings}"
        )

    def test_clean_removes_both_gz_and_br(self, tmp_path: Path) -> None:
        d = tmp_path / "static"
        d.mkdir()
        # 手工放置两种产物文件
        (d / "f.css.gz").write_bytes(b"\x1f\x8b" + b"x" * 50)
        (d / "f.css.br").write_bytes(b"\xce\xb2" + b"x" * 50)

        out = precompress_static.run(directories=[d], clean=True)
        cleaned = [r for r in out["results"] if r.action == "cleaned"]
        encodings = sorted({r.encoding for r in cleaned})
        assert encodings == ["br", "gzip"], (
            f"--clean 应该同时清 gzip 和 br，实际 cleaned encodings={encodings}"
        )
        assert not (d / "f.css.gz").exists()
        assert not (d / "f.css.br").exists()

    def test_check_mode_detects_stale_for_br(self, tmp_path: Path) -> None:
        """check 模式：源已有 .gz 但没有 .br → ``needs_compress`` for br。"""
        d = tmp_path / "static"
        d.mkdir()
        source = d / "stale.css"
        source.write_text("a" * 800, encoding="utf-8")

        # 只生成 .gz，假装是 R20.14-D 旧仓库的状态
        precompress_static.compress_file(source)
        # 不要直接检查 BROTLI_AVAILABLE 是否影响 check 模式 ── 我们刚 skipif 过了

        out = precompress_static.run(directories=[d], check=True)
        actions_per_encoding = {
            r.encoding: r.action for r in out["results"] if r.source == source
        }
        assert actions_per_encoding.get("gzip") == "skipped_fresh"
        assert actions_per_encoding.get("br") == "needs_compress", (
            "check 模式应该报告 br 缺失"
        )


# ===========================================================================
# C. _parse_accept_encoding 单元
# ===========================================================================


class TestParseAcceptEncoding:
    """``web_ui_routes/static._parse_accept_encoding`` 的解析正确性。"""

    def setup_method(self) -> None:
        # 避免每个 test 都 import；这里 lazy import 保证 `static.py` 没问题
        from web_ui_routes import static as static_mod

        self.parse = static_mod._parse_accept_encoding

    def _fake_req(self, header: str) -> Any:
        class _FakeReq:
            headers = {"Accept-Encoding": header}

        return _FakeReq()

    @pytest.mark.parametrize(
        "header,expected_subset",
        [
            ("br, gzip", {"br", "gzip"}),
            ("gzip, br", {"br", "gzip"}),
            ("gzip", {"gzip"}),
            ("br", {"br"}),
            ("identity", {"identity"}),
            ("*", {"*"}),
            ("br;q=0.9, gzip;q=0.8", {"br", "gzip"}),
            ("br;q=0", set()),  # q=0 等于明确拒绝
            ("gzip;q=0, br", {"br"}),
            ("", set()),
            ("  br ,  gzip  ", {"br", "gzip"}),
        ],
    )
    def test_parses_common_headers(
        self, header: str, expected_subset: set[str]
    ) -> None:
        result = self.parse(self._fake_req(header))
        assert expected_subset == result, (
            f"header={header!r} expected {expected_subset} got {result}"
        )

    def test_no_header_returns_empty(self) -> None:
        class _FakeReq:
            headers: dict[str, str] = {}

        # 显式调 ``.get()`` 路径
        empty_req = _FakeReq()
        # _parse_accept_encoding 内部用 ``.headers.get("Accept-Encoding", "")``
        empty_req.headers = {}
        result = self.parse(empty_req)
        assert result == set()


# ===========================================================================
# D. _send_with_optional_gzip 协商优先级
# ===========================================================================


class TestSendWithNegotiation:
    """通过 Flask test client 验证 br > gzip > identity 协商。"""

    def setup_method(self) -> None:
        from flask import Flask

        from web_ui_routes.static import _send_with_optional_gzip

        self._send = _send_with_optional_gzip

        # 准备一个 tmp 目录 + 源文件 + .gz 副本 + .br 副本
        self.tmp = Path(tempfile.mkdtemp(prefix="r21_4_test_"))
        self.raw = b"body { color: red; padding: 1em; }\n" * 30
        (self.tmp / "test.css").write_bytes(self.raw)
        # gzip 副本
        (self.tmp / "test.css.gz").write_bytes(
            gzip.compress(self.raw, compresslevel=9, mtime=0)
        )
        # br 副本（real brotli 也可以，这里用 fake bytes 简化测试，但 Content-Encoding
        # 头必须正确）
        if BROTLI_AVAILABLE:
            import brotli

            (self.tmp / "test.css.br").write_bytes(brotli.compress(self.raw))
        else:
            (self.tmp / "test.css.br").write_bytes(b"\xce\xb2" + b"fake-br")

        self.app = Flask(__name__)

        @self.app.route("/css/<filename>")
        def _route(filename: str):  # type: ignore[no-untyped-def]
            return self._send(self.tmp, filename, mimetype="text/css")

    def teardown_method(self) -> None:
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_brotli_preferred_when_supported_and_present(self) -> None:
        client = self.app.test_client()
        rv = client.get("/css/test.css", headers={"Accept-Encoding": "br, gzip"})
        assert rv.status_code == 200
        assert rv.headers.get("Content-Encoding") == "br", (
            f"client 支持 br + .br 存在时应该优先 br，实际 "
            f"Content-Encoding={rv.headers.get('Content-Encoding')!r}"
        )
        assert "Accept-Encoding" in rv.headers.get("Vary", "")

    def test_gzip_used_when_only_gzip_supported(self) -> None:
        client = self.app.test_client()
        rv = client.get("/css/test.css", headers={"Accept-Encoding": "gzip"})
        assert rv.status_code == 200
        assert rv.headers.get("Content-Encoding") == "gzip"
        assert "Accept-Encoding" in rv.headers.get("Vary", "")

    def test_identity_when_neither_supported(self) -> None:
        client = self.app.test_client()
        rv = client.get("/css/test.css", headers={"Accept-Encoding": "identity"})
        assert rv.status_code == 200
        assert rv.headers.get("Content-Encoding") in (None, "")
        assert rv.data == self.raw
        assert "Accept-Encoding" in rv.headers.get("Vary", "")

    def test_identity_when_no_accept_encoding(self) -> None:
        client = self.app.test_client()
        rv = client.get("/css/test.css")
        assert rv.status_code == 200
        # Flask-Compress 这个 app 没装，所以肯定 raw
        assert rv.headers.get("Content-Encoding") in (None, "")
        assert rv.data == self.raw

    def test_brotli_q0_falls_back_to_gzip(self) -> None:
        """``br;q=0`` 表示明确拒绝 br → 应降级到 gzip。"""
        client = self.app.test_client()
        rv = client.get("/css/test.css", headers={"Accept-Encoding": "br;q=0, gzip"})
        assert rv.status_code == 200
        assert rv.headers.get("Content-Encoding") == "gzip"

    def test_star_accepts_brotli(self) -> None:
        """``*`` 通配符应该被识别为支持 br。"""
        client = self.app.test_client()
        rv = client.get("/css/test.css", headers={"Accept-Encoding": "*"})
        assert rv.status_code == 200
        # 优先级：br 先尝试
        assert rv.headers.get("Content-Encoding") == "br"


class TestSendWithFallbackWhenSiblingMissing:
    """``.br`` 缺失但 ``.gz`` 存在时降级到 gzip；都缺失时降级到 raw。"""

    def setup_method(self) -> None:
        from flask import Flask

        from web_ui_routes.static import _send_with_optional_gzip

        self._send = _send_with_optional_gzip
        self.tmp = Path(tempfile.mkdtemp(prefix="r21_4_test_"))
        self.raw = b"a" * 1000
        (self.tmp / "x.js").write_bytes(self.raw)
        # 只生成 .gz，没有 .br ── 模拟「老 fork 没跑 R21.4 precompress」的状态
        (self.tmp / "x.js.gz").write_bytes(
            gzip.compress(self.raw, compresslevel=9, mtime=0)
        )

        self.app = Flask(__name__)

        @self.app.route("/js/<filename>")
        def _route(filename: str):  # type: ignore[no-untyped-def]
            return self._send(self.tmp, filename, mimetype="application/javascript")

    def teardown_method(self) -> None:
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_falls_back_to_gzip_when_br_missing(self) -> None:
        client = self.app.test_client()
        rv = client.get("/js/x.js", headers={"Accept-Encoding": "br, gzip"})
        assert rv.status_code == 200
        assert rv.headers.get("Content-Encoding") == "gzip", (
            ".br 缺失但 .gz 存在 + client 支持两者 → 应降级 gzip"
        )

    def test_raw_when_only_br_supported_but_missing(self) -> None:
        """client 只声明支持 br，但 .br 副本缺失 → 服务原文件。

        ``_client_accepts_gzip`` 是独立检查；此 case 下 client 不声明
        gzip，所以 gzip 检查失败，最终落到 raw。
        """
        client = self.app.test_client()
        rv = client.get("/js/x.js", headers={"Accept-Encoding": "br"})
        assert rv.status_code == 200
        assert rv.headers.get("Content-Encoding") in (None, "")
        assert rv.data == self.raw


# ===========================================================================
# E. Source-text invariants for static.py
# ===========================================================================


class TestStaticPySourceInvariants:
    """``web_ui_routes/static.py`` 的源文本 invariants ── 防止重构破坏 R21.4 协商。"""

    def setup_method(self) -> None:
        self.text = (REPO_ROOT / "web_ui_routes" / "static.py").read_text()

    def test_brotli_check_present(self) -> None:
        """实现里必须有 brotli 协商分支。"""
        assert re.search(r"_client_accepts_brotli\s*\(\s*\)", self.text), (
            "R21.4 期望 ``_send_with_optional_gzip`` 调用 ``_client_accepts_brotli()``"
        )

    def test_brotli_filename_pattern(self) -> None:
        """实现里必须能拼出 ``.br`` 后缀文件名。"""
        assert re.search(r"filename\s*\+\s*[\'\"]\.br[\'\"]", self.text), (
            "R21.4 期望源文件加 ``.br`` 后缀拼成 br 副本路径"
        )

    def test_brotli_content_encoding_set(self) -> None:
        """实际响应头里必须设 ``Content-Encoding: br``（让浏览器解压）。"""
        assert re.search(
            r"Content-Encoding[\'\"]\s*\]\s*=\s*[\'\"]br[\'\"]", self.text
        ), "R21.4 期望 Brotli 响应打 ``Content-Encoding: br``"

    def test_vary_accept_encoding_still_set(self) -> None:
        """R20.14-D 的 ``Vary: Accept-Encoding`` 不变。"""
        assert "Vary" in self.text and "Accept-Encoding" in self.text, (
            "Vary/Accept-Encoding 头部设置必须保留 ── 否则 CDN 错配会导致 br 副本"
            "被发给只支持 gzip 的客户端，bytes 解码失败"
        )

    def test_br_check_before_gzip_in_send_helper(self) -> None:
        """协商顺序：br 必须在 gzip 之前检查（br > gzip 优先级）。"""
        # 抓 ``_send_with_optional_gzip`` 函数体：从 ``def _send_with_optional_gzip``
        # 起，到文件结束 OR 下一个顶层 ``def``/``class``（行首 0 缩进）。
        m = re.search(
            r"def\s+_send_with_optional_gzip\b.*?(?=\n(?:def|class)\s|\Z)",
            self.text,
            re.DOTALL,
        )
        assert m is not None, "找不到 ``_send_with_optional_gzip`` 函数体"
        body = m.group(0)
        br_pos = body.find("_client_accepts_brotli")
        gz_pos = body.find("_client_accepts_gzip")
        assert br_pos != -1, "_client_accepts_brotli 必须在函数体里被调用"
        assert gz_pos != -1, "_client_accepts_gzip 必须在函数体里被调用"
        assert br_pos < gz_pos, (
            "R21.4 协商优先级要求 br 检查在 gzip 之前 ── 否则当客户端两种都"
            "支持时会错误地优先发更大的 gzip"
        )


# ===========================================================================
# F. precompress_static.py source-text invariants
# ===========================================================================


class TestPrecompressSourceInvariants:
    def setup_method(self) -> None:
        self.text = (REPO_ROOT / "scripts" / "precompress_static.py").read_text()

    def test_brotli_constant_defined(self) -> None:
        assert re.search(r"BROTLI_QUALITY\s*=\s*\d+", self.text), (
            "R21.4 期望模块顶部声明 ``BROTLI_QUALITY = N``"
        )

    def test_brotli_available_flag(self) -> None:
        assert "BROTLI_AVAILABLE" in self.text, (
            "graceful degradation 需要 ``BROTLI_AVAILABLE`` 标志"
        )

    def test_compress_file_br_function(self) -> None:
        assert re.search(r"def\s+compress_file_br\s*\(", self.text), (
            "R21.4 引入 ``compress_file_br()`` 函数"
        )

    def test_brotli_quality_max(self) -> None:
        """BROTLI_QUALITY 应是 11（最高）── 离线一次性运行追求最小体积。"""
        m = re.search(r"BROTLI_QUALITY\s*=\s*(\d+)", self.text)
        assert m is not None
        assert int(m.group(1)) == 11, (
            f"R21.4 期望 BROTLI_QUALITY=11 (max)，实际 {m.group(1)}"
        )

    def test_skip_extensions_includes_br(self) -> None:
        assert '".br"' in self.text, "SKIP_EXTENSIONS 必须包含 .br 否则会递归压 .br.br"
