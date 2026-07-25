"""R709 回归护栏：translateDOM 不得覆盖 JS 动态写入的内容。

背景（盲区扫描发现，浏览器实证）：

``i18n.js::translateDOM()`` 对所有 ``[data-i18n]`` 元素执行
``el.textContent = t(key)``，对 ``[data-i18n-placeholder]`` 执行
placeholder 覆盖。它在两个时机重跑：语言切换（setLang）与
``ensureDefaultLocale()`` 异步完成时（慢网络下可能晚于首屏渲染）。

任何「模板带 data-i18n* 占位 + JS 运行时写入动态内容」的元素都会被
它覆盖回静态翻译。最严重的实例：``#description`` 初始
``data-i18n="page.loading"``，任务 prompt 渲染后一次 translateDOM 就把
**正在显示的任务内容整体抹成「加载中…」**——且 R687 渲染签名仍匹配、
childNodes 非空，后续轮询短路不重渲染，破坏是永久的（浏览器实测
``promptWiped: true``）。

R709 契约（BUG6 config-file-path 修复模式的系统化应用）：

1. ``renderMarkdownContent``（app.js）与 ``updateDescriptionDisplay``
   （multi_task.js）写入真实内容前 ``removeAttribute("data-i18n")``；
2. ``updateFeedbackPlaceholder``：任务自定义 placeholder 生效期间摘掉
   ``data-i18n-placeholder``，回默认文案时恢复（默认继续跟随语言）；
3. custom-sound 状态文本：动态值（用户文件名）时摘掉 ``data-i18n``，
   静态 i18n 文案时把属性同步为对应 key（跟随语言切换）；
4. 剪贴板失败提示：``getClipboardFailureHintKey`` 返回 **key**，
   ``openCodePasteModal`` 同步 ``data-i18n`` 为具体原因 key；
5. ``#countdown-text`` 模板不带 ``data-i18n``——文案由 JS 每秒以参数
   插值重写，静态翻译会覆盖成未替换的 ``{seconds}`` 字面量。
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
STATIC_JS = REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "js"
APP_JS = STATIC_JS / "app.js"
MULTI_TASK_JS = STATIC_JS / "multi_task.js"
SETTINGS_JS = STATIC_JS / "settings-manager.js"
TEMPLATE = REPO_ROOT / "src" / "ai_intervention_agent" / "templates" / "web_ui.html"


def _function_body(source: str, name: str) -> str:
    match = re.search(rf"(?:async\s+)?function\s+{name}\s*\([^)]*\)\s*\{{", source)
    assert match is not None, f"missing function {name}"
    depth = 0
    for idx in range(match.end() - 1, len(source)):
        char = source[idx]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[match.end() : idx]
    raise AssertionError(f"could not parse body for {name}")


class TestDescriptionRenderStripsI18nAttr(unittest.TestCase):
    """两个 prompt 渲染入口都必须在写入前摘掉 data-i18n。"""

    def test_render_markdown_content_removes_attr(self) -> None:
        body = _function_body(
            APP_JS.read_text(encoding="utf-8"), "renderMarkdownContent"
        )
        self.assertIn('element.removeAttribute("data-i18n")', body)

    def test_update_description_display_removes_attr(self) -> None:
        body = _function_body(
            MULTI_TASK_JS.read_text(encoding="utf-8"), "updateDescriptionDisplay"
        )
        self.assertIn('descriptionElement.removeAttribute("data-i18n")', body)

    def test_description_template_keeps_loading_placeholder(self) -> None:
        # 初始占位「加载中…」仍需跟随语言——data-i18n 保留在模板里，
        # 由渲染入口在写入真实内容时摘除。
        template = TEMPLATE.read_text(encoding="utf-8")
        idx = template.find('id="description"')
        self.assertGreater(idx, 0)
        snippet = template[max(0, idx - 200) : idx + 200]
        self.assertIn('data-i18n="page.loading"', snippet)


class TestFeedbackPlaceholderTwoWaySync(unittest.TestCase):
    """per-task placeholder：自定义时摘属性，回默认时恢复。"""

    def setUp(self) -> None:
        self.body = _function_body(
            MULTI_TASK_JS.read_text(encoding="utf-8"), "updateFeedbackPlaceholder"
        )

    def test_custom_placeholder_removes_attr(self) -> None:
        self.assertIn('removeAttribute("data-i18n-placeholder")', self.body)

    def test_default_placeholder_restores_attr(self) -> None:
        self.assertIn('"data-i18n-placeholder"', self.body)
        self.assertIn('"page.feedbackPlaceholder"', self.body)


class TestCustomSoundStatusAttrSync(unittest.TestCase):
    """custom-sound 状态：动态文件名摘属性，静态文案同步 key。"""

    def setUp(self) -> None:
        self.source = SETTINGS_JS.read_text(encoding="utf-8")

    def test_dynamic_filename_removes_attr(self) -> None:
        # refresh() 的 meta 分支：写 `${meta.name} (${kb} KB)` 前 remove
        idx = self.source.find("${meta.name} (${kb} KB)")
        self.assertGreater(idx, 0)
        window = self.source[max(0, idx - 400) : idx]
        self.assertIn('statusEl.removeAttribute("data-i18n")', window)

    def test_static_not_uploaded_restores_attr(self) -> None:
        self.assertIn(
            'statusEl.setAttribute("data-i18n", "settings.customSound.notUploaded")',
            self.source,
        )

    def test_error_branch_syncs_attr_to_msg_key(self) -> None:
        self.assertIn('statusEl.setAttribute("data-i18n", msgKey)', self.source)


class TestClipboardHintKeySync(unittest.TestCase):
    """剪贴板失败提示：返回 {key, text} + 写入时同步 data-i18n。"""

    def setUp(self) -> None:
        self.source = APP_JS.read_text(encoding="utf-8")

    def test_hint_helper_returns_key_and_text(self) -> None:
        body = _function_body(self.source, "getClipboardFailureHint")
        # 每个分支必须同时携带 key（供 data-i18n 同步）与 t("字面量")
        # 翻译（供孤儿 key 扫描器 JS_T_CALL_RE 识别）。
        self.assertIn('key: "status.clipboardHttp"', body)
        self.assertIn('t("status.clipboardHttp")', body)
        self.assertIn('key: "status.clipboardDefault"', body)
        self.assertIn('t("status.clipboardDefault")', body)

    def test_modal_syncs_hint_attr(self) -> None:
        body = _function_body(self.source, "openCodePasteModal")
        self.assertIn('hint.setAttribute("data-i18n", hintInfo.key)', body)


class TestCountdownTextHasNoI18nAttr(unittest.TestCase):
    """#countdown-text 由 JS 每秒参数插值重写，模板不得带 data-i18n。"""

    def test_template_countdown_text_attr_free(self) -> None:
        template = TEMPLATE.read_text(encoding="utf-8")
        idx = template.find('id="countdown-text"')
        self.assertGreater(idx, 0)
        snippet = template[max(0, idx - 300) : idx + 120]
        self.assertNotIn('data-i18n="page.countdown"', snippet)


class TestSseStatusAttrFollowsState(unittest.TestCase):
    """SSE 指示灯：data-i18n-title 必须跟随当前连接状态的 key。

    模板初始 ``data-i18n-title="page.sseStatus.connected"``；断线期间发生
    语言切换时 translateDOM 会按旧属性把 title 覆盖回「已连接」——与
    真实状态矛盾。_setSseStatus 必须把属性同步到当前状态 key。
    """

    def test_set_sse_status_syncs_attr_keys(self) -> None:
        body = _function_body(
            MULTI_TASK_JS.read_text(encoding="utf-8"), "_setSseStatus"
        )
        self.assertIn('el.setAttribute("data-i18n-title", stateKey)', body)
        self.assertIn('el.setAttribute("data-i18n-aria-label", stateKey)', body)
        self.assertIn('"page.sseStatus.reconnecting"', body)
        self.assertIn('"page.sseStatus.disconnected"', body)


if __name__ == "__main__":
    unittest.main()
