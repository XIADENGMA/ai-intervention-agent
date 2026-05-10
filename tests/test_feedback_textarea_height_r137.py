"""R137 · Feedback textarea 高度持久化契约测试。

背景
----
``.feedback-textarea`` 已经支持 CSS ``resize: vertical``，用户可以拖
拽调整高度。但每次刷新 / 新会话后高度都会重置回 ``min-height: 180px``
默认值。R137 把高度持久化到 ``localStorage``，下次进 web UI 自动恢
复——对齐 ``mcp-feedback-enhanced`` v2.4.3 "Input Height Memory" 体感。

设计契约（5 个 invariant class，共 18 cases）：

1. **JS 模块文件存在 + 关键常量** — STORAGE_KEY / SCHEMA_VERSION /
   MIN_HEIGHT_PX / MAX_HEIGHT_PX / DEBOUNCE_MS / TARGET_ID 锁定。

2. **API 函数签名** — readPersistedHeight / persistHeight /
   applyPersistedHeight / setupResizeObserver / init 在 source 中可
   见，``window.AIIA_FEEDBACK_TEXTAREA_HEIGHT`` 暴露完整 API。

3. **clamp 与容错** — clamp 防止极端值；persistHeight 拒绝非数字；
   readPersistedHeight 容错（无 / 损坏 / schema 不匹配 / 数值非法）。

4. **HTML 集成** — web_ui.html 引用 ``feedback_textarea_height.js``
   带 ``?v={{ feedback_textarea_height_version }}`` 与 ``defer`` +
   ``nonce``；``_get_template_context`` 返回
   ``feedback_textarea_height_version``。

5. **ResizeObserver 优先 + fallback** — source 内含 ``ResizeObserver``
   primary path + ``mouseup`` / ``touchend`` fallback。
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


JS_PATH = (
    REPO_ROOT
    / "src"
    / "ai_intervention_agent"
    / "static"
    / "js"
    / "feedback_textarea_height.js"
)
HTML_PATH = REPO_ROOT / "src" / "ai_intervention_agent" / "templates" / "web_ui.html"
WEB_UI_PY = REPO_ROOT / "src" / "ai_intervention_agent" / "web_ui.py"


def _read_js() -> str:
    return JS_PATH.read_text(encoding="utf-8")


def _read_html() -> str:
    return HTML_PATH.read_text(encoding="utf-8")


def _read_web_ui_py() -> str:
    return WEB_UI_PY.read_text(encoding="utf-8")


# ----------------------------------------------------------------------------
# 1. 文件 + 关键常量
# ----------------------------------------------------------------------------


class TestModuleFileAndConstants(unittest.TestCase):
    def test_js_file_exists(self) -> None:
        self.assertTrue(
            JS_PATH.exists(),
            "feedback_textarea_height.js 必须存在（R137 模块入口）",
        )

    def test_storage_key_v1(self) -> None:
        # localStorage key 与 R130 quick_phrases 同款命名风格
        self.assertIn(
            'STORAGE_KEY = "aiia.feedbackTextareaHeight.v1"',
            _read_js(),
        )

    def test_schema_version_one(self) -> None:
        self.assertIn("SCHEMA_VERSION = 1", _read_js())

    def test_min_max_height_constants(self) -> None:
        src = _read_js()
        # MIN_HEIGHT_PX 100；MAX_HEIGHT_PX 800
        self.assertIn("MIN_HEIGHT_PX = 100", src)
        self.assertIn("MAX_HEIGHT_PX = 800", src)

    def test_debounce_constant_reasonable(self) -> None:
        # 150ms debounce — 用户拖动停手后写盘
        self.assertIn("DEBOUNCE_MS = 150", _read_js())

    def test_target_id_matches_html(self) -> None:
        # 模块用 document.getElementById(TARGET_ID)，TARGET_ID 必须
        # 与 web_ui.html 中 textarea 的 id 一致（feedback-text）
        self.assertIn('TARGET_ID = "feedback-text"', _read_js())
        self.assertIn('id="feedback-text"', _read_html())


# ----------------------------------------------------------------------------
# 2. API 函数签名
# ----------------------------------------------------------------------------


class TestApiShape(unittest.TestCase):
    def test_read_persisted_height_defined(self) -> None:
        self.assertIn("function readPersistedHeight(", _read_js())

    def test_persist_height_defined(self) -> None:
        self.assertIn("function persistHeight(", _read_js())

    def test_apply_persisted_height_defined(self) -> None:
        self.assertIn("function applyPersistedHeight(", _read_js())

    def test_setup_resize_observer_defined(self) -> None:
        self.assertIn("function setupResizeObserver(", _read_js())

    def test_init_defined(self) -> None:
        self.assertIn("function init(", _read_js())

    def test_window_api_exposed(self) -> None:
        # 公开 API 给测试 + 调试 + 未来扩展
        src = _read_js()
        self.assertIn("window.AIIA_FEEDBACK_TEXTAREA_HEIGHT", src)
        for fn in (
            "readPersistedHeight",
            "persistHeight",
            "applyPersistedHeight",
            "setupResizeObserver",
            "init",
        ):
            self.assertRegex(
                src,
                rf"{fn}:\s*{fn}",
                f"window API 应当暴露 {fn}",
            )


# ----------------------------------------------------------------------------
# 3. clamp 与容错路径
# ----------------------------------------------------------------------------


class TestClampAndGracefulFailures(unittest.TestCase):
    def test_clamp_helper_referenced(self) -> None:
        # 内部 _clamp helper 必须被 readPersistedHeight 与 persistHeight
        # 使用，保证存读两端都在 [MIN, MAX] 范围内
        src = _read_js()
        self.assertIn("function _clamp(", src)
        # 既在 read 路径又在 write 路径调用
        self.assertGreaterEqual(src.count("_clamp("), 3)

    def test_persist_height_rejects_non_number(self) -> None:
        # persistHeight 应当对非数字 / 非有限数字早早返回 false 不写盘
        src = _read_js()
        match = re.search(
            r"function persistHeight\([^)]*\)\s*\{(.*?)\n\s*\}\s*\n",
            src,
            re.DOTALL,
        )
        self.assertIsNotNone(match)
        body = match.group(1) if match else ""
        self.assertIn('typeof height !== "number"', body)
        self.assertIn("Number.isFinite(height)", body)

    def test_read_persisted_height_handles_corrupt_json(self) -> None:
        # try/catch 包 JSON.parse + localStorage.getItem
        src = _read_js()
        match = re.search(
            r"function readPersistedHeight\([^)]*\)\s*\{(.*?)\n\s*\}\s*\n",
            src,
            re.DOTALL,
        )
        self.assertIsNotNone(match)
        body = match.group(1) if match else ""
        self.assertIn("try", body)
        self.assertIn("catch", body)
        self.assertIn("JSON.parse", body)

    def test_read_persisted_height_validates_schema_version(self) -> None:
        src = _read_js()
        self.assertIn("schema_version !== SCHEMA_VERSION", src)

    def test_read_persisted_height_rejects_non_finite(self) -> None:
        src = _read_js()
        # 数值校验：typeof number + Number.isFinite
        self.assertIn('typeof height !== "number"', src)
        self.assertIn("Number.isFinite(height)", src)


# ----------------------------------------------------------------------------
# 4. HTML 集成
# ----------------------------------------------------------------------------


class TestHtmlIntegration(unittest.TestCase):
    def test_html_includes_script_tag_with_version(self) -> None:
        html = _read_html()
        # script 标签须含模块路径 + ?v={{ feedback_textarea_height_version }}
        self.assertRegex(
            html,
            r'src="/static/js/feedback_textarea_height\.js\?v='
            r"\{\{ feedback_textarea_height_version \}\}",
        )

    def test_html_script_has_defer_and_nonce(self) -> None:
        # CSP 兼容 + 不阻塞 main thread
        html = _read_html()
        match = re.search(
            r"<script[^>]*feedback_textarea_height\.js[^>]*>",
            html,
            re.DOTALL,
        )
        self.assertIsNotNone(match)
        tag = match.group(0) if match else ""
        self.assertIn("defer", tag)
        self.assertIn("nonce=", tag)

    def test_template_context_provides_version(self) -> None:
        # web_ui.py _get_template_context 必须新增 feedback_textarea_height_version
        py_src = _read_web_ui_py()
        self.assertIn('"feedback_textarea_height_version"', py_src)
        # 且通过 _compute_file_version 计算（同行 dict literal 形式）
        self.assertRegex(
            py_src,
            r'"feedback_textarea_height_version":\s*_compute_file_version\(',
        )


# ----------------------------------------------------------------------------
# 5. ResizeObserver 优先 + fallback
# ----------------------------------------------------------------------------


class TestResizeObserverWithFallback(unittest.TestCase):
    def test_resize_observer_primary_path(self) -> None:
        src = _read_js()
        self.assertIn('typeof ResizeObserver !== "undefined"', src)
        self.assertIn("new ResizeObserver(", src)
        self.assertIn(".observe(textarea)", src)

    def test_mouseup_touchend_fallback(self) -> None:
        # ResizeObserver 不可用时 fallback 到原生事件
        src = _read_js()
        self.assertIn('addEventListener("mouseup"', src)
        self.assertIn('addEventListener("touchend"', src)

    def test_setup_returns_mode_marker(self) -> None:
        # 返回值结构 {observer, mode}，让单元测试 + 调试能检测当前路径
        src = _read_js()
        self.assertIn('mode: "resize_observer"', src)
        self.assertIn('mode: "mouseup_fallback"', src)


if __name__ == "__main__":
    unittest.main()
