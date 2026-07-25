"""TODO#8-A：页面不在前台时新任务改发系统桌面通知的回归测试。

历史行为：``notifyNewTasks`` 无条件走页内 Visual Hint + 声音——页面在
后台/最小化（正是最需要桌面提醒的场景）时用户什么都看不到。

新行为：
- ``document.hidden === true`` 或 ``document.hasFocus() === false`` →
  调 ``showNotification``（系统桌面通知，固定 tag 折叠连发）
- 页面可见且聚焦 → 维持原 Visual Hint（不打扰）
- 测试 harness / 旧浏览器 document 缺这些成员 → 按"页面可见"处理
  （现有 ``test_notification_new_tasks_lazy_ids_r551.py`` 的 3 个用例
  即依赖该兜底语义保持绿色）
"""

from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
NOTIFICATION_MANAGER_JS = (
    REPO_ROOT
    / "src"
    / "ai_intervention_agent"
    / "static"
    / "js"
    / "notification-manager.js"
)


def _source() -> str:
    return NOTIFICATION_MANAGER_JS.read_text(encoding="utf-8")


def _extract_function(source: str, marker: str) -> str:
    start = source.find(marker)
    assert start != -1, f"Cannot find function marker: {marker}"
    open_brace = source.find("{", start + len(marker) - 1)
    assert open_brace != -1, f"Cannot find opening brace for: {marker}"
    depth = 1
    i = open_brace + 1
    while i < len(source):
        char = source[i]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[start : i + 1]
        i += 1
    raise AssertionError(f"Unbalanced function body for: {marker}")


def _notification_harness(document_js: str, case_js: str) -> str:
    """构建 Node vm harness；``document_js`` 注入自定义 document 对象字面量。"""
    return textwrap.dedent(
        f"""
        const fs = require('fs');
        const vm = require('vm');
        const code = fs.readFileSync({str(NOTIFICATION_MANAGER_JS)!r}, 'utf8')
          + '\\nglobalThis.__notificationManager = notificationManager;';

        const visualHintCounts = [];
        const showNotificationCalls = [];

        const sandbox = {{
          Audio: function Audio() {{}},
          Blob: function Blob(parts) {{
            this.size = String(parts && parts[0] ? parts[0] : '').length;
          }},
          CustomEvent: function CustomEvent(type, init) {{
            this.type = type;
            this.detail = init && init.detail;
          }},
          Date,
          Error,
          JSON,
          Map,
          Math,
          Notification: {{ permission: 'granted' }},
          Number,
          Object,
          Promise,
          RegExp,
          String,
          console: {{
            debug() {{}},
            error() {{}},
            info() {{}},
            log() {{}},
            warn() {{}},
          }},
          document: {document_js},
          localStorage: {{
            getItem() {{ return null; }},
            setItem() {{}},
            removeItem() {{}},
          }},
          navigator: {{ userAgent: 'node' }},
          setInterval() {{ return 1; }},
          clearInterval() {{}},
          setTimeout(fn) {{ fn(); return 1; }},
          clearTimeout() {{}},
          dispatchEvent() {{}},
          isSecureContext: true,
          showNewTaskVisualHint(count) {{
            visualHintCounts.push(count);
          }},
          __visualHintCounts: visualHintCounts,
          __showNotificationCalls: showNotificationCalls,
        }};
        sandbox.window = sandbox;

        vm.createContext(sandbox);
        vm.runInContext(code, sandbox);

        (async () => {{
        {textwrap.indent(case_js, "  ")}
        }})().catch((err) => {{
          console.error(err && err.stack ? err.stack : err);
          process.exit(1);
        }});
        """
    )


def _run_node(script: str) -> str:
    proc = subprocess.run(
        ["node", "-e", script],
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )
    if proc.returncode != 0:
        raise AssertionError(
            f"node exited {proc.returncode}\nstdout={proc.stdout!r}\nstderr={proc.stderr!r}"
        )
    return proc.stdout


_CASE_JS = """
const manager = sandbox.__notificationManager;
manager.playSound = async () => {};
manager.showNotification = async (title, message, options) => {
  sandbox.__showNotificationCalls.push({ title, message, options });
  return { close() {} };
};

const result = await manager.notifyNewTasks({ taskIds: ['task-a'] });

process.stdout.write(JSON.stringify({
  result,
  visualHintCounts: sandbox.__visualHintCounts,
  showNotificationCalls: sandbox.__showNotificationCalls,
}));
"""


def test_notify_new_tasks_has_page_away_branch() -> None:
    body = _extract_function(_source(), "async notifyNewTasks(event = {}) {")

    assert "document.hidden === true" in body
    assert "document.hasFocus" in body
    assert "'aiia-new-tasks'" in body
    # 页面前台路径必须保留 Visual Hint 调用（防回归删除）
    assert "showNewTaskVisualHint" in body


@pytest.mark.skipif(shutil.which("node") is None, reason="node runtime unavailable")
def test_hidden_page_sends_system_notification_instead_of_visual_hint() -> None:
    script = _notification_harness(
        "{ title: 'AI Intervention Agent', hidden: true, hasFocus() { return false; } }",
        _CASE_JS,
    )

    payload = json.loads(_run_node(script))
    assert payload["visualHintCounts"] == []
    assert len(payload["showNotificationCalls"]) == 1
    call = payload["showNotificationCalls"][0]
    assert call["title"] == "AI Intervention Agent"
    assert call["message"] == "New task added: task-a"
    assert call["options"]["tag"] == "aiia-new-tasks"


@pytest.mark.skipif(shutil.which("node") is None, reason="node runtime unavailable")
def test_unfocused_visible_page_sends_system_notification() -> None:
    # 窗口可见（hidden=false）但焦点在其他应用（hasFocus()=false）——
    # 用户在 IDE 里工作、Chrome 在旁边屏幕的典型场景。
    script = _notification_harness(
        "{ title: 'AI Intervention Agent', hidden: false, hasFocus() { return false; } }",
        _CASE_JS,
    )

    payload = json.loads(_run_node(script))
    assert payload["visualHintCounts"] == []
    assert len(payload["showNotificationCalls"]) == 1


@pytest.mark.skipif(shutil.which("node") is None, reason="node runtime unavailable")
def test_focused_visible_page_keeps_visual_hint() -> None:
    script = _notification_harness(
        "{ title: 'AI Intervention Agent', hidden: false, hasFocus() { return true; } }",
        _CASE_JS,
    )

    payload = json.loads(_run_node(script))
    assert payload["visualHintCounts"] == [1]
    assert payload["showNotificationCalls"] == []


@pytest.mark.skipif(shutil.which("node") is None, reason="node runtime unavailable")
def test_document_without_focus_members_defaults_to_visual_hint() -> None:
    # R551 harness 的 document 只有 title——兜底语义必须是"按页面可见处理"，
    # 否则旧测试矩阵与真实旧浏览器都会误走系统通知路径。
    script = _notification_harness(
        "{ title: 'AI Intervention Agent' }",
        _CASE_JS,
    )

    payload = json.loads(_run_node(script))
    assert payload["visualHintCounts"] == [1]
    assert payload["showNotificationCalls"] == []
