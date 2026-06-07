"""R280 / cycle-25 (R268/R279 同 class entry-side): ``submitFeedback()``
入口阶段的 DOM 引用必须 null-guard，防止键盘快捷键 + 任务切换并发场景
下抛 TypeError 被 catch 误翻成"网络错误"。

R268 / R279 教训扩展
--------------------

cycle-22 R268 修了 finally 块（exit-side）；cycle-25 R279 修了
``settings-manager.js`` 同 class bug；cycle-25 R280 进一步推广到 **entry
side**——try 块入口立即访问 DOM 元素之前必须 null-guard。

R280 修复目标
-------------

``app.js::submitFeedback()`` 可由 **Ctrl/Cmd+Enter 键盘快捷键** 触发
(``app.js`` line ~1527 keyboard handler)。这意味着：

1. 用户切任务过程中（multi_task.js 渲染中间态）
2. SSE 推送新页面渲染中（``feedback-text`` / ``submit-btn`` 节点重建）
3. 任务 auto-resubmit timeout 触发 ``showNoContentPage()`` 移除编辑器

任一场景都可能让 ``getElementById("feedback-text")`` 返回 ``null``。旧
代码：

  const feedbackText = document.getElementById("feedback-text").value.trim();
  //                                                              ^
  //                                                              ❌ TypeError

被 catch 抓住 → ``showStatus("status.networkError", "error")`` 显示"网络
错误"。**严重误导**：用户开始检查网络/防火墙/代理，实际是 stale DOM。

R280 修复
---------

1. ``feedback-text`` null check → silently abort + ``console.warn`` 留 trace
2. ``submit-btn`` null check → best-effort UI loading state，缺失不阻止 fetch

边界
----

- 反馈不能因 UI loading state 缺失就丢失 → submit-btn 不 abort，只跳过
  ``disabled = true`` 与 ``innerHTML = "submitting..."``
- feedback-text 缺失 → 用户根本不在反馈视图，silently abort
  (continue 试图 fetch 会发空字符串到 ``/api/submit``，污染后端日志)

Invariant 锁定
--------------

1. ``feedback-text`` 必须 null guard + early return
2. ``submit-btn`` 必须 null guard 但 **不能** early return（反馈不能丢）
3. ``R280`` anchor 注释存在

Meta-lint 推广
--------------

cycle-25 R279 meta-lint scan finally 块；cycle-26 候选 meta-lint：
所有 ``async function`` 入口的 DOM 访问必须 null-guard——包括函数体前
6 行的 ``getElementById(...).<prop>``。
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
APP_JS = REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "js" / "app.js"


def _strip_js_comments(src: str) -> str:
    """粗略剥离 ``//`` 与 ``/* ... */`` 注释，保留代码与字符串字面值。
    用于 invariant 检查时让 regex 不误匹配文档/注释里的 bad-pattern 示例。"""
    out: list[str] = []
    i = 0
    n = len(src)
    in_string: str | None = None
    while i < n:
        ch = src[i]
        nxt = src[i + 1] if i + 1 < n else ""
        if in_string:
            if ch == "\\" and i + 1 < n:
                out.append(ch + nxt)
                i += 2
                continue
            if ch == in_string:
                in_string = None
            out.append(ch)
            i += 1
            continue
        if ch in ('"', "'", "`"):
            in_string = ch
            out.append(ch)
            i += 1
            continue
        if ch == "/" and nxt == "/":
            # 行注释
            j = src.find("\n", i)
            if j == -1:
                break
            i = j
            continue
        if ch == "/" and nxt == "*":
            # 块注释
            j = src.find("*/", i + 2)
            if j == -1:
                break
            i = j + 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _extract_function_body(src: str, fn_signature_regex: str) -> str:
    """从源码中提取首次匹配 fn signature 的函数 body (粗略大括号匹配)。"""
    match = re.search(fn_signature_regex, src)
    assert match is not None, f"R280: 找不到函数签名 ``{fn_signature_regex}``"
    start = match.end()
    open_brace = src.find("{", start)
    assert open_brace >= 0, "R280: 函数签名后找不到 ``{``"
    depth = 1
    i = open_brace + 1
    in_string = None
    while i < len(src) and depth > 0:
        ch = src[i]
        if in_string:
            if ch == "\\":
                i += 2
                continue
            if ch == in_string:
                in_string = None
        else:
            if ch in ("'", '"', "`"):
                in_string = ch
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return src[open_brace : i + 1]
        i += 1
    raise AssertionError("R280: function body brace mismatch")


class TestSubmitFeedbackEntryNullCheckR280(unittest.TestCase):
    """R280 #1: ``submitFeedback()`` entry 阶段的 DOM 访问必须 null-guard。"""

    src = APP_JS.read_text(encoding="utf-8")

    def setUp(self) -> None:
        self.body = _extract_function_body(
            self.src, r"async\s+function\s+submitFeedback\s*\(\s*\)\s*"
        )

    def test_feedback_text_null_guard(self) -> None:
        """``feedback-text`` 必须先 null check 再 ``.value.trim()``。"""
        code_only = _strip_js_comments(self.body)
        self.assertNotRegex(
            code_only,
            r'getElementById\(\s*[\'"]feedback-text[\'"]\s*\)\.value',
            "R280 regression: ``submitFeedback()`` 不能直接 "
            '``getElementById("feedback-text").value`` (键盘快捷键 + 任务切换'
            "并发场景下 ``feedback-text`` 可能 null → TypeError 被 catch 翻成"
            '误导性 ``"网络错误"`` toast)',
        )
        # 必须先把 element 拿出来，null check，再访问 .value
        self.assertRegex(
            self.body,
            r"feedbackTextEl\s*=\s*document\.getElementById",
            "R280: 必须先把 ``feedback-text`` 拿到 ``feedbackTextEl`` 局部变量",
        )
        self.assertRegex(
            self.body,
            r"if\s*\(\s*!\s*feedbackTextEl\s*\)",
            "R280: 必须 ``if (!feedbackTextEl) return;`` early-return (避免后续"
            "继续访问 .value 抛 TypeError)",
        )

    def test_feedback_text_early_returns_silently(self) -> None:
        """``feedback-text`` null → early return（不污染网络错误 toast）。"""
        self.assertRegex(
            self.body,
            r"if\s*\(\s*!\s*feedbackTextEl\s*\)\s*\{[\s\S]*?return\s*;",
            "R280: ``feedback-text`` null 必须 early return (silently abort, "
            "不要 fall-through 到 catch 路径)",
        )

    def test_submit_btn_null_guard_in_try_block(self) -> None:
        """``submit-btn`` 必须 null check 但 **不能** early return。"""
        # 在 try 块内必须有 submit-btn null check
        self.assertRegex(
            self.body,
            r'submitBtn\s*=\s*document\.getElementById\(\s*"submit-btn"\s*\)',
            "R280: try 块入口必须把 submit-btn 拿到局部变量 ``submitBtn``",
        )
        self.assertRegex(
            self.body,
            r"if\s*\(\s*submitBtn\s*\)\s*\{",
            "R280: ``submitBtn`` 必须 null check (``if (submitBtn) { ... }``)。"
            "DOM 缺失时 UI loading state 跳过即可，**不能** 因此 abort fetch"
            "(反馈不能因 UI 缺失就丢失)",
        )

    def test_r280_anchor_comment_present(self) -> None:
        """函数体必须有 ``R280`` anchor 注释。"""
        self.assertIn(
            "R280",
            self.body,
            "R280: ``submitFeedback()`` 函数体必须有 ``R280`` anchor 注释 "
            "(让 grep R280 能直接定位修复点)",
        )


class TestR268R279PreservedR280(unittest.TestCase):
    """R280 sanity: R268 (finally) 与 R279 (settings-manager) 修复都还在。"""

    app_src = APP_JS.read_text(encoding="utf-8")

    def test_app_js_r268_finally_still_null_checked(self) -> None:
        """R268 finally 块的 ``if (submitBtn)`` 兜底仍在。"""
        self.assertIn(
            "R268",
            self.app_src,
            "R280 sanity: app.js R268 anchor 仍在",
        )
        self.assertRegex(
            self.app_src,
            r"finally\s*\{[\s\S]{0,800}?if\s*\(\s*submitBtn\s*\)",
            "R280 sanity: app.js submitFeedback finally 块必须仍有 "
            "``if (submitBtn)`` 兜底 (R268 fix preserved)",
        )

    def test_settings_manager_r279_still_present(self) -> None:
        """settings-manager.js R279 修复仍在。"""
        sm_path = (
            REPO_ROOT
            / "src"
            / "ai_intervention_agent"
            / "static"
            / "js"
            / "settings-manager.js"
        )
        sm_src = sm_path.read_text(encoding="utf-8")
        self.assertIn(
            "R279",
            sm_src,
            "R280 sanity: settings-manager.js R279 anchor 仍在",
        )


if __name__ == "__main__":
    unittest.main()
