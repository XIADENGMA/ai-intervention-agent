"""feat-custom-sound (mining-cycle-1 §3.4) — 自定义通知音效上传契约。

背景
----
对标 mcp-feedback-enhanced v2.6.0 "Built-in multiple sound effects, custom
audio upload support, volume control"。本仓库之前只有内置音效，缺自定义
上传路径。

本 cycle 实现：
- ``notification-manager.js``：``saveCustomSoundFromFile`` /
  ``loadCustomSoundFromStorage`` / ``hasCustomSound`` / ``getCustomSoundMeta``
  / ``clearCustomSound`` 一组 API
- ``playSound(null)`` 默认 dispatch 到 ``'custom'``（如果 audioBuffers
  里有），否则 ``'default'``
- ``web_ui.html``：通知设置 section 新增 file picker / Test / Remove
- ``settings-manager.js::_wireCustomSoundControls``：把 UI 三 control 接到
  notification-manager；reset 时也清自定义音效

本测试套件锁 7 层 invariant，避免任何一层 silent drift。
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
JS_NM = (
    REPO_ROOT
    / "src"
    / "ai_intervention_agent"
    / "static"
    / "js"
    / "notification-manager.js"
)
JS_SM = (
    REPO_ROOT
    / "src"
    / "ai_intervention_agent"
    / "static"
    / "js"
    / "settings-manager.js"
)
HTML = REPO_ROOT / "src" / "ai_intervention_agent" / "templates" / "web_ui.html"
CSS = REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "css" / "main.css"
LOC_EN = REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "locales" / "en.json"
LOC_ZH_CN = (
    REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "locales" / "zh-CN.json"
)


def _read(p: Path) -> str:
    assert p.is_file(), f"缺失文件 {p}"
    return p.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 1. notification-manager.js API surface
# ---------------------------------------------------------------------------


class TestNotificationManagerApiSurface(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.src = _read(JS_NM)

    def test_storage_key_and_limit_constants_present(self) -> None:
        # localStorage key 必须 versioned；防止未来引入 v2 schema 时静默覆盖
        self.assertIn("CUSTOM_SOUND_LS_KEY = 'aiia.notif.customSound.v1'", self.src)
        # 700KB 上限保证 base64 后仍在 localStorage 5MB 配额内有充足余量
        self.assertRegex(
            self.src,
            r"CUSTOM_SOUND_MAX_BYTES\s*=\s*700\s*\*\s*1024",
            "上限必须 = 700KB（base64 ~933KB，留 4MB+ 余量）",
        )

    def test_mime_whitelist_covers_common_audio_formats(self) -> None:
        for mime in (
            "audio/mpeg",
            "audio/wav",
            "audio/ogg",
            "audio/webm",
            "audio/aac",
            "audio/mp4",
            "audio/flac",
        ):
            self.assertIn(
                f"'{mime}'",
                self.src,
                f"MIME 白名单必须包含 {mime}",
            )

    def test_five_public_methods_present(self) -> None:
        for sig in (
            r"hasCustomSound\s*\(\s*\)\s*\{",
            r"getCustomSoundMeta\s*\(\s*\)\s*\{",
            r"async\s+loadCustomSoundFromStorage\s*\(\s*\)\s*\{",
            r"async\s+saveCustomSoundFromFile\s*\(\s*file\s*\)\s*\{",
            r"clearCustomSound\s*\(\s*\)\s*\{",
        ):
            self.assertRegex(
                self.src,
                sig,
                f"NotificationManager 必须暴露方法签名 {sig}",
            )


# ---------------------------------------------------------------------------
# 2. saveCustomSoundFromFile 的错误码契约
# ---------------------------------------------------------------------------


class TestSaveErrorCodes(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.src = _read(JS_NM)

    def test_error_codes_all_returned(self) -> None:
        # 这些 error code 是 UI 层翻译 i18n key 的桥梁。任何一个被悄悄改名都
        # 会导致用户看到 'unknown' fallback。
        body_m = re.search(
            r"async\s+saveCustomSoundFromFile\s*\(\s*file\s*\)\s*\{(?P<body>[\s\S]*?)\n  \}",
            self.src,
        )
        self.assertIsNotNone(body_m, "找不到 saveCustomSoundFromFile 函数体")
        assert body_m is not None
        body = body_m.group("body")
        for code in (
            "no_file",
            "invalid_mime",
            "too_large",
            "read_failed",
            "storage_failed",
            "decode_failed",
        ):
            self.assertIn(
                f"'{code}'",
                body,
                f"saveCustomSoundFromFile 必须能返回 error code {code!r}",
            )


# ---------------------------------------------------------------------------
# 3. playSound 默认 dispatch 到 'custom' (如果存在)
# ---------------------------------------------------------------------------


class TestPlaySoundDispatch(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.src = _read(JS_NM)

    def test_play_sound_default_param_is_null(self) -> None:
        # 改成 null 是 §3.4 的核心改动：null 时 dispatch 到 'custom' fallback
        # 'default'；其它显式参数（'default' / 'custom'）保持原语义
        self.assertRegex(
            self.src,
            r"async\s+playSound\s*\(\s*soundName\s*=\s*null,",
            "playSound 第一参数默认值必须改为 null（让 null 触发 dispatch）",
        )

    def test_play_sound_dispatches_to_custom_when_present(self) -> None:
        # 找到 ``audioBuffers.has('custom') ? 'custom' : 'default'``
        self.assertRegex(
            self.src,
            r"audioBuffers\.has\(['\"]custom['\"]\)\s*\?\s*['\"]custom['\"]\s*:\s*['\"]default['\"]",
            "playSound 必须按 audioBuffers.has('custom') 三元 dispatch",
        )


# ---------------------------------------------------------------------------
# 4. initAudio 会 await loadCustomSoundFromStorage
# ---------------------------------------------------------------------------


class TestInitAudioLoadsCustom(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.src = _read(JS_NM)

    def test_init_audio_calls_load_custom(self) -> None:
        body_m = re.search(
            r"async\s+initAudio\s*\(\s*\)\s*\{(?P<body>[\s\S]*?)\n  \}",
            self.src,
        )
        self.assertIsNotNone(body_m)
        assert body_m is not None
        body = body_m.group("body")
        self.assertIn(
            "loadCustomSoundFromStorage",
            body,
            "initAudio 必须 await loadCustomSoundFromStorage 让上次上传的音效在 init 时立即可用",
        )


# ---------------------------------------------------------------------------
# 5. HTML 包含上传 / 测试 / 清除 三个 control + i18n attribute
# ---------------------------------------------------------------------------


class TestHtmlControls(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.src = _read(HTML)

    def test_file_input_present(self) -> None:
        self.assertRegex(
            self.src,
            r'id="custom-sound-input"',
            "必须有 file picker input#custom-sound-input",
        )
        self.assertIn(
            'accept="audio/*"',
            self.src,
            "file picker 必须限定 accept=audio/* 引导用户选音频文件",
        )

    def test_three_buttons_present(self) -> None:
        for ctrl_id in (
            "custom-sound-test",
            "custom-sound-clear",
            "custom-sound-status",
        ):
            self.assertIn(
                f'id="{ctrl_id}"',
                self.src,
                f"必须有 #{ctrl_id}",
            )

    def test_i18n_data_attributes_present(self) -> None:
        # 这是 i18n.js 自动翻译的钩子；缺一个就让某个按钮永远显示英文 fallback
        for key in (
            "settings.customSound.label",
            "settings.customSound.upload",
            "settings.customSound.test",
            "settings.customSound.clear",
            "settings.customSound.notUploaded",
        ):
            self.assertIn(
                f'data-i18n="{key}"',
                self.src,
                f'HTML 必须含 data-i18n="{key}" 才能 runtime 翻译',
            )


# ---------------------------------------------------------------------------
# 6. settings-manager.js wiring + reset 清理
# ---------------------------------------------------------------------------


class TestSettingsManagerWiring(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.src = _read(JS_SM)

    def test_wire_function_present(self) -> None:
        self.assertRegex(
            self.src,
            r"_wireCustomSoundControls\s*\(",
            "settings-manager 必须有 _wireCustomSoundControls 把 UI 接到 NM",
        )

    def test_reset_clears_custom_sound(self) -> None:
        # resetSettings 必须包含 ``notificationManager.clearCustomSound()``
        body_m = re.search(
            r"resetSettings\s*\(\s*\)\s*\{(?P<body>[\s\S]*?)\n  \}",
            self.src,
        )
        self.assertIsNotNone(body_m)
        assert body_m is not None
        body = body_m.group("body")
        self.assertIn(
            "clearCustomSound",
            body,
            "resetSettings 必须调 clearCustomSound 让 reset 语义完整",
        )

    def test_wire_handles_three_event_types(self) -> None:
        body_m = re.search(
            r"_wireCustomSoundControls\s*\(\s*\)\s*\{(?P<body>[\s\S]*?)\n  \}",
            self.src,
        )
        self.assertIsNotNone(body_m)
        assert body_m is not None
        body = body_m.group("body")
        for handler_pat in (
            r'fileInput\.addEventListener\(\s*["\']change["\']',
            r'testBtn\.addEventListener\(\s*["\']click["\']',
            r'clearBtn\.addEventListener\(\s*["\']click["\']',
        ):
            self.assertRegex(
                body,
                handler_pat,
                f"_wireCustomSoundControls 必须有 handler 匹配 {handler_pat}",
            )


# ---------------------------------------------------------------------------
# 7. CSS + i18n locale parity
# ---------------------------------------------------------------------------


class TestCssAndLocales(unittest.TestCase):
    def test_css_has_custom_sound_classes(self) -> None:
        css = _read(CSS)
        for cls in (
            ".custom-sound-row",
            ".custom-sound-status",
            ".custom-sound-input",
            ".upload-btn-label",
            ".custom-sound-btn",
            ".custom-sound-btn-danger",
        ):
            self.assertIn(
                cls,
                css,
                f"CSS 必须含选择器 {cls}",
            )

    def test_css_respects_reduced_motion(self) -> None:
        css = _read(CSS)
        # 按钮过渡必须在 prefers-reduced-motion 时被关掉，保 a11y
        m = re.search(
            r"prefers-reduced-motion[\s\S]*?\.custom-sound-btn\s*\{[\s\S]*?transition:\s*none",
            css,
        )
        if not m:
            # 允许更宽松写法：检查 ``.upload-btn-label,\n  .custom-sound-btn`` 联合规则
            self.assertRegex(
                css,
                r"prefers-reduced-motion[\s\S]*?\.(upload-btn-label|custom-sound-btn)[\s\S]*?transition:\s*none",
                "CSS 必须在 prefers-reduced-motion 时关掉按钮 transition",
            )

    def test_en_locale_has_all_keys(self) -> None:
        en = _read(LOC_EN)
        for key in (
            '"label"',
            '"upload"',
            '"uploadTitle"',
            '"test"',
            '"clear"',
            '"uploaded"',
            '"notUploaded"',
        ):
            self.assertIn(key, en, f"en.json 内 settings.customSound 必须含 {key}")
        for err in (
            '"invalidMime"',
            '"tooLarge"',
            '"storageFailed"',
            '"decodeFailed"',
        ):
            self.assertIn(err, en, f"en.json::settings.customSound.errors 必须含 {err}")

    def test_zh_cn_locale_has_all_keys(self) -> None:
        zh = _read(LOC_ZH_CN)
        # 必含 customSound 字串本体 + 至少 3 个 error code
        self.assertIn('"customSound"', zh)
        self.assertIn('"invalidMime"', zh)
        self.assertIn('"tooLarge"', zh)
        self.assertIn('"decodeFailed"', zh)


if __name__ == "__main__":
    unittest.main()
