"""R285 / cycle-26 t26-2 (R268/R279/R280 entry-side 第四轮 audit):
``loadConfig()`` + ``copyCodeToClipboard()`` 在 await 跨界后的 DOM 访问
必须 null-guard / isConnected guard，防 stale DOM ref 抛 TypeError 污染
catch 路径误报错误。

R268 → R279 → R280 → R285 evolution
------------------------------------

| Cycle | R# | Function | Side | Guard pattern |
|-------|-----|----------|------|---------------|
| cycle-22 | R268 | submitFeedback | finally | re-query + null check |
| cycle-25 | R279 | openConfigFileInIde | finally | re-query + null check |
| cycle-25 | R280 | submitFeedback | entry + success path | direct null check |
| cycle-26 | R285 | loadConfig | success path (3 nodes) | null check 兜底 |
| cycle-26 | R285 | copyCodeToClipboard | entry + await result + setTimeout | isConnected check |

R285 引入新 guard pattern: ``isConnected`` 而非 ``getElementById`` re-query。
``isConnected`` 适用于 caller 已传入引用 (event handler closure) 的场景，
检查节点是否仍 attached to document。性能比 re-query 更优 (无 DOM 树查询)。

R285 修复目标
-------------

### #1: ``loadConfig()`` (app.js line ~617)

await ``/api/config`` 后访问 3 个 DOM 节点：
- ``#description`` (line 635 ``renderMarkdownContent(descriptionElement, ...)``)
- ``#options-container`` (line 643)
- ``#separator`` (line 644)

旧代码任一节点缺失（multi-task 切换中 / DOM 重渲染中）会抛 TypeError
被 catch 翻成 "Config load failed"——但配置实际成功加载，UI 渲染失败误
报为"加载失败"。

R285 修复: 3 处都加 null check 兜底 + ``console.warn`` 留 trace。

### #2: ``copyCodeToClipboard(preElement, button)`` (app.js line ~520)

caller (event handler) 传入 preElement + button 引用。await
``navigator.clipboard.writeText`` 之后 button 可能因父 message bubble
unmount → DOM detached。旧代码直接 ``button.innerHTML = ...`` 在 detached
节点上抛 TypeError → catch 路径同样抛 → 整个 setTimeout restore 链断裂,
console error 无法被用户感知。

R285 修复: 入口 null check + await 后 ``isConnected`` check (best-effort
UI feedback, detached 时 silently skip)。

Invariant 锁定
--------------

1. ``loadConfig()`` 必须 3 处 null check (description / options-container
   / separator)
2. ``copyCodeToClipboard()`` 必须入口 null check (preElement + button)
3. ``copyCodeToClipboard()`` 必须 4 处 ``isConnected`` check (success+setTimeout
   + catch+setTimeout)
4. ``R285`` anchor 注释存在
5. R268/R279/R280 preserve sanity (不回退之前修复)

Pattern 选择 rationale
----------------------

- ``getElementById`` re-query (R268/R279): 适合 finally 块需要操作 DOM
  且不确定 element 引用是否新鲜的场景
- 直接 null check (R280): 适合 entry 阶段 ``getElementById`` 局部变量,
  失败 early return
- ``isConnected`` (R285 新引入): 适合 closure 引用 caller 传入的节点,
  检查 still attached 到 document, 比 re-query 更高效

3 种 pattern 各有适用场景。R285 是 "isConnected pattern" 的第一个
production 应用，为未来 closure-based DOM refs 提供 reusable template。
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
APP_JS = REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "js" / "app.js"


def _strip_js_comments(src: str) -> str:
    """剥离 ``//`` 与 ``/* */`` 注释 (R280 helper 复用)。"""
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
            j = src.find("\n", i)
            if j == -1:
                break
            i = j
            continue
        if ch == "/" and nxt == "*":
            j = src.find("*/", i + 2)
            if j == -1:
                break
            i = j + 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _extract_function_body(src: str, fn_signature_regex: str) -> str:
    """从源码中提取首次匹配的函数 body。"""
    match = re.search(fn_signature_regex, src)
    assert match is not None, f"R285: 找不到函数签名 ``{fn_signature_regex}``"
    start = match.end()
    open_brace = src.find("{", start)
    assert open_brace >= 0
    depth = 1
    i = open_brace + 1
    in_string = None
    while i < len(src) and depth > 0:
        ch = src[i]
        if in_string:
            if ch == "\\" and i + 1 < len(src):
                i += 2
                continue
            if ch == in_string:
                in_string = None
        else:
            if ch in ('"', "'", "`"):
                in_string = ch
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return src[open_brace : i + 1]
        i += 1
    raise AssertionError("R285: brace mismatch")


class TestLoadConfigNullChecksR285(unittest.TestCase):
    """R285 #1: ``loadConfig()`` 必须 3 处 null check + R285 anchor。"""

    src = APP_JS.read_text(encoding="utf-8")

    def setUp(self) -> None:
        self.body = _extract_function_body(
            self.src, r"async\s+function\s+loadConfig\s*\(\s*\)\s*"
        )

    def test_description_null_check(self) -> None:
        """``#description`` 必须 null check 后才 renderMarkdownContent。"""
        code = _strip_js_comments(self.body)
        self.assertRegex(
            code,
            r"const\s+descriptionElement\s*=\s*document\.getElementById\(\s*[\'\"]description[\'\"]\s*\)",
            "R285: ``descriptionElement`` 必须先拿到局部变量",
        )
        self.assertRegex(
            code,
            r"if\s*\(\s*descriptionElement\s*\)\s*\{[\s\S]{0,200}?renderMarkdownContent",
            "R285: ``renderMarkdownContent`` 必须包在 "
            "``if (descriptionElement) {...}`` 块内",
        )

    def test_options_container_null_check(self) -> None:
        """``#options-container`` + ``#separator`` 必须 null check。"""
        code = _strip_js_comments(self.body)
        self.assertRegex(
            code,
            r"if\s*\(\s*!\s*optionsContainer\s*\|\|\s*!\s*separator\s*\)",
            "R285: options-container / separator 任一缺失必须 short-circuit "
            "(``if (!optionsContainer || !separator)``) 跳过 options 渲染",
        )

    def test_r285_anchor_present(self) -> None:
        self.assertIn(
            "R285",
            self.body,
            "R285: ``loadConfig()`` 函数体必须有 ``R285`` anchor 注释",
        )


class TestCopyCodeToClipboardNullChecksR285(unittest.TestCase):
    """R285 #2: ``copyCodeToClipboard()`` 必须入口 null check +
    ``isConnected`` guards (success path + catch path + setTimeout)。"""

    src = APP_JS.read_text(encoding="utf-8")

    def setUp(self) -> None:
        self.body = _extract_function_body(
            self.src,
            r"async\s+function\s+copyCodeToClipboard\s*\(\s*preElement\s*,\s*button\s*\)\s*",
        )

    def test_entry_null_check(self) -> None:
        """入口 ``if (!preElement || !button) return;`` early-return。"""
        code = _strip_js_comments(self.body)
        self.assertRegex(
            code,
            r"if\s*\(\s*!\s*preElement\s*\|\|\s*!\s*button\s*\)\s*\{[\s\S]{0,200}?return",
            "R285: copyCodeToClipboard 入口必须 ``if (!preElement || !button) "
            "{ ... return; }`` early-return 兜底",
        )

    def test_isconnected_after_await(self) -> None:
        """await 后必须至少 1 处 ``button.isConnected`` 检查 (success path)。"""
        code = _strip_js_comments(self.body)
        # 数 button.isConnected 出现次数：应 ≥ 4 (success + success setTimeout
        # + catch + catch setTimeout)
        matches = re.findall(r"button\.isConnected", code)
        self.assertGreaterEqual(
            len(matches),
            4,
            f"R285: ``button.isConnected`` 必须出现至少 4 处 (success + "
            f"success setTimeout + catch + catch setTimeout)。当前 {len(matches)} 处",
        )

    def test_r285_anchor_present(self) -> None:
        self.assertIn(
            "R285",
            self.body,
            "R285: ``copyCodeToClipboard()`` 函数体必须有 ``R285`` anchor",
        )


class TestR268R279R280PreservedR285(unittest.TestCase):
    """R285 sanity: cycle-22 R268 / cycle-25 R279 / cycle-25 R280 修复
    都仍然在。"""

    app_src = APP_JS.read_text(encoding="utf-8")

    def test_r268_finally_null_check_preserved(self) -> None:
        self.assertIn("R268", self.app_src)
        self.assertRegex(
            self.app_src,
            r"finally\s*\{[\s\S]{0,800}?if\s*\(\s*submitBtn\s*\)",
            "R285 sanity: R268 submitBtn finally null-check 仍在",
        )

    def test_r280_submit_entry_preserved(self) -> None:
        self.assertIn("R280", self.app_src)
        self.assertRegex(
            self.app_src,
            r"feedbackTextEl\s*=\s*document\.getElementById\(\s*[\'\"]feedback-text[\'\"]\s*\)",
            "R285 sanity: R280 feedback-text entry null-check 仍在",
        )

    def test_r279_settings_manager_preserved(self) -> None:
        sm = (
            REPO_ROOT
            / "src"
            / "ai_intervention_agent"
            / "static"
            / "js"
            / "settings-manager.js"
        ).read_text(encoding="utf-8")
        self.assertIn("R279", sm, "R285 sanity: R279 settings-manager 修复仍在")


if __name__ == "__main__":
    unittest.main()
