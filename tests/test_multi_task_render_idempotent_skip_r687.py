"""R687 — 轮询周期内容未变化时描述/选项渲染必须幂等短路（TODO#1 渲染抽搐）。

问题链（修复前）
----------------

``updateTasksList``（2s 轮询 / SSE 刷新）→ ``loadTaskDetails(activeTaskId)``
→ ``updateDescriptionDisplay`` + ``updateOptionsDisplay`` **无条件**重建 DOM：

- ``#description.innerHTML`` 整体替换 + Prism 重高亮 + MathJax 重排 →
  原始 TeX 与渲染态来回闪烁、布局抖动、用户文本选区每 2 秒丢一次；
- ``#options-container`` checkbox 全量重建 → hover / focus / 键盘导航
  状态每 2 秒丢一次。

修复
----

两个渲染函数入口比较 dataset 签名（描述用 prompt 原文；选项用
task + 选项文案 + 默认位图），内容未变化时直接 return，不触碰 DOM。

本测试锁定：

1. 源码契约：两个函数体必须带 R687 幂等短路。
2. 运行时行为（node vm）：同参重复调用只写一次 DOM；参数变化后重新渲染。
"""

from __future__ import annotations

import json
import unittest

from tests.test_multi_task_poll_controller_lifecycle_r452 import (
    MULTI_TASK_JS,
    _node_available,
    _poll_harness,
    _run_node,
)
from tests.test_multi_task_tab_active_sync_loop_r610 import _extract_function_body


def _source() -> str:
    return MULTI_TASK_JS.read_text(encoding="utf-8")


def test_description_render_has_r687_idempotent_guard() -> None:
    body = _extract_function_body(_source(), "updateDescriptionDisplay")
    assert "R687" in body, "updateDescriptionDisplay 必须带 R687 幂等短路注释标记"
    assert "renderedPrompt" in body, "必须用 dataset.renderedPrompt 做签名比较"
    assert "return" in body


def test_options_render_has_r687_idempotent_guard() -> None:
    body = _extract_function_body(_source(), "updateOptionsDisplay")
    assert "R687" in body, "updateOptionsDisplay 必须带 R687 幂等短路注释标记"
    assert "renderedSignature" in body, "必须用 dataset.renderedSignature 做签名比较"


def test_app_js_render_markdown_content_has_r687_idempotent_guard() -> None:
    """单任务路径（app.js::renderMarkdownContent）同样必须幂等短路。

    SSE auto-refresh 可能以相同内容重入 loadConfig → renderMarkdownContent，
    与多任务路径一样会造成 innerHTML 重建 + MathJax 重排闪烁。
    """
    app_js = (MULTI_TASK_JS.parent / "app.js").read_text(encoding="utf-8")
    body = _extract_function_body(app_js, "renderMarkdownContent")
    assert "R687" in body, "renderMarkdownContent 必须带 R687 幂等短路注释标记"
    assert "renderedContent" in body, "必须用 dataset.renderedContent 做签名比较"


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_description_rerender_skipped_when_prompt_unchanged() -> None:
    script = _poll_harness(
        """
        let innerHTMLWrites = 0;
        const descriptionElement = {
          dataset: {},
          childNodes: [],
          textContent: '',
          set innerHTML(value) {
            innerHTMLWrites += 1;
            this._html = value;
            this.childNodes = [{}];
          },
          get innerHTML() {
            return this._html || '';
          },
        };
        document.getElementById = function getElementById(id) {
          if (id === 'description') return descriptionElement;
          return null;
        };

        await updateDescriptionDisplay('# same prompt');
        await updateDescriptionDisplay('# same prompt');
        await updateDescriptionDisplay('# same prompt');
        const writesAfterSamePrompt = innerHTMLWrites;

        await updateDescriptionDisplay('# CHANGED prompt');
        const writesAfterChange = innerHTMLWrites;

        process.stdout.write(JSON.stringify({
          writesAfterSamePrompt,
          writesAfterChange,
        }));
        """
    )

    result = json.loads(_run_node(script))

    assert result["writesAfterSamePrompt"] == 1, (
        "同一 prompt 重复渲染必须幂等短路（只写一次 innerHTML），"
        f"实际写入 {result['writesAfterSamePrompt']} 次"
    )
    assert result["writesAfterChange"] == 2, "prompt 变化后必须重新渲染"


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_description_rerender_happens_when_container_cleared() -> None:
    """容器被外部清空（childNodes 为空）时，即使 prompt 相同也必须重渲染。"""
    script = _poll_harness(
        """
        let innerHTMLWrites = 0;
        const descriptionElement = {
          dataset: {},
          childNodes: [],
          textContent: '',
          set innerHTML(value) {
            innerHTMLWrites += 1;
            this._html = value;
            this.childNodes = [{}];
          },
          get innerHTML() {
            return this._html || '';
          },
        };
        document.getElementById = function getElementById(id) {
          if (id === 'description') return descriptionElement;
          return null;
        };

        await updateDescriptionDisplay('# same prompt');
        // 模拟外部清空容器（例如切页/错误恢复路径）
        descriptionElement.childNodes = [];
        await updateDescriptionDisplay('# same prompt');

        process.stdout.write(JSON.stringify({ innerHTMLWrites }));
        """
    )

    result = json.loads(_run_node(script))
    assert result["innerHTMLWrites"] == 2, "容器被清空后必须重渲染而不是误短路"


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_options_rerender_skipped_when_signature_unchanged() -> None:
    script = _poll_harness(
        """
        let clearCount = 0;
        const children = [];
        const optionsContainer = {
          dataset: {},
          classList: { add() {}, remove() {} },
          get childNodes() {
            return children;
          },
          set innerHTML(value) {
            if (value === '') {
              clearCount += 1;
              children.length = 0;
            }
          },
          get innerHTML() {
            return '';
          },
          appendChild(child) {
            children.push(child);
            return child;
          },
          querySelectorAll() {
            return [];
          },
        };
        const separator = { classList: { add() {}, remove() {} } };

        document.getElementById = function getElementById(id) {
          if (id === 'options-container') return optionsContainer;
          if (id === 'separator') return separator;
          return null;
        };

        activeTaskId = 'task-r687';
        taskOptionsStates = {};

        updateOptionsDisplay(['A', 'B'], [true, false]);
        updateOptionsDisplay(['A', 'B'], [true, false]);
        updateOptionsDisplay(['A', 'B'], [true, false]);
        const clearsAfterSameOptions = clearCount;

        updateOptionsDisplay(['A', 'B', 'C'], [true, false, false]);
        const clearsAfterChange = clearCount;

        process.stdout.write(JSON.stringify({
          clearsAfterSameOptions,
          clearsAfterChange,
          renderedCount: children.length,
        }));
        """
    )

    result = json.loads(_run_node(script))

    assert result["clearsAfterSameOptions"] == 1, (
        "同一签名重复渲染必须幂等短路（只清空重建一次），"
        f"实际 {result['clearsAfterSameOptions']} 次"
    )
    assert result["clearsAfterChange"] == 2, "选项变化后必须重新渲染"
    assert result["renderedCount"] == 3, "变化后的渲染应包含新选项集合"


if __name__ == "__main__":
    unittest.main()
