"""R289 invariant: ``_classifyFetchError`` helper + 4 个新 i18n keys 提升
错误消息精细化。

背景
----
cycle-25 R285 §2.2 修复 stale DOM 让"网络错误"误报消失，但根本问题没
解决——任何 catch 块都笼统显示 "网络错误"（5xx、4xx、timeout、JSON
parse 失败、stale DOM TypeError 都一样）。用户看到 "网络错误" 会本能
重试，但如果错误是 5xx 服务端 bug，重试 30 次也不解决；如果是 stale
DOM，应该刷新页面而非重试。

R289 引入分类 helper
-------------------
``app.js`` 暴露 ``window._classifyFetchError(error)``，按
``error.name`` + ``error.message`` 分到 5 个 i18n key:

| error.name      | error.message 特征      | 分类 key                     | 用户应该做的事       |
|-----------------|------------------------|------------------------------|---------------------|
| ``AbortError``  | —                      | ``status.requestTimeout``    | 重试（请求超时）     |
| ``TypeError``   | ``"Failed to fetch"``  | ``status.networkOffline``    | 检查网络             |
| ``SyntaxError`` | —                      | ``status.serverResponseInvalid`` | 联系运维（5xx 返回 HTML）|
| ``TypeError``   | 其他                    | ``status.uiRenderingError``  | 刷新页面             |
| 其他            | —                      | ``status.networkError``      | 通用兜底             |

``submitFeedback()`` (app.js) + ``closeTask()`` (multi_task.js) 两个最
hot 的 catch 块都改用此 helper。

本测试锁住：
1. ``_classifyFetchError`` helper 在 app.js 中定义 + exposed to window
2. 5 个分类规则全部覆盖 (5 条 return path)
3. submitFeedback / multi_task closeTask 的 catch 都用 helper
4. 4 个新 i18n keys 在 4 个 locale 文件中存在且非空
5. zh-CN 必须真中文 / en 必须真英文 / 4 keys 双语都不能空
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
STATIC_JS = REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "js"
APP_JS = STATIC_JS / "app.js"
MULTI_TASK_JS = STATIC_JS / "multi_task.js"
LOCALES_DIR = REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "locales"

NEW_I18N_KEYS = [
    "requestTimeout",
    "networkOffline",
    "serverResponseInvalid",
    "uiRenderingError",
]


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _strip_js_comments(source: str) -> str:
    """剥除 JS 单行/块注释（避免 regex 误命中文档反模式）。"""
    out: list[str] = []
    i = 0
    n = len(source)
    in_string: str | None = None
    in_line = False
    in_block = False
    while i < n:
        ch = source[i]
        nxt = source[i + 1] if i + 1 < n else ""
        if in_line:
            if ch == "\n":
                in_line = False
                out.append(ch)
        elif in_block:
            if ch == "*" and nxt == "/":
                in_block = False
                i += 1
        elif in_string is not None:
            out.append(ch)
            if ch == "\\":
                if i + 1 < n:
                    out.append(source[i + 1])
                    i += 1
            elif ch == in_string:
                in_string = None
        else:
            if ch == "/" and nxt == "/":
                in_line = True
                i += 1
            elif ch == "/" and nxt == "*":
                in_block = True
                i += 1
            elif ch in ('"', "'", "`"):
                in_string = ch
                out.append(ch)
            else:
                out.append(ch)
        i += 1
    return "".join(out)


class TestClassifyFetchErrorHelperDefined(unittest.TestCase):
    """``app.js`` 必须定义 ``_classifyFetchError`` 并暴露到 window。"""

    def setUp(self) -> None:
        self.source = _read(APP_JS)
        self.clean = _strip_js_comments(self.source)

    def test_helper_function_defined(self) -> None:
        self.assertIn(
            "function _classifyFetchError(error)",
            self.clean,
            "app.js 必须定义 ``function _classifyFetchError(error)``"
            "（R289 错误消息分类 helper）",
        )

    def test_helper_exported_to_window(self) -> None:
        self.assertIn(
            "window._classifyFetchError = _classifyFetchError",
            self.clean,
            "_classifyFetchError 必须暴露到 window 让 multi_task.js / "
            "settings-manager.js 等模块复用同一套分类逻辑（避免散落 "
            '"网络错误" 兜底）',
        )

    def test_helper_handles_5_categories(self) -> None:
        """helper 必须按 5 条分类规则 return 不同 key。"""
        # 提取 helper body
        match = re.search(
            r"function\s+_classifyFetchError\(error\)\s*\{(?P<body>.*?)\n\}",
            self.clean,
            re.DOTALL,
        )
        self.assertIsNotNone(
            match,
            "无法定位 _classifyFetchError 函数体（请检查命名 / 函数签名）",
        )
        assert match is not None
        body = match.group("body")
        # 5 条 return path（4 个新 keys + 1 fallback）
        expected_returns = [
            "status.requestTimeout",
            "status.networkOffline",
            "status.serverResponseInvalid",
            "status.uiRenderingError",
            "status.networkError",
        ]
        for key in expected_returns:
            self.assertIn(
                f'"{key}"',
                body,
                f'_classifyFetchError must return `"{key}"` for at least '
                f"one error category (R289 §5-category mapping)",
            )

    def test_helper_dispatches_on_abort_error(self) -> None:
        """AbortError → requestTimeout（fetchWithTimeout 超时场景）。"""
        match = re.search(
            r"function\s+_classifyFetchError\(error\)\s*\{(?P<body>.*?)\n\}",
            self.clean,
            re.DOTALL,
        )
        assert match is not None
        body = match.group("body")
        self.assertIn("AbortError", body, "AbortError 必须显式分类")
        # AbortError 必须返回 requestTimeout
        abort_section = re.search(
            r'name\s*===\s*"AbortError"\s*\)\s*\{[^}]*?return\s+"(status\.\w+)"',
            body,
            re.DOTALL,
        )
        self.assertIsNotNone(
            abort_section,
            "AbortError 分支必须 return 一个 status.* key",
        )
        assert abort_section is not None
        self.assertEqual(
            abort_section.group(1),
            "status.requestTimeout",
            f"AbortError 应该 return status.requestTimeout，实际：{abort_section.group(1)}",
        )


class TestSubmitFeedbackUsesHelper(unittest.TestCase):
    """``submitFeedback()`` 的 catch 块必须用 helper 而非裸 networkError。"""

    def setUp(self) -> None:
        self.clean = _strip_js_comments(_read(APP_JS))

    def test_submit_catch_calls_helper(self) -> None:
        """submitFeedback catch 块必须出现 ``t(_classifyFetchError(error))``。"""
        self.assertRegex(
            self.clean,
            r"showStatus\(\s*t\(\s*_classifyFetchError\(\s*error\s*\)\s*\)",
            'submitFeedback catch 块必须 ``showStatus(t(_classifyFetchError(error)), "error")``，'
            '而非裸 ``t("status.networkError")``。后者会让 5xx / timeout / '
            'stale DOM 错误都显示 "网络错误" 误导用户重试网络',
        )

    def test_submit_catch_no_longer_uses_bare_networkError(self) -> None:
        """submitFeedback catch 块不能再裸用 ``t("status.networkError")``。
        helper 内部会在 fallback 时返回它，但 catch 块直接调 helper。"""
        # 提取 submitFeedback 函数体
        match = re.search(
            r"async\s+function\s+submitFeedback\(\)\s*\{(?P<body>.*?)\n\}",
            self.clean,
            re.DOTALL,
        )
        self.assertIsNotNone(match, "找不到 submitFeedback 函数体")
        assert match is not None
        body = match.group("body")
        # catch 块内不应直接出现 t("status.networkError")（不是经过 helper 的）
        bare_use = re.search(
            r'showStatus\(\s*t\(\s*"status\.networkError"\s*\)',
            body,
        )
        self.assertIsNone(
            bare_use,
            'submitFeedback 函数体内不应再直接 ``t("status.networkError")``，'
            "必须通过 ``t(_classifyFetchError(error))`` 间接拿到分类 key",
        )


class TestCloseTaskUsesHelper(unittest.TestCase):
    """``multi_task.js`` 的 close-task catch 也必须用 helper（typeof 兜底）。"""

    def setUp(self) -> None:
        self.clean = _strip_js_comments(_read(MULTI_TASK_JS))

    def test_close_task_uses_classify_helper(self) -> None:
        """close task catch 块必须 ``window._classifyFetchError`` 或同 helper。"""
        self.assertIn(
            "window._classifyFetchError",
            self.clean,
            "multi_task.js 必须复用 app.js 暴露的 window._classifyFetchError "
            'helper（避免散落 "网络错误" 兜底）',
        )

    def test_close_task_has_typeof_fallback(self) -> None:
        """跨模块调用必须 ``typeof === \"function\"`` 兜底（防 app.js 未加载）。"""
        # 找 typeof window._classifyFetchError === "function" 模式
        self.assertRegex(
            self.clean,
            r'typeof\s+window\._classifyFetchError\s*===\s*["\']function["\']',
            "multi_task.js 引用 window._classifyFetchError 时必须做 typeof "
            '===  "function" 兜底，避免极简加载顺序下抛 TypeError',
        )


class TestNewI18nKeysPresent(unittest.TestCase):
    """4 个新 i18n keys 必须在 4 个 locale 文件中存在且非空。"""

    LOCALE_FILES = ["en.json", "zh-CN.json", "zh-TW.json", "_pseudo/pseudo.json"]

    def _load(self, name: str) -> dict:
        return json.loads((LOCALES_DIR / name).read_text(encoding="utf-8"))

    def test_all_4_keys_present_in_all_locales(self) -> None:
        for locale in self.LOCALE_FILES:
            data = self._load(locale)
            status = data.get("status", {})
            self.assertIsInstance(
                status,
                dict,
                f"{locale} must have a `status` section",
            )
            for key in NEW_I18N_KEYS:
                value = status.get(key)
                self.assertIsInstance(
                    value,
                    str,
                    f"{locale} must have `status.{key}` (str), got {type(value).__name__}",
                )
                assert isinstance(value, str)
                self.assertTrue(
                    value.strip(),
                    f"{locale} `status.{key}` must not be empty",
                )

    def test_zh_keys_actually_chinese(self) -> None:
        """zh-CN 的 4 个新 key 必须真是中文（防复制粘贴 en 文案）。"""
        zh = self._load("zh-CN.json")
        status = zh.get("status", {})
        assert isinstance(status, dict)
        for key in NEW_I18N_KEYS:
            value = status[key]
            cjk_chars = [c for c in value if "\u4e00" <= c <= "\u9fff"]
            self.assertGreaterEqual(
                len(cjk_chars),
                3,
                f"zh-CN status.{key} 应至少包含 3 个 CJK 字符；当前: {value!r}",
            )

    def test_en_keys_not_identical_to_zh(self) -> None:
        """en 和 zh-CN 文案必须不同（防直接复制）。"""
        en = self._load("en.json").get("status", {})
        zh = self._load("zh-CN.json").get("status", {})
        for key in NEW_I18N_KEYS:
            self.assertNotEqual(
                en.get(key),
                zh.get(key),
                f"status.{key} en 和 zh-CN 文案不应相同（应已翻译）",
            )

    def test_pseudo_keys_have_bang_markers(self) -> None:
        """_pseudo/pseudo.json 4 个新 key 必须带 ``[!! ... !!]`` 标记。"""
        pseudo = self._load("_pseudo/pseudo.json").get("status", {})
        for key in NEW_I18N_KEYS:
            value = pseudo.get(key, "")
            self.assertTrue(
                value.startswith("[!! ") and value.endswith(" !!]"),
                f"_pseudo status.{key} 必须被 ``[!! ... !!]`` 包裹"
                f"（pseudo-locale 标记格式）；当前：{value!r}",
            )


class TestExistingNetworkErrorPreserved(unittest.TestCase):
    """``status.networkError`` 仍然必须存在（fallback 路径仍用它）。"""

    def test_network_error_key_preserved(self) -> None:
        for locale in ["en.json", "zh-CN.json", "zh-TW.json"]:
            data = json.loads((LOCALES_DIR / locale).read_text(encoding="utf-8"))
            self.assertIn(
                "networkError",
                data.get("status", {}),
                f"{locale} status.networkError 必须保留（R289 helper fallback 仍用它）",
            )


if __name__ == "__main__":
    unittest.main()
