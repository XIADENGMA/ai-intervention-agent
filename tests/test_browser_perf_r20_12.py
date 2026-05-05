"""R20.12 浏览器运行时优化回归测试

Tests for:
    - R20.12-A: ``templates/web_ui.html`` 把 ``mathjax-loader.js`` 的 ``<script>``
      改成 ``<script defer>``，让脚本不再阻塞 head 解析。
    - R20.12-B: 服务端 ``_read_inline_locale_json`` + Jinja 模板内联 locale，
      让首次 ``i18n.init()`` 不再 fetch 11 KB locale JSON（节省一次 30-80 ms RTT）。
    - R20.12-C: ``static/js/image-upload.js`` 的 ``compressImage`` 改用
      ``createImageBitmap`` 异步解码（fallback 兼容老浏览器），单张大图压缩
      wall time 实测降 ~40-60%（与 ``packages/vscode/webview-ui.js`` 对齐）。

Test strategy (与本仓库现有 R20.x 测试同款 4 轴覆盖):
    - **Source-text invariants**: 直接 grep 模板和 JS 源文件，防止有人重构时无意删
      回 sync mathjax-loader 或重新引入 ``new Image() + ObjectURL`` 同步解码路径。
      不依赖运行时浏览器，可在普通 pytest CI 中跑。
    - **Functional unit**: 直接调用 ``_read_inline_locale_json`` / 调用
      ``_get_template_context()``，验证返回值结构 + 缓存命中 + 失败降级。
    - **End-to-end render**: 用 Flask test client 触发 ``GET /``，断言完整 HTML
      包含 ``<script defer src="/static/js/mathjax-loader.js">`` 和正确转义的
      ``window._AIIA_INLINE_LOCALE`` 注入。
    - **Security**: 验证内联 locale 中的 ``<`` 字符被转义成 ``\\u003c``，
      避免 ``</script>`` 子串提前关闭脚本块（XSS 防御）。

Why these invariants matter:
    - mathjax-loader 改 sync 回去 → head 阻塞 +5-10 ms FCP；
    - inline locale 失活 → 首次 i18n.init 多一次 30-80 ms RTT；
    - createImageBitmap 失活 → 单张大图压缩 +50-200 ms 用户感知。
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WEB_UI_HTML = REPO_ROOT / "templates" / "web_ui.html"
WEB_UI_PY = REPO_ROOT / "web_ui.py"
IMAGE_UPLOAD_JS = REPO_ROOT / "static" / "js" / "image-upload.js"
LOCALE_DIR = REPO_ROOT / "static" / "locales"


def _strip_html_comments(html: str) -> str:
    return re.sub(r"<!--.*?-->", "", html, flags=re.DOTALL)


# --------------------------------------------------------------------------- #
# R20.12-A: mathjax-loader defer
# --------------------------------------------------------------------------- #


class TestMathjaxLoaderDefer(unittest.TestCase):
    """R20.12-A: mathjax-loader.js 必须带 ``defer``，不阻塞 HTML head 解析。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.html = WEB_UI_HTML.read_text(encoding="utf-8")
        cls.html_no_comments = _strip_html_comments(cls.html)

    def test_mathjax_loader_script_has_defer(self) -> None:
        """mathjax-loader.js 标签必须带 ``defer`` 属性。

        若回退到同步加载（无 defer / async），head 解析会阻塞至少 5-10 ms，
        且会延后所有后续 ``defer`` 脚本的下载窗口（虽然现代浏览器有预扫描，
        但首字节时机仍可观测）。
        """
        pattern = re.compile(
            r"""<script[^>]*\bdefer\b[^>]*src=["']/static/js/mathjax-loader\.js["']""",
        )
        match = pattern.search(self.html_no_comments)
        self.assertIsNotNone(
            match,
            msg=(
                "mathjax-loader.js 必须带 `defer` 属性（R20.12-A）。"
                "若回退到 sync，head 解析会被阻塞至少 5-10 ms。"
            ),
        )

    def test_mathjax_loader_appears_before_other_defers(self) -> None:
        """mathjax-loader.js 在 ``defer`` 顺序中必须仍是第一个。

        ``defer`` 脚本按 HTML 出现顺序执行；mathjax-loader.js 设置
        ``window.MathJax`` config + ``window.hasMathContent`` helper，必须
        先于 marked.js / app.js 等可能调用 ``loadMathJaxIfNeeded`` 的脚本执行。
        """
        positions = [
            (
                m.group(1),
                m.start(),
            )
            for m in re.finditer(
                r"""<script[^>]*\bdefer\b[^>]*src=["']/static/js/([^"']+)["']""",
                self.html_no_comments,
            )
        ]
        self.assertTrue(
            positions,
            msg="模板里至少要有一个 defer 脚本（这个测试基础假设）",
        )
        first_defer_name, _ = positions[0]
        self.assertEqual(
            first_defer_name,
            "mathjax-loader.js",
            msg=(
                "mathjax-loader.js 必须是第一个 defer 脚本（R20.12-A 顺序契约）。"
                f"当前第一个 defer 是 `{first_defer_name}` —— "
                "这意味着在它之前执行的脚本无法读到 window.MathJax / "
                "window.hasMathContent 等全局符号。"
            ),
        )


# --------------------------------------------------------------------------- #
# R20.12-B: inline locale JSON
# --------------------------------------------------------------------------- #


class TestInlineLocaleReader(unittest.TestCase):
    """R20.12-B: ``_read_inline_locale_json`` 函数行为契约。

    注意：lru_cache wrapper 在 Python 中实现了描述符协议，会在 instance/class
    access 时绑定 self/cls，所以测试里直接 import 函数本体调用，不走 self.X.
    """

    def setUp(self) -> None:
        from web_ui import _read_inline_locale_json

        # 清缓存，避免被前面的测试污染
        _read_inline_locale_json.cache_clear()

    def _read(self, path: str) -> str | None:
        from web_ui import _read_inline_locale_json

        return _read_inline_locale_json(path)

    def test_existing_locale_returns_compact_json_string(self) -> None:
        """读 ``en.json`` 应该返回紧凑序列化的 JSON 字符串。"""
        path = str(LOCALE_DIR / "en.json")
        result = self._read(path)
        self.assertIsNotNone(result, msg="en.json 存在且应能读取")
        assert result is not None
        # 紧凑序列化：不含 ``": "`` 也不含 ``", "``（默认 dumps 会加空格）
        self.assertNotIn('": "', result, msg="必须用 separators=(',', ':') 紧凑序列化")
        # 内容应能反向解析
        parsed = json.loads(result)
        self.assertIsInstance(parsed, dict)

    def test_zh_cn_locale_keeps_utf8_chars(self) -> None:
        """``zh-CN.json`` 必须用 ``ensure_ascii=False``，保留中文字符不转义。"""
        path = str(LOCALE_DIR / "zh-CN.json")
        result = self._read(path)
        self.assertIsNotNone(result, msg="zh-CN.json 存在且应能读取")
        assert result is not None
        # 中文字符应直接保留 UTF-8，不出现 ``\\u4e2d`` 之类的 ASCII 转义
        self.assertNotRegex(
            result,
            r"\\u[0-9a-fA-F]{4}",
            msg="zh-CN locale 必须保留原 UTF-8 字符，避免 \\uXXXX 转义把字节数翻倍",
        )

    def test_nonexistent_path_returns_none(self) -> None:
        """不存在的文件应优雅降级为 ``None``，让模板跳过内联。"""
        result = self._read(str(LOCALE_DIR / "nonexistent_lang.json"))
        self.assertIsNone(result)

    def test_invalid_json_returns_none(self) -> None:
        """损坏的 JSON 文件返回 ``None``，不抛异常。"""
        import tempfile

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as f:
            f.write("{ this is not valid JSON")
            tmp_path = f.name

        try:
            result = self._read(tmp_path)
            self.assertIsNone(result)
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    def test_non_dict_json_returns_none(self) -> None:
        """JSON 顶层是数组/字符串等非 dict 时也降级为 ``None``。"""
        import tempfile

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as f:
            f.write('["not", "a", "dict"]')
            tmp_path = f.name

        try:
            result = self._read(tmp_path)
            self.assertIsNone(result)
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    def test_lru_cache_hits_on_repeat_call(self) -> None:
        """同一路径多次调用应只读 1 次磁盘（LRU cache 命中）。"""
        from web_ui import _read_inline_locale_json

        _read_inline_locale_json.cache_clear()
        path = str(LOCALE_DIR / "en.json")
        self._read(path)
        self._read(path)
        self._read(path)
        info = _read_inline_locale_json.cache_info()
        self.assertEqual(info.misses, 1, msg="首次调用 miss 1 次")
        self.assertEqual(info.hits, 2, msg="后两次必须 cache 命中")

    def test_lru_cache_capacity_at_least_two_locales(self) -> None:
        """LRU 缓存容量必须 ≥ 2，让 ``en`` + ``zh-CN`` 同时驻留不互相驱逐。"""
        from web_ui import _read_inline_locale_json

        info = _read_inline_locale_json.cache_info()
        self.assertGreaterEqual(
            info.maxsize or 0,
            2,
            msg=(
                "lru_cache(maxsize=...) 必须 ≥ 2，否则 en 和 zh-CN 会互相驱逐，"
                "高频访问下退化成『每次都读盘』。"
            ),
        )


class TestTemplateContextInlineLocale(unittest.TestCase):
    """R20.12-B: ``WebFeedbackUI._get_template_context()`` 必须包含 ``inline_locale_json``。

    Helper 不在 WebFeedbackUI 实例上动态挂属性（避免 ty 静态检查抱怨），改为
    把 mock_config 通过 closure / patch 在测试方法内组装。
    """

    def _build_ctx_with_language(self, language: str) -> dict:
        """创建 WebFeedbackUI 实例 + mock 必需依赖，返回 ``_get_template_context()`` 输出。"""
        from unittest.mock import MagicMock, patch

        from web_ui import WebFeedbackUI

        ui = WebFeedbackUI(
            prompt="bench",
            predefined_options=[],
            task_id=None,
            port=18951,
        )

        mock_config = MagicMock()
        mock_config.get_section.return_value = {"language": language}

        # R26.2: ``_get_template_context`` 现在调用模块级 ``_compute_file_version``
        # 而不是实例方法 ``_get_file_version``——后者保留为公共 API 供其他调用方
        # 使用，但在热路径上被替换。这里 patch 模块级函数让所有 4 次调用都返回稳定值
        # 以便快照比较。
        with (
            patch("web_ui.get_config", return_value=mock_config),
            patch.object(
                WebFeedbackUI,
                "_get_csp_nonce",
                return_value="test-nonce",
            ),
            patch("web_ui._compute_file_version", return_value="v1"),
        ):
            return ui._get_template_context()

    def test_zh_cn_language_includes_inline_locale_json(self) -> None:
        ctx = self._build_ctx_with_language("zh-CN")
        self.assertIn("inline_locale_json", ctx)
        self.assertIsNotNone(
            ctx["inline_locale_json"],
            msg="lang=zh-CN 时必须读到 zh-CN.json 内容",
        )
        # 校验是有效 JSON
        parsed = json.loads(ctx["inline_locale_json"])
        self.assertIsInstance(parsed, dict)

    def test_auto_language_skips_inline_locale_json(self) -> None:
        ctx = self._build_ctx_with_language("auto")
        self.assertIsNone(
            ctx["inline_locale_json"],
            msg=(
                "lang=auto 时 server 没法预知浏览器最终选哪个 locale，"
                "必须返回 None 让前端 fetch 兜底。"
            ),
        )

    def test_en_language_includes_inline_locale_json(self) -> None:
        ctx = self._build_ctx_with_language("en")
        self.assertIsNotNone(ctx["inline_locale_json"])


class TestTemplateInlineLocaleSourceInvariants(unittest.TestCase):
    """R20.12-B: ``templates/web_ui.html`` 必须按契约注入 + 转义 inline locale。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.html = WEB_UI_HTML.read_text(encoding="utf-8")

    def test_template_has_inline_locale_block(self) -> None:
        """模板必须包含 ``{% if inline_locale_json %}`` 注入块。"""
        self.assertIn(
            "inline_locale_json",
            self.html,
            msg="模板必须接收 inline_locale_json context 变量（R20.12-B）",
        )
        self.assertIn(
            "window._AIIA_INLINE_LOCALE",
            self.html,
            msg="模板必须把 locale 注入到 window._AIIA_INLINE_LOCALE 全局",
        )
        self.assertIn(
            "window._AIIA_INLINE_LOCALE_LANG",
            self.html,
            msg="模板必须同时声明 locale 对应的 lang 标识，i18n 才能 registerLocale 正确",
        )

    def test_template_xss_escapes_lt_in_inline_locale(self) -> None:
        """模板必须把 inline locale 中的 ``<`` 转义为 ``\\u003c``，防御 ``</script>`` XSS。"""
        # 找到模板里实际注入 inline_locale_json 的那一行
        match = re.search(
            r"window\._AIIA_INLINE_LOCALE\s*=\s*\{\{\s*inline_locale_json[^}]*\}\}",
            self.html,
        )
        self.assertIsNotNone(
            match,
            msg=(
                "模板必须用 `window._AIIA_INLINE_LOCALE = {{ inline_locale_json... }}` 注入。"
            ),
        )
        assert match is not None
        injection_line = match.group(0)
        self.assertIn(
            ".replace('<', '\\\\u003c')",
            injection_line,
            msg=(
                "inline locale 注入必须用 `.replace('<', '\\u003c')` "
                "防御 `</script>` 子串过早关闭脚本块（XSS 防御标准做法）。"
            ),
        )

    def test_template_inline_locale_block_uses_safe_filter(self) -> None:
        """注入语法必须用 ``|safe``，否则 ``{`` 被自动转义就破坏 JSON。"""
        match = re.search(
            r"window\._AIIA_INLINE_LOCALE\s*=\s*\{\{[^}]*\}\}",
            self.html,
        )
        self.assertIsNotNone(match)
        assert match is not None
        self.assertIn("|safe", match.group(0))


class TestTemplateRendersInlineLocaleE2E(unittest.TestCase):
    """R20.12-B: 真正用 Flask 渲染 GET /，断言 HTML 包含正确的 inline locale。"""

    def _render_root_html(self, language: str) -> str:
        from unittest.mock import MagicMock, patch

        from web_ui import WebFeedbackUI

        ui = WebFeedbackUI(
            prompt="hello",
            predefined_options=[],
            task_id=None,
            port=18952,
        )

        mock_config = MagicMock()
        mock_config.get_section.return_value = {"language": language}

        with patch("web_ui.get_config", return_value=mock_config):
            client = ui.app.test_client()
            response = client.get("/")
            self.assertEqual(response.status_code, 200)
            return response.get_data(as_text=True)

    def test_get_root_renders_inline_locale_for_zh_cn(self) -> None:
        body = self._render_root_html("zh-CN")
        # 必须有 inline locale assignment（lang 标识 = zh-CN）
        self.assertRegex(
            body,
            r'window\._AIIA_INLINE_LOCALE_LANG\s*=\s*"zh-CN"',
            msg="lang=zh-CN 时必须注入 inline locale lang 标识",
        )
        # 必须有 inline locale 数据 assignment
        self.assertRegex(
            body,
            r"window\._AIIA_INLINE_LOCALE\s*=\s*\{",
            msg="lang=zh-CN 时必须注入 inline locale 数据",
        )

    def test_get_root_skips_inline_locale_for_auto(self) -> None:
        body = self._render_root_html("auto")
        # auto 模式：模板的 {% if inline_locale_json %} 假，不应注入实际 assignment
        # 注意：检查 inline locale 模块的 setter 区块（``window._AIIA_INLINE_LOCALE_LANG = "..."``
        # 这种带具体 lang 字符串的赋值），不能简单 grep `_AIIA_INLINE_LOCALE_LANG`，因为
        # 后续的 `if (window._AIIA_INLINE_LOCALE_LANG)` 条件检查在所有模式下都会出现。
        self.assertNotRegex(
            body,
            r'window\._AIIA_INLINE_LOCALE_LANG\s*=\s*"(en|zh-CN|auto)"',
            msg="lang=auto 时不应注入 inline locale lang 赋值（server 不知道浏览器选哪个）",
        )
        self.assertNotRegex(
            body,
            r"window\._AIIA_INLINE_LOCALE\s*=\s*\{",
            msg="lang=auto 时不应注入 inline locale 数据",
        )


# --------------------------------------------------------------------------- #
# R20.12-C: image-upload createImageBitmap
# --------------------------------------------------------------------------- #


class TestImageUploadCreateImageBitmapInvariants(unittest.TestCase):
    """R20.12-C: ``static/js/image-upload.js`` 必须用 ``createImageBitmap`` 异步解码路径。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = IMAGE_UPLOAD_JS.read_text(encoding="utf-8")

    def test_decode_image_source_function_exists(self) -> None:
        """``decodeImageSource(file)`` 必须作为统一解码入口存在。"""
        self.assertRegex(
            self.js,
            r"async\s+function\s+decodeImageSource\s*\(\s*file\s*\)",
            msg=(
                "image-upload.js 必须有 `async function decodeImageSource(file)` "
                "作为统一解码入口（R20.12-C，对齐 packages/vscode/webview-ui.js）。"
            ),
        )

    def test_decode_image_source_prefers_create_image_bitmap(self) -> None:
        """``decodeImageSource`` 内部必须优先尝试 ``createImageBitmap``。"""
        # 提取 decodeImageSource 函数体
        match = re.search(
            r"async\s+function\s+decodeImageSource\s*\([^)]*\)\s*\{(.*?)\n\}\s*\n",
            self.js,
            re.DOTALL,
        )
        self.assertIsNotNone(
            match,
            msg="找不到 decodeImageSource 函数体",
        )
        assert match is not None
        body = match.group(1)
        self.assertIn(
            "createImageBitmap",
            body,
            msg="decodeImageSource 必须先尝试 createImageBitmap（R20.12-C 主路径）",
        )
        self.assertIn(
            "typeof createImageBitmap === 'function'",
            body,
            msg="必须先 typeof 检测 createImageBitmap，避免老浏览器抛 ReferenceError",
        )

    def test_decode_image_source_has_object_url_fallback(self) -> None:
        """``decodeImageSource`` 必须有 ObjectURL fallback 路径，兼容老浏览器。"""
        match = re.search(
            r"async\s+function\s+decodeImageSource\s*\([^)]*\)\s*\{(.*?)\n\}\s*\n",
            self.js,
            re.DOTALL,
        )
        assert match is not None
        body = match.group(1)
        # fallback 是 _loadImageViaObjectURL，让我们检查它存在
        self.assertIn(
            "_loadImageViaObjectURL",
            body,
            msg="decodeImageSource 必须 fallback 到 _loadImageViaObjectURL（兼容 Safari < 14）",
        )

    def test_load_image_via_object_url_helper_exists(self) -> None:
        """``_loadImageViaObjectURL`` helper 必须存在。"""
        self.assertRegex(
            self.js,
            r"function\s+_loadImageViaObjectURL\s*\(\s*file\s*\)",
            msg="_loadImageViaObjectURL helper 必须存在（fallback 路径）",
        )

    def test_compress_image_uses_decode_image_source(self) -> None:
        """``compressImage`` 主流程必须 ``await decodeImageSource(file)``，不再用 ``new Image()``。"""
        match = re.search(
            r"async\s+function\s+compressImage\s*\(\s*file\s*\)\s*\{(.*?)\n\}\s*\n",
            self.js,
            re.DOTALL,
        )
        self.assertIsNotNone(
            match,
            msg="compressImage 必须是 `async function`",
        )
        assert match is not None
        body = match.group(1)
        self.assertIn(
            "await decodeImageSource(file)",
            body,
            msg=(
                "compressImage 必须用 `await decodeImageSource(file)` 而不是直接 "
                "`new Image() + ObjectURL`，否则 R20.12-C 优化退化。"
            ),
        )

    def test_compress_image_no_longer_uses_legacy_img_onload(self) -> None:
        """``compressImage`` 内部不应再有 ``img.onload =`` 这种老路径。

        旧路径（被 R20.12-C 替换掉）：
            const img = new Image()
            img.onload = () => { ... }
            img.src = objectURL

        新路径已通过 ``await decodeImageSource(file)`` 取代，不应残留 ``img.onload``
        和 ``img.onerror`` 的 callback 风格代码。但全局其它函数（比如 thumbnail 渲染）
        仍可能用 ``img.onload``，所以只检查 ``compressImage`` 函数体。
        """
        match = re.search(
            r"async\s+function\s+compressImage\s*\(\s*file\s*\)\s*\{(.*?)\n\}\s*\n",
            self.js,
            re.DOTALL,
        )
        assert match is not None
        body = match.group(1)
        self.assertNotRegex(
            body,
            r"\bimg\.onload\s*=",
            msg=(
                "compressImage 内部不应再用 img.onload callback 风格"
                "（已被 R20.12-C 的 await decodeImageSource 取代）"
            ),
        )

    def test_compress_image_uses_safe_resolve_for_cleanup(self) -> None:
        """``compressImage`` 内部 ``Promise resolve`` 必须包 ``safeResolve`` 调用 ``cleanup()``。

        ``createImageBitmap`` 路径返回的 ImageBitmap 必须显式 ``.close()``，否则浏览器
        会保留 GPU 内存；ObjectURL fallback 路径必须 ``revokeObjectURL``。``safeResolve``
        wrapper 是契约。
        """
        match = re.search(
            r"async\s+function\s+compressImage\s*\(\s*file\s*\)\s*\{(.*?)\n\}\s*\n",
            self.js,
            re.DOTALL,
        )
        assert match is not None
        body = match.group(1)
        self.assertIn(
            "safeResolve",
            body,
            msg=(
                "compressImage 必须用 `safeResolve` wrapper 在 resolve 前调用 cleanup()"
                "（否则 ImageBitmap 不 close / ObjectURL 不 revoke 会泄漏内存）"
            ),
        )
        self.assertIn(
            "decoded.cleanup()",
            body,
            msg="必须在 safeResolve wrapper 中调用 decoded.cleanup() 释放底层资源",
        )

    def test_compress_image_drawimage_uses_decoded_image(self) -> None:
        """``ctx.drawImage`` 必须传 ``decoded.image`` 而不是裸 ``img``。"""
        match = re.search(
            r"async\s+function\s+compressImage\s*\(\s*file\s*\)\s*\{(.*?)\n\}\s*\n",
            self.js,
            re.DOTALL,
        )
        assert match is not None
        body = match.group(1)
        # 必须有 ctx.drawImage(decoded.image, ...)
        self.assertRegex(
            body,
            r"ctx\.drawImage\(\s*decoded\.image",
            msg=(
                "ctx.drawImage 必须传 decoded.image（既能接受 ImageBitmap "
                "也能接受 HTMLImageElement，统一接口）"
            ),
        )
        # 不应残留 ctx.drawImage(img, ...)
        self.assertNotRegex(
            body,
            r"ctx\.drawImage\(\s*img\b",
            msg="不应再用裸 `ctx.drawImage(img, ...)`（R20.12-C 已统一改为 decoded.image）",
        )


# --------------------------------------------------------------------------- #
# R20.12 cumulative: source-level cross-cutting checks
# --------------------------------------------------------------------------- #


class TestR2012CumulativeContract(unittest.TestCase):
    """R20.12 总契约：上述三项优化作为整体不可被任何单点回退。"""

    def test_web_ui_has_read_inline_locale_json_function(self) -> None:
        """``web_ui.py`` 必须保留 ``_read_inline_locale_json`` 模块级函数（带 lru_cache）。"""
        src = WEB_UI_PY.read_text(encoding="utf-8")
        self.assertIn(
            "def _read_inline_locale_json",
            src,
            msg="web_ui.py 必须包含 _read_inline_locale_json 函数（R20.12-B）",
        )
        # 确认装饰器是 @lru_cache（用 maxsize=8 缓存）
        match = re.search(
            r"@lru_cache\(maxsize=\d+\)\s*\ndef\s+_read_inline_locale_json",
            src,
        )
        self.assertIsNotNone(
            match,
            msg=(
                "_read_inline_locale_json 必须用 @lru_cache(maxsize=N) 装饰，"
                "否则每次 GET / 都会读 11 KB JSON 解析。"
            ),
        )

    def test_image_upload_js_does_not_eagerly_use_image_object_url(self) -> None:
        """``image-upload.js`` 顶层 ``compressImage`` 不应直接 ``createObjectURL(file)``
        + ``new Image()`` 同步路径（被 R20.12-C 替换为 decodeImageSource）。

        允许在 ``_loadImageViaObjectURL`` helper 内部继续用（fallback 路径）。
        """
        js = IMAGE_UPLOAD_JS.read_text(encoding="utf-8")
        match = re.search(
            r"async\s+function\s+compressImage\s*\(\s*file\s*\)\s*\{(.*?)\n\}\s*\n",
            js,
            re.DOTALL,
        )
        assert match is not None
        compress_body = match.group(1)
        self.assertNotRegex(
            compress_body,
            r"createObjectURL\s*\(\s*file\s*\)",
            msg=(
                "compressImage 内部不应直接调 createObjectURL(file)"
                "（已被 await decodeImageSource(file) 取代，仅 fallback 才用）"
            ),
        )
        self.assertNotRegex(
            compress_body,
            r"new\s+Image\s*\(\s*\)",
            msg=(
                "compressImage 内部不应直接 `new Image()`"
                "（已统一通过 decodeImageSource 路由）"
            ),
        )


if __name__ == "__main__":
    unittest.main()
