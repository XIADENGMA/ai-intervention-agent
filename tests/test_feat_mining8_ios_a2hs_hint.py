"""mining-8 Track A — iOS Safari A2HS hint banner 回归测试.

覆盖层级：
  1. JS 模块存在性 + 关键函数 / 常量 (UA 检测 / standalone 检测 /
     dismiss 持久化 / 测试 hook);
  2. CSS — .ios-a2hs-banner 样式块存在 + light/dark 主题分离 +
     prefers-reduced-motion 兜底;
  3. i18n — 4 keys × 3 locales (en / zh-CN / zh-TW) 全部存在;
  4. Flask asset version wiring;
  5. 模板 script registration.
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC_DIR = _REPO_ROOT / "src" / "ai_intervention_agent"
_TEMPLATES_DIR = _SRC_DIR / "templates"
_STATIC_DIR = _SRC_DIR / "static"
_JS_DIR = _STATIC_DIR / "js"
_CSS_DIR = _STATIC_DIR / "css"
_LOCALES_DIR = _STATIC_DIR / "locales"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# §1 JS module
# ---------------------------------------------------------------------------
class TestJsModule(unittest.TestCase):
    def setUp(self) -> None:
        path = _JS_DIR / "ios_a2hs_hint.js"
        self.assertTrue(path.exists(), "ios_a2hs_hint.js 缺失")
        self.js = _read(path)

    def test_storage_key_versioned(self) -> None:
        self.assertIn('"aiia.iosA2hsDismissed.v1"', self.js)

    def test_ua_detection_iphone_ipad_ipod(self) -> None:
        # 必须 case-insensitive match iphone/ipad/ipod
        m = re.search(r"function _isIosSafari\(\) \{.*?\n  \}", self.js, re.DOTALL)
        assert m is not None
        block = m.group(0)
        self.assertIn("iphone|ipad|ipod", block, "UA 必须检测 iPhone/iPad/iPod")

    def test_ipad_desktop_mode_detection(self) -> None:
        # iPad Pro 11+ desktop class Safari fallback
        m = re.search(r"function _isIosSafari\(\) \{.*?\n  \}", self.js, re.DOTALL)
        assert m is not None
        block = m.group(0)
        self.assertIn("MacIntel", block, "必须 detect iPad desktop mode")
        self.assertIn("maxTouchPoints", block)

    def test_excludes_inapp_browsers(self) -> None:
        # iOS 上的 Chrome / Firefox / Edge / Opera (WebKit-based but no A2HS)
        m = re.search(r"function _isIosSafari\(\) \{.*?\n  \}", self.js, re.DOTALL)
        assert m is not None
        block = m.group(0)
        self.assertIn("crios", block, "iOS Chrome (CriOS) 必须排除")
        self.assertIn("fxios", block, "iOS Firefox (FxiOS) 必须排除")
        self.assertIn("edgios", block, "iOS Edge (EdgiOS) 必须排除")

    def test_standalone_detection_two_methods(self) -> None:
        # 旧 webkit navigator.standalone + 新 display-mode matchMedia
        m = re.search(
            r"function _isAlreadyStandalone\(\) \{.*?\n  \}", self.js, re.DOTALL
        )
        assert m is not None
        block = m.group(0)
        self.assertIn("navigator.standalone", block, "必须用旧 webkit API")
        self.assertIn("display-mode: standalone", block, "必须用新 matchMedia API")

    def test_dismiss_persists_permanent_flag(self) -> None:
        m = re.search(r"function _setDismissed\(\) \{.*?\n  \}", self.js, re.DOTALL)
        assert m is not None
        block = m.group(0)
        self.assertIn("dismissed: true", block)
        self.assertIn("dismissed_at", block)
        self.assertIn("schema_version", block)

    def test_show_delay_constant(self) -> None:
        # 1500ms 延迟避免首屏渲染高峰
        self.assertIn("1500", self.js)
        self.assertIn("SHOW_DELAY_MS", self.js)

    def test_double_check_pre_show(self) -> None:
        # _maybeShow 内 setTimeout 回调里二次 check (防 race)
        m = re.search(r"function _maybeShow\(\) \{.*?\n  \}", self.js, re.DOTALL)
        assert m is not None
        block = m.group(0)
        # 二次 check：dismiss / standalone / 已存在 banner
        self.assertIn("_isDismissed()", block)
        self.assertIn("_isAlreadyStandalone()", block)
        self.assertIn("getElementById(BANNER_ID)", block)

    def test_banner_has_aria_dialog(self) -> None:
        m = re.search(r"function _buildBanner\(\) \{.*?\n  \}", self.js, re.DOTALL)
        assert m is not None
        block = m.group(0)
        self.assertIn('"role", "dialog"', block)
        self.assertIn('"aria-labelledby"', block)

    def test_test_hook_exposed(self) -> None:
        self.assertIn("window.__iosA2hsInternal", self.js)
        self.assertIn("STORAGE_KEY", self.js)
        self.assertIn("BANNER_ID", self.js)


# ---------------------------------------------------------------------------
# §2 CSS
# ---------------------------------------------------------------------------
class TestCssStyles(unittest.TestCase):
    def setUp(self) -> None:
        self.css = _read(_CSS_DIR / "main.css")

    def test_banner_style_present(self) -> None:
        self.assertIn(".ios-a2hs-banner {", self.css)
        self.assertIn(".ios-a2hs-banner.ios-a2hs-banner--visible", self.css)
        self.assertIn(".ios-a2hs-banner__title", self.css)
        self.assertIn(".ios-a2hs-banner__desc", self.css)
        self.assertIn(".ios-a2hs-banner__dismiss", self.css)

    def test_position_fixed_bottom(self) -> None:
        m = re.search(r"\.ios-a2hs-banner \{[^}]+\}", self.css, re.DOTALL)
        assert m is not None
        block = m.group(0)
        self.assertIn("position: fixed", block)
        self.assertIn("bottom:", block)

    def test_safe_area_inset_support(self) -> None:
        # iOS notch / home-bar 安全区
        m = re.search(r"\.ios-a2hs-banner \{[^}]+\}", self.css, re.DOTALL)
        assert m is not None
        block = m.group(0)
        self.assertIn("env(safe-area-inset", block, "必须支持 iOS 安全区")

    def test_light_theme_overrides_present(self) -> None:
        self.assertIn('[data-theme="light"] .ios-a2hs-banner', self.css)

    def test_prefers_reduced_motion_disabled_anim(self) -> None:
        # 必须 honor prefers-reduced-motion
        m = re.search(
            r"@media \(prefers-reduced-motion: reduce\) \{[^}]*?\.ios-a2hs-banner[^}]*\}",
            self.css,
            re.DOTALL,
        )
        assert m is not None, "prefers-reduced-motion 必须 disable 上滑动画"

    def test_uses_brand_accent(self) -> None:
        # R697：品牌强调色统一为 Anthropic 陶土橙 217,119,87（原紫色
        # 139,92,246 随 Claude 暖炭主题迁移一并退役）
        m = re.search(r"\.ios-a2hs-banner \{[^}]+\}", self.css, re.DOTALL)
        assert m is not None
        block = m.group(0)
        self.assertIn("217, 119, 87", block, "border 必须用品牌陶土橙 accent")


# ---------------------------------------------------------------------------
# §3 i18n
# ---------------------------------------------------------------------------
_REQUIRED_KEYS = ("title", "desc", "dismissTitle", "dismissAriaLabel")


def _load_locale(name: str) -> dict:
    return json.loads(_read(_LOCALES_DIR / name))


class TestI18nKeys(unittest.TestCase):
    def _assert_block(self, locale: str) -> None:
        data = _load_locale(locale)
        page = data.get("page", {})
        block = page.get("iosA2hs")
        self.assertIsInstance(block, dict, f"{locale} 缺失 page.iosA2hs 块")
        for key in _REQUIRED_KEYS:
            self.assertIn(key, block, f"{locale} 缺失 page.iosA2hs.{key}")
            self.assertTrue(
                isinstance(block[key], str) and block[key].strip(),
                f"{locale} page.iosA2hs.{key} 为空",
            )

    def test_en_block(self) -> None:
        self._assert_block("en.json")

    def test_zh_cn_block(self) -> None:
        self._assert_block("zh-CN.json")

    def test_zh_tw_block(self) -> None:
        self._assert_block("zh-TW.json")

    def test_zh_translated_not_english_passthrough(self) -> None:
        en = _load_locale("en.json")["page"]["iosA2hs"]
        zh = _load_locale("zh-CN.json")["page"]["iosA2hs"]
        for key in _REQUIRED_KEYS:
            self.assertNotEqual(
                en[key],
                zh[key],
                f"zh-CN page.iosA2hs.{key} 未翻译（与英文 fallback 同字）",
            )


# ---------------------------------------------------------------------------
# §4 Flask asset version wiring
# ---------------------------------------------------------------------------
class TestAssetVersionWiring(unittest.TestCase):
    def setUp(self) -> None:
        self.web_ui_py = _read(_SRC_DIR / "web_ui.py")

    def test_ios_a2hs_hint_version_injected(self) -> None:
        self.assertIn('"ios_a2hs_hint_version"', self.web_ui_py)
        self.assertIn('"js" / "ios_a2hs_hint.js"', self.web_ui_py)


# ---------------------------------------------------------------------------
# §5 Template script registration
# ---------------------------------------------------------------------------
class TestTemplateScriptRegistered(unittest.TestCase):
    def setUp(self) -> None:
        self.html = _read(_TEMPLATES_DIR / "web_ui.html")

    def test_script_tag_present(self) -> None:
        self.assertIn("/static/js/ios_a2hs_hint.js", self.html)
        self.assertIn("{{ ios_a2hs_hint_version }}", self.html)


if __name__ == "__main__":
    unittest.main()
