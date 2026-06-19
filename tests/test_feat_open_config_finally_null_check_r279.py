"""R279 / cycle-25 t25-3 (R268 spillover): ``openConfigFileInIde()``
finally 块的 DOM 引用必须 null-guard，防止 settings 重渲染后 stale
reference 抛 TypeError 污染 finally 块吞掉 catch 路径的 error toast。

R268 教训
---------

cycle-22 R268 修复 ``app.js::submitFeedback()`` 的 finally 块：

  finally {
    submitBtn.disabled = false;  // ❌ 旧实现，submit-btn 被 SSE re-render
                                  // 替换节点 → TypeError 污染 finally 块
  }

修复为:

  finally {
    const submitBtn = document.getElementById("submit-btn");
    if (submitBtn) {
      submitBtn.disabled = false;
    }
  }

cycle-25 t25-3 meta-lint scan
-----------------------------

扫所有 ``static/js/*.js`` 里 ``} finally { ... }`` 后 await 跨界的 DOM
mutation 模式。审计结果（6 处 finally）：

| File | Line | Pattern | Verdict |
|------|------|---------|---------|
| i18n.js:161 | seen.delete(value) (Set) | safe (no DOM) |
| i18n.js:1093 | delete _pendingLoads[lang] (module state) | safe |
| settings-manager.js:886 | btn.disabled = (await fetch 之后) | **R279 BUG** |
| settings-manager.js:1007 | document.body.removeChild(ta) (local sync) | safe |
| multi_task.js:1413 | clearTimeout (timer cleanup) | safe |
| multi_task.js:1614 | tasksPollAbortController = null | safe |
| multi_task.js:2463 | setTimeout / dispatchEvent | safe |
| app.js:1221 | submitBtn (R268 已有 null check) | safe (R268 fixed) |
| notification-manager.js:325 | this.permissionRequestPromise = null | safe |

只有 1 处 ``settings-manager.js:886`` 是 R279 的同 class bug。

R279 修复
---------

``openConfigFileInIde()`` 的 finally 块：
  - **旧**: ``btn.disabled = originalDisabled;`` (无 null check)
  - **新**: 重新 ``getElementById`` + null check 兜底

边界场景:
1. 用户在 fetch 期间快速 hideSettings()：``btn`` 仍在 DOM (panel 只 hide 不 unmount)，safe
2. 用户切语言触发 retranslateDOM：``btn`` 不被替换 (只换 textContent)，safe
3. **SSE config-changed → 重 init**：理论上 settings.init() 只 register 一次 (dataset.aiiaWired guard)，DOM 不替换。**但**未来若 cycle-26+ 引入 settings hot-reload，这个 guard 失效，``btn`` reference 会作废。R279 防御性修复 lock 行为。

Invariant 锁定
--------------

1. **R279 specific**: ``openConfigFileInIde()`` 的 finally 块必须重新
   ``getElementById("open-config-file-btn")`` 而不是直接复用 stale ``btn``
2. **R279 anchor 注释**: finally 块必须有 ``R279`` 注释 marker，让未来
   refactor 看到时立刻理解为什么 re-query
3. **R268 + R279 meta-lint (建议)**: 任何 ``async`` 方法的 finally 块若
   要重置 DOM ``.disabled`` 属性，必须用 ``document.getElementById`` 重
   query 或显式 null check

Why locked
----------

R268 在 ``app.js::submitFeedback()`` 是 user-visible bug (catch 路径的
error toast 被吞)。R279 是同 class bug，在 ``settings-manager.js`` 隐
形发生（用户极少在 fetch 期间触发重渲染），但一旦未来 cycle 引入 settings
hot-reload 立刻爆发。R279 是 anti-future-regression lock。

Meta-lint pattern
-----------------

这是 R275 meta-lint pattern (``reset*()`` 必须 confirm) 的第三个 production
应用，扩展到 ``finally`` 块 DOM 模式：

| R# | Cycle | Meta-lint subject |
|----|-------|-------------------|
| R273 | cycle-23 | ``setting-title`` 必须 ``data-i18n`` |
| R275 | cycle-24 | ``async reset*()`` 必须 ``window.confirm`` |
| R279 | cycle-25 | finally + await 后的 DOM 引用必须 null-guard |
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SETTINGS_MANAGER_JS = (
    REPO_ROOT
    / "src"
    / "ai_intervention_agent"
    / "static"
    / "js"
    / "settings-manager.js"
)
APP_JS = REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "js" / "app.js"


def _extract_function_body(src: str, fn_signature_regex: str) -> str:
    """从源码中提取首次匹配 fn signature 的函数 body (粗略大括号匹配)。"""
    match = re.search(fn_signature_regex, src)
    assert match is not None, f"R279: 找不到函数签名 ``{fn_signature_regex}``"
    start = match.end()
    open_brace = src.find("{", start)
    assert open_brace >= 0, "R279: 函数签名后找不到 ``{``"
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
    raise AssertionError("R279: function body brace mismatch")


class TestOpenConfigFinallyNullCheckR279(unittest.TestCase):
    """R279 #1: ``openConfigFileInIde()`` finally 块必须 re-query +
    null-guard，不能直接复用 await 前的 stale ``btn`` reference。"""

    src = SETTINGS_MANAGER_JS.read_text(encoding="utf-8")

    def test_open_config_function_exists(self) -> None:
        self.assertRegex(
            self.src,
            r"async\s+openConfigFileInIde\s*\(\s*\)\s*\{",
            "R279: ``openConfigFileInIde()`` 函数必须存在 (R279 锚定的修复点)",
        )

    def _extract_finally_body(self) -> str:
        body = _extract_function_body(
            self.src, r"async\s+openConfigFileInIde\s*\(\s*\)\s*"
        )
        finally_match = re.search(
            r"\}\s*finally\s*\{(.*?)^\s*\}\s*$",
            body,
            re.DOTALL | re.MULTILINE,
        )
        assert finally_match is not None, (
            "R279: ``openConfigFileInIde()`` 必须有 finally 块（R279 锚点）"
        )
        return finally_match.group(1)

    def test_finally_block_does_not_use_stale_btn(self) -> None:
        """finally 块里不能直接 ``btn.disabled = ...``（应改用重新 query 的
        ``btnNow``）。"""
        finally_body = self._extract_finally_body()
        self.assertNotRegex(
            finally_body,
            r"^\s*btn\.disabled\s*=",
            "R279 regression: ``openConfigFileInIde()`` finally 块不能直接 "
            "``btn.disabled = originalDisabled;`` (R268 同 class bug)。"
            "必须重新 ``getElementById`` 拿 fresh reference + null check 兜底。",
        )

    def test_finally_block_requeries_button(self) -> None:
        """finally 块里必须有 ``getElementById("open-config-file-btn")``
        re-query。"""
        finally_body = self._extract_finally_body()
        self.assertIn(
            'getElementById("open-config-file-btn")',
            finally_body,
            'R279: finally 块必须重新 ``getElementById("open-config-file-btn")`` '
            "获取 fresh reference (await 后 DOM 可能被 SSE re-render 替换)",
        )

    def test_finally_block_null_guards_requeried_button(self) -> None:
        """finally 块必须 ``if (btnNow)`` 或类似 null check 兜底。"""
        finally_body = self._extract_finally_body()
        self.assertRegex(
            finally_body,
            r"if\s*\(\s*btnNow\s*\)",
            "R279: finally 块的 re-queried ``btnNow`` 必须 ``if (btnNow)`` "
            "null check (DOM 已不在时静默跳过)",
        )

    def test_r279_anchor_comment_present(self) -> None:
        """finally 块附近必须有 ``R279`` anchor 注释，让未来 refactor 看
        到时知道为什么 re-query 而不是直接复用 ``btn``。"""
        body = _extract_function_body(
            self.src, r"async\s+openConfigFileInIde\s*\(\s*\)\s*"
        )
        self.assertIn(
            "R279",
            body,
            "R279: ``openConfigFileInIde()`` 函数体必须有 ``R279`` anchor "
            "注释（让 grep R279 能直接定位修复点）",
        )


class TestR268AppJsStillFixed(unittest.TestCase):
    """R268 sanity check: ``app.js::submitFeedback()`` 的 finally 块仍然
    有 R268 null check（确保 R279 commit 不意外回退 R268）。"""

    src = APP_JS.read_text(encoding="utf-8")

    def test_app_js_submit_finally_still_has_null_check(self) -> None:
        """``submitFeedback`` 的 finally 块必须仍有 ``if (submitBtn)`` 兜底
        (R268 修复点)。"""
        self.assertIn(
            "R268",
            self.src,
            "R279 sanity: ``app.js`` 必须仍有 ``R268`` anchor 注释",
        )
        self.assertRegex(
            self.src,
            r"const\s+submitBtn\s*=\s*document\.getElementById\(\s*\"submit-btn\"\s*\)\s*;\s*if\s*\(\s*submitBtn\s*\)",
            "R279 sanity: ``app.js::submitFeedback()`` 必须仍有 R268 "
            '``const submitBtn = document.getElementById("submit-btn"); '
            "if (submitBtn) {{ ... }}`` 兜底 (防止 R279 commit 意外回退 R268)",
        )


class TestFinallyBlockMetaLint(unittest.TestCase):
    """R279 meta-lint (advisory): scan all ``static/js/*.js`` 里 ``async``
    函数的 ``finally`` 块，找出疑似 ``await`` 跨界后未 null-guard 的 DOM
    访问。

    这是 R275 meta-lint pattern 的第三个 production 应用，扩展到 finally
    块 DOM 模式。
    """

    def test_async_function_finally_blocks_audit(self) -> None:
        """白名单审计：遍历 static/js 下所有 finally 块，确认每个 DOM
        property assignment 都有 null guard 或注释豁免。

        当前白名单（cycle-25 t25-3 audit 结果）：
        - settings-manager.js:1007 (document.body.removeChild ta sync)
        - app.js R268 + settings-manager.js R279 都已修复
        - 其他 finally 块都不访问 DOM

        如果未来新 finally + DOM 模式出现且未在白名单，本测试会失败
        提示作者评估是否需要 R268/R279 同款 null check。
        """
        js_dir = REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "js"
        # 白名单：(file_name, signature) 表示已知 safe 或已修复
        whitelist = {
            "settings-manager.js": [
                "R279",
                "removeChild(ta)",
                "R452-custom-sound-upload-reset",
            ],  # R279 fixed + local-sync ta + custom sound file-input cleanup
            "app.js": ["R268"],  # R268 fixed
            "i18n.js": ["seen.delete", "delete _pendingLoads"],  # safe (no DOM)
            "multi_task.js": ["clearTimeout", "tasksPollAbortController", "setTimeout"],
            "notification-manager.js": ["permissionRequestPromise"],  # safe (state)
            "quick_phrases.js": ["R452-export-cleanup"],  # safe (download cleanup)
        }

        # 扫所有 .js (排除 .min.js 和 vendor 第三方库)
        vendor_files = {
            "tex-mml-chtml.js",  # MathJax 3rd-party，不在我们控制范围
        }
        violations: list[str] = []
        for js_file in sorted(js_dir.glob("*.js")):
            if js_file.name.endswith(".min.js"):
                continue
            if js_file.name in vendor_files:
                continue
            content = js_file.read_text(encoding="utf-8")
            # 找所有 finally 块
            finally_matches = re.finditer(
                r"\}\s*finally\s*\{",
                content,
            )
            for fm in finally_matches:
                # 取 finally 后 600 chars 作为 block body sample
                block_sample = content[fm.start() : fm.start() + 600]
                expected_markers = whitelist.get(js_file.name, [])
                if not any(marker in block_sample for marker in expected_markers):
                    # 此 finally 块没有任何白名单 marker → 疑似新 finally 模式
                    line_no = content[: fm.start()].count("\n") + 1
                    violations.append(
                        f"{js_file.name}:{line_no} — finally 块没有任何白名单 "
                        f"marker ({expected_markers})，可能是新的 R268/R279 "
                        "class bug。请审查并：(a) 加 null guard，(b) 添加 "
                        "anchor 注释，或 (c) 更新本测试白名单"
                    )

        self.assertEqual(
            len(violations),
            0,
            "R279 meta-lint failure:\n  " + "\n  ".join(violations),
        )


if __name__ == "__main__":
    unittest.main()
