"""R285 / cycle-26 t26-2 (R268/R279/R280 entry-side 第四轮 audit):
``loadConfig()`` 在 await 跨界后的 DOM 访问必须 null-guard，防 stale DOM ref
抛 TypeError 污染 catch 路径误报错误。

R268 → R279 → R280 → R285 evolution
------------------------------------

| Cycle | R# | Function | Side | Guard pattern |
|-------|-----|----------|------|---------------|
| cycle-22 | R268 | submitFeedback | finally | re-query + null check |
| cycle-25 | R279 | openConfigFileInIde | finally | re-query + null check |
| cycle-25 | R280 | submitFeedback | entry + success path | direct null check |
| cycle-26 | R285 | loadConfig | success path (3 nodes) | null check 兜底 |

R285 修复目标
-------------

``loadConfig()`` 在 await ``/api/config`` 后访问 3 个 DOM 节点：

- ``#description`` (``renderMarkdownContent(descriptionElement, ...)``)
- ``#options-container``
- ``#separator``

旧代码任一节点缺失（multi-task 切换中 / DOM 重渲染中）会抛 TypeError
被 catch 翻成 "Config load failed"——但配置实际成功加载，UI 渲染失败误
报为"加载失败"。

R285 修复: 3 处都加 null check 兜底 + ``console.warn`` 留 trace。

Invariant 锁定
--------------

1. ``loadConfig()`` 必须 3 处 null check (description / options-container
   / separator)
2. R268/R279/R280 preserve sanity (不回退之前修复)

R285 当时还给 ``copyCodeToClipboard()`` 加了 ``isConnected`` guard。这个函数
没有任何调用点（活着的复制按钮是 ``DOMSecurity.createCopyButton``，它的反馈
定时器行为由 R744 锁定），已被整个删除，对应的测试一并移除。
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


class TestR268R279R280PreservedR285(unittest.TestCase):
    """R285 sanity: cycle-22 R268 / cycle-25 R279 / cycle-25 R280 修复
    都仍然在（锚点注释已清理，改锁代码特征本身）。"""

    app_src = APP_JS.read_text(encoding="utf-8")

    def test_r268_finally_null_check_preserved(self) -> None:
        self.assertRegex(
            self.app_src,
            r"finally\s*\{[\s\S]{0,800}?if\s*\(\s*submitBtn\s*\)",
            "R285 sanity: R268 submitBtn finally null-check 仍在",
        )

    def test_r280_submit_entry_preserved(self) -> None:
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
        self.assertRegex(
            sm,
            r"finally\s*\{[\s\S]{0,800}?getElementById\(",
            "R285 sanity: R279 settings-manager finally null-check 仍在",
        )


if __name__ == "__main__":
    unittest.main()
