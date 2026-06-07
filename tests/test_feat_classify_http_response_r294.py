"""R294 invariant: ``_classifyHttpResponse`` helper + 2 个新 i18n keys
让 HTTP 4xx/5xx 响应也精细分类 (cycle-28 R289 spillover lock)。

背景
----
cycle-27 R289 引入 ``_classifyFetchError`` 把 JS-level error (AbortError /
TypeError / SyntaxError) 分成 5 类。但 ``fetch()`` 默认对 HTTP 4xx/5xx
**不抛异常** → ``response.ok == false`` 走 ``else`` 分支，原代码：

.. code-block:: javascript

    } else {
      showStatus(result.message || t("status.submitFailed"), "error");
    }

把所有 HTTP 错误笼统显示 backend ``result.message``。但用户对 401/403
应该"重新登录"而非看 backend message；对 5xx (502/503/504) 应该
"稍后重试"而非看 stack trace。

R294 引入 ``_classifyHttpResponse(response)`` 按 ``status`` 分类:

.. code-block:: text

    status 401 / 403 → "status.unauthorized"      (用户重新登录)
    status 5xx       → "status.serviceUnavailable" (稍后重试)
    其他             → null (调用方按既有 backend message + fallback)

实现位置:

- ``app.js`` line ~1198 新增 ``_classifyHttpResponse(response)`` helper +
  window export
- ``app.js::submitFeedback`` ``else`` 分支：``const httpKey =
  _classifyHttpResponse(response); if (httpKey) ... else fallback``
- ``multi_task.js::closeTask`` ``if (!response.ok)`` 同改造，typeof 兜底
- ``en/zh-CN/zh-TW/_pseudo`` 各加 ``status.unauthorized`` +
  ``status.serviceUnavailable`` 2 个 key
- ``_PRE_RESERVED_KEYS`` + ``_WEB_RESERVED_DYNAMIC`` 加 2 个 key (dynamic
  pattern, R291 同 lineage)
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


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _load_json(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


class TestClassifyHttpResponseHelperDefined(unittest.TestCase):
    """``_classifyHttpResponse`` 必须在 app.js 定义 + window export。"""

    def test_helper_function_defined(self) -> None:
        src = _read(APP_JS)
        self.assertRegex(
            src,
            r"function\s+_classifyHttpResponse\s*\(\s*response\s*\)",
            "app.js 必须定义 function _classifyHttpResponse(response)",
        )

    def test_helper_exported_to_window(self) -> None:
        src = _read(APP_JS)
        self.assertIn(
            "window._classifyHttpResponse = _classifyHttpResponse",
            src,
            "_classifyHttpResponse 必须 export 到 window (multi_task.js 复用)",
        )

    def test_helper_handles_401_403_unauthorized(self) -> None:
        src = _read(APP_JS)
        # 401 || 403 → unauthorized
        self.assertRegex(
            src,
            r"status\s*===\s*401\s*\|\|\s*status\s*===\s*403",
            "_classifyHttpResponse 必须 check status === 401 || status === 403",
        )
        self.assertIn(
            '"status.unauthorized"',
            src,
            "_classifyHttpResponse 必须 return 'status.unauthorized'",
        )

    def test_helper_handles_5xx_service_unavailable(self) -> None:
        src = _read(APP_JS)
        # 5xx range check: status >= 500 && status < 600
        self.assertRegex(
            src,
            r"status\s*>=\s*500\s*&&\s*status\s*<\s*600",
            "_classifyHttpResponse 必须 check status >= 500 && status < 600",
        )
        self.assertIn(
            '"status.serviceUnavailable"',
            src,
            "_classifyHttpResponse 必须 return 'status.serviceUnavailable'",
        )

    def test_helper_returns_null_for_unhandled(self) -> None:
        """非 401/403/5xx 必须 return null，让调用方走 fallback。"""
        src = _read(APP_JS)
        # 函数体内必须有 return null（非 401/403/5xx 兜底）
        # 限定在 _classifyHttpResponse 函数内寻找
        func_match = re.search(
            r"function\s+_classifyHttpResponse[^}]*\}",
            src,
            re.DOTALL,
        )
        self.assertIsNotNone(func_match)
        assert func_match is not None
        self.assertIn(
            "return null",
            func_match.group(0),
            "_classifyHttpResponse 必须 return null 让调用方按 backend message fallback",
        )

    def test_helper_guards_against_null_response(self) -> None:
        """``_classifyHttpResponse(null)`` / ``response.status`` 不是 number 时必须 return null。"""
        src = _read(APP_JS)
        # 寻找 ``if (!response || typeof response.status !== "number")``
        self.assertRegex(
            src,
            r'if\s*\(\s*!response\s*\|\|\s*typeof\s+response\.status\s*!==\s*"number"\s*\)',
            "_classifyHttpResponse 必须 guard null response + non-number status",
        )


class TestSubmitFeedbackUsesHttpHelper(unittest.TestCase):
    """``submitFeedback`` 的 ``else`` 分支必须优先调用 helper。"""

    def test_submit_else_calls_classify_http_response(self) -> None:
        src = _read(APP_JS)
        # 寻找 ``const httpKey = _classifyHttpResponse(response);``
        self.assertRegex(
            src,
            r"const\s+httpKey\s*=\s*_classifyHttpResponse\(response\)",
            "submitFeedback else 分支必须先调用 _classifyHttpResponse",
        )

    def test_submit_else_fallback_preserved(self) -> None:
        """``result.message || t('status.submitFailed')`` fallback 必须保留。"""
        src = _read(APP_JS)
        self.assertRegex(
            src,
            r'result\.message\s*\|\|\s*t\(\s*"status\.submitFailed"\s*\)',
            "submitFeedback else fallback 必须保留 result.message || t('status.submitFailed')",
        )


class TestCloseTaskUsesHttpHelper(unittest.TestCase):
    """``closeTask`` 的 ``if (!response.ok)`` 分支也必须复用 helper (typeof 兜底)。"""

    def test_close_task_has_typeof_classify_http_fallback(self) -> None:
        src = _read(MULTI_TASK_JS)
        # ``typeof window._classifyHttpResponse === "function"``
        self.assertRegex(
            src,
            r'typeof\s+window\._classifyHttpResponse\s*===\s*"function"',
            "closeTask 必须 typeof === 'function' 兜底 window._classifyHttpResponse",
        )

    def test_close_task_uses_classify_http_on_response(self) -> None:
        src = _read(MULTI_TASK_JS)
        # 找 ``classifyHttp(response)`` 调用 (var name 可能是 classifyHttp)
        # 至少 1 处 ``window._classifyHttpResponse`` 或 classifyHttp 调用
        self.assertTrue(
            "classifyHttp(response)" in src or "_classifyHttpResponse(response)" in src,
            "closeTask 必须用 helper(response) 分类，否则会绕过 4xx/5xx 精细化",
        )


class TestNew2I18nKeysPresent(unittest.TestCase):
    """2 个新 i18n keys 必须在 4 个 locale 文件都存在且非空。"""

    NEW_KEYS = ("unauthorized", "serviceUnavailable")
    LOCALE_FILES = (
        "en.json",
        "zh-CN.json",
        "zh-TW.json",
        "_pseudo/pseudo.json",
    )

    def test_all_2_keys_present_in_all_locales(self) -> None:
        for fname in self.LOCALE_FILES:
            data = _load_json(LOCALES_DIR / fname)
            status = data.get("status", {})
            for key in self.NEW_KEYS:
                self.assertIn(key, status, f"{fname} status.{key} missing")
                self.assertTrue(
                    status[key],
                    f"{fname} status.{key} must be non-empty string",
                )

    def test_zh_cn_keys_actually_chinese(self) -> None:
        """zh-CN 翻译必须含至少 3 个 CJK 字符 (防英文 placeholder 漏译)。"""
        data = _load_json(LOCALES_DIR / "zh-CN.json")
        status = data.get("status", {})
        cjk_re = re.compile(r"[\u4e00-\u9fff]")
        for key in self.NEW_KEYS:
            value = status.get(key, "")
            cjk_count = len(cjk_re.findall(value))
            self.assertGreaterEqual(
                cjk_count,
                3,
                f"zh-CN status.{key} = {value!r} 必须含 ≥3 CJK 字符 "
                "(防英文 placeholder 漏译)",
            )

    def test_en_keys_not_identical_to_zh(self) -> None:
        """en 和 zh-CN 翻译不能完全相同 (防漏译 placeholder)。"""
        en = _load_json(LOCALES_DIR / "en.json").get("status", {})
        zh = _load_json(LOCALES_DIR / "zh-CN.json").get("status", {})
        for key in self.NEW_KEYS:
            self.assertNotEqual(
                en.get(key),
                zh.get(key),
                f"en 与 zh-CN status.{key} 不应完全相同（漏译）",
            )

    def test_pseudo_keys_have_bang_markers(self) -> None:
        """pseudo locale 必须含 ``[!! ... !!]`` 标记 (i18n bootstrap 测试)。"""
        data = _load_json(LOCALES_DIR / "_pseudo/pseudo.json")
        status = data.get("status", {})
        for key in self.NEW_KEYS:
            value = status.get(key, "")
            self.assertIn(
                "[!!",
                value,
                f"pseudo locale status.{key} = {value!r} 必须含 [!! ... !!] 标记",
            )
            self.assertIn("!!]", value, "pseudo 必须含闭合 !!]")


class TestExemptionListsUpdatedWithNew2Keys(unittest.TestCase):
    """新 2 个 dynamic key 必须同步加入 test + script 两处豁免清单 (R291 lineage)。"""

    NEW_KEYS = ("status.unauthorized", "status.serviceUnavailable")

    def test_test_reserved_contains_new_keys(self) -> None:
        src = _read(REPO_ROOT / "tests" / "test_runtime_behavior.py")
        for key in self.NEW_KEYS:
            self.assertIn(
                f'"{key}": frozenset',
                src,
                f"test_runtime_behavior._PRE_RESERVED_KEYS 必须有 '{key}': frozenset",
            )

    def test_script_reserved_contains_new_keys(self) -> None:
        src = _read(REPO_ROOT / "scripts" / "check_i18n_orphan_keys.py")
        for key in self.NEW_KEYS:
            self.assertIn(
                f'"{key}"',
                src,
                f"check_i18n_orphan_keys._WEB_RESERVED_DYNAMIC 必须有 '{key}'",
            )


class TestR289R291LineagePreserved(unittest.TestCase):
    """R294 必须保留 R289 既有 helper (_classifyFetchError) + R291 既有 sync 模式。"""

    def test_classify_fetch_error_helper_still_defined(self) -> None:
        src = _read(APP_JS)
        self.assertIn(
            "function _classifyFetchError(error)",
            src,
            "R294 不能砍掉 R289 的 _classifyFetchError helper (互补，不替代)",
        )

    def test_window_classify_fetch_error_still_exported(self) -> None:
        src = _read(APP_JS)
        self.assertIn(
            "window._classifyFetchError = _classifyFetchError",
            src,
            "R294 不能砍掉 R289 的 window._classifyFetchError export",
        )


if __name__ == "__main__":
    unittest.main()
