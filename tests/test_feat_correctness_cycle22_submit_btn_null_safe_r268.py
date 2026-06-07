"""correctness-cycle-22 · Track K (R268) · `submitFeedback` finally null deref fix.

背景
----

`app.js::submitFeedback` 是 feedback 提交的主路径，try/catch/finally 结构：

```js
try {
  const submitBtn = document.getElementById("submit-btn");
  submitBtn.disabled = true;
  // ... await fetchWithTimeout (long async)
} catch (error) {
  console.error("Submit failed:", error);
  showStatus(t("status.networkError"), "error");
} finally {
  const submitBtn = document.getElementById("submit-btn");
  submitBtn.disabled = false;          // ← TypeError 如果 null
  if (SUBMIT_BTN_ORIGINAL_HTML !== null) {
    submitBtn.innerHTML = SUBMIT_BTN_ORIGINAL_HTML;  // ← 同
    window.AIIA_I18N.translateDOM(submitBtn);        // ← 同
  }
}
```

await 边界期间可能发生：
- 任务 auto-resubmit timeout → `showNoContentPage()` 把 `#submit-btn`
  整个从 DOM 移除（empty state 没有 submit 按钮）
- 多 task 场景 SSE 重渲染替换节点 → 旧 ID 查找返回 null

`submitBtn.disabled = false` 不做 null check → `TypeError: Cannot set
property 'disabled' of null` → finally 抛错 → 污染整个 submit 流程：
- catch 块里 console.error + showStatus 的 ``status.networkError`` toast
  已经显示给用户
- 但 finally 抛出的 TypeError 会让 await submitFeedback() 的调用者
  收到一个**不同的 error**，覆盖原 catch toast 的状态显示

更严重场景：用户的 feedback 实际**成功提交**（response.ok = true，
showStatus(success)，refreshTasksList 已经把页面切回 empty state，
submit-btn 从 DOM 移除），但 finally 抛 TypeError → 用户看到红色
error toast，以为"提交失败" → 重复提交。

修复
----

`submitBtn` 加 null check 兜底 —— 元素已不在 DOM 时 silently skip
整个 finally body（UI 状态无需 reset，因为按钮本身已经不存在）。

回归契约
--------

3 invariants：
- finally 块 `submitBtn` 必须做 `if (submitBtn) { ... }` null check
- finally 块内不能直接裸写 `submitBtn.disabled = false`
- finally 块内不能直接裸写 `submitBtn.innerHTML = SUBMIT_BTN_ORIGINAL_HTML`

Without these invariants, a routine "let me simplify by removing the
null check, getElementById never returns null in practice" refactor
would silently re-introduce the TypeError swallowing the catch block's
user-facing error toast.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

JS_PATH = (
    Path(__file__).resolve().parent.parent
    / "src"
    / "ai_intervention_agent"
    / "static"
    / "js"
    / "app.js"
)


class TestSubmitFeedbackFinallyNullSafe(unittest.TestCase):
    """R268 · `submitFeedback` finally 块 null check 防御."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = JS_PATH.read_text(encoding="utf-8")
        # 抓 submitFeedback 函数体（到下一个顶层 function 定义或注释段落）
        body_match = re.search(
            r"async\s+function\s+submitFeedback[\s\S]*?(?=\n// 关闭界面|\nasync\s+function\s+closeInterface\b)",
            cls.js,
        )
        cls.body = body_match.group(0) if body_match else ""
        assert cls.body, "找不到 async function submitFeedback 函数体"

    def test_finally_block_has_null_check_guard(self) -> None:
        """finally 块必须有 `if (submitBtn) { ... }` null check."""
        # 抓 finally 块（从 ``} finally {`` 到对应 ``}``）
        finally_match = re.search(
            r"\}\s*finally\s*\{([\s\S]*?)\n  \}\n\}",
            self.body,
        )
        self.assertIsNotNone(finally_match, "找不到 submitFeedback finally 块")
        assert finally_match is not None
        finally_body = finally_match.group(1)
        self.assertRegex(
            finally_body,
            r"if\s*\(\s*submitBtn\s*\)",
            "R268 submitFeedback finally 块缺 if (submitBtn) null check "
            "—— submit-btn 在 await 边界期间可能从 DOM 移除（empty state / "
            "SSE 重渲染），裸调 .disabled / .innerHTML 会抛 TypeError "
            "污染整个 submit 流程",
        )

    def test_finally_does_not_naked_set_disabled(self) -> None:
        """finally 块不能在 null check 外裸写 `submitBtn.disabled = false`."""
        finally_match = re.search(
            r"\}\s*finally\s*\{([\s\S]*?)\n  \}\n\}",
            self.body,
        )
        assert finally_match is not None
        finally_body = finally_match.group(1)
        # 抓 finally 块内 if 块外的代码段（即 if 块之前）
        if_pos = finally_body.find("if (submitBtn)")
        self.assertGreater(
            if_pos,
            0,
            "R268: if (submitBtn) 必须出现于 finally body",
        )
        pre_if = finally_body[:if_pos]
        self.assertNotIn(
            "submitBtn.disabled = false",
            pre_if,
            "R268 finally 块在 if (submitBtn) null check 之外不能裸写 "
            "submitBtn.disabled = false（裸调会抛 TypeError 当 submit-btn "
            "已从 DOM 移除）",
        )

    def test_finally_does_not_naked_set_innerHTML(self) -> None:
        """finally 块不能在 null check 外裸写 `submitBtn.innerHTML = ...`."""
        finally_match = re.search(
            r"\}\s*finally\s*\{([\s\S]*?)\n  \}\n\}",
            self.body,
        )
        assert finally_match is not None
        finally_body = finally_match.group(1)
        if_pos = finally_body.find("if (submitBtn)")
        pre_if = finally_body[:if_pos]
        self.assertNotIn(
            "submitBtn.innerHTML",
            pre_if,
            "R268 finally 块在 if (submitBtn) null check 之外不能裸写 "
            "submitBtn.innerHTML（裸调会抛 TypeError 当 submit-btn 已从 "
            "DOM 移除）",
        )


if __name__ == "__main__":
    unittest.main()
