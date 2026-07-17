"""R688 — VSCode webview marked 配置必须用 use() 合并 renderer（TODO#2）。

问题链（修复前）
----------------

``packages/vscode/webview-ui.js::configureMarkedOnce`` 用::

    marked.setOptions({..., renderer: { html() { return '' } }})

禁用原生 HTML。但 ``setOptions`` 会把整个 renderer **替换**成这个只有
``html`` 方法的裸对象（``marked.use`` 才会做部分方法合并）。bundled
marked v15 在解析任何标题 / 列表 / 代码块 / 表格时都会抛::

    this.renderer.heading is not a function

``renderSimpleMarkdown`` 的 catch 兜底把整段内容降级为转义纯文本 ——
于是出现「web 页面能渲染 Markdown、插件页面显示原始 Markdown 文本 /
内容不完整」的用户可见故障。

修复
----

与 web 端 ``multi_task.js::configureMarkedSecurityOnce`` 同构：

1. ``marked.use({renderer: {html(){return ''}}})`` —— 部分覆盖合并；
2. ``marked.setOptions({...})`` 不再携带 ``renderer`` 键。

本测试锁定：

1. 源码契约：``configureMarkedOnce`` 必须走 ``marked.use`` 且
   ``setOptions`` 参数里不得出现 ``renderer:``。
2. 运行时行为：用 bundled ``marked.min.js`` 按源码同款配置序列真实解析
   代表性 Markdown，断言标题 / 列表 / 代码块 / 表格全部渲染成功且原生
   HTML 被丢弃。
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WEBVIEW_UI_JS = REPO_ROOT / "packages" / "vscode" / "webview-ui.js"
MARKED_MIN_JS = REPO_ROOT / "packages" / "vscode" / "marked.min.js"


def _source() -> str:
    return WEBVIEW_UI_JS.read_text(encoding="utf-8")


def _node_available() -> bool:
    return shutil.which("node") is not None


def _extract_configure_marked_once(source: str) -> str:
    match = re.search(
        r"function configureMarkedOnce\(\) \{.*?\n  \}", source, re.DOTALL
    )
    assert match is not None, "未找到 configureMarkedOnce —— 函数被重命名后请更新本测试"
    return match.group(0)


def test_configure_marked_uses_use_for_renderer_merge() -> None:
    body = _extract_configure_marked_once(_source())
    assert "marked.use(" in body, (
        "R688: 禁用原生 HTML 必须走 marked.use({renderer: ...})（部分合并），"
        "不能用 setOptions 整体替换 renderer"
    )
    assert "R688" in body, "configureMarkedOnce 必须带 R688 注释标记便于回溯"

    set_options_match = re.search(r"marked\.setOptions\(\{(.*?)\}\)", body, re.DOTALL)
    assert set_options_match is not None, (
        "configureMarkedOnce 应保留 setOptions 基础配置"
    )
    assert "renderer" not in set_options_match.group(1), (
        "R688: setOptions 参数不得携带 renderer —— 那会把默认 Renderer 替换成"
        "缺少 heading/paragraph 等方法的裸对象，marked v5+ 解析必抛异常"
    )


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_bundled_marked_renders_full_markdown_with_source_config() -> None:
    """用 bundled marked + 源码同款配置序列做真实解析（运行时行为验证）。"""
    configure_fn = _extract_configure_marked_once(_source())
    script = f"""
    global.window = {{}};
    const loaded = require({str(MARKED_MIN_JS)!r});
    const marked = global.window.marked || loaded;
    let markedOptionsConfigured = false;
    {configure_fn}
    configureMarkedOnce();
    if (!markedOptionsConfigured) {{
      throw new Error('configureMarkedOnce 未成功配置 marked');
    }}
    const input = [
      '# Heading',
      '',
      '<div>raw html should be dropped</div>',
      '',
      '- item1',
      '- [ ] task item',
      '',
      '```js',
      'code();',
      '```',
      '',
      '| a | b |',
      '|---|---|',
      '| 1 | 2 |',
    ].join('\\n');
    const html = marked.parse(input);
    process.stdout.write(JSON.stringify({{ html }}));
    """
    proc = subprocess.run(
        ["node", "-e", script],
        capture_output=True,
        check=False,
        text=True,
        timeout=20,
    )
    assert proc.returncode == 0, (
        f"node exited {proc.returncode}\nstdout={proc.stdout!r}\nstderr={proc.stderr!r}"
    )
    html = json.loads(proc.stdout)["html"]

    assert "<h1>" in html, "标题必须渲染成功（修复前抛 renderer.heading 异常）"
    assert "<ul>" in html and "<li>" in html, "列表必须渲染成功"
    assert "<pre><code" in html, "代码块必须渲染成功"
    assert "<table>" in html, "GFM 表格必须渲染成功"
    assert "raw html should be dropped" not in html, (
        "原生 HTML 必须仍被 html() 覆盖丢弃（安全语义不变）"
    )


if __name__ == "__main__":
    unittest.main()
