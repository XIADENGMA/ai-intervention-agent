"""state_machine.py 单元测试 + 前端 JS 常量同步回归护栏。

三类测试：
1. **常量表本体**：状态集合 / 迁移表的形态与自检
2. **StateMachine 行为**：合法迁移、非法迁移抛异常、订阅/取消订阅
3. **JS 同步**：static/js/state.js 与 packages/vscode/webview-state.js
   内容必须完全一致；其中声明的常量值必须与 Python 端逐项对齐
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from state_machine import (
    ConnectionStatus,
    ContentStatus,
    InteractionPhase,
    InvalidTransition,
    StateMachine,
    flatten_targets,
    list_all_states,
    list_transitions,
    validate_transition_table,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
WEB_STATE_JS = REPO_ROOT / "static" / "js" / "state.js"
VSCODE_STATE_JS = REPO_ROOT / "packages" / "vscode" / "webview-state.js"


# ---------------------------------------------------------------------------
# 常量表 / 表结构
# ---------------------------------------------------------------------------
class TestConstants(unittest.TestCase):
    def test_connection_values_are_lowercase_words(self):
        for s in ConnectionStatus.ALL:
            self.assertRegex(s, r"^[a-z_]+$", f"{s!r} 应为小写下划线字符串")

    def test_content_values_are_lowercase_words(self):
        for s in ContentStatus.ALL:
            self.assertRegex(s, r"^[a-z_]+$")

    def test_interaction_values_are_lowercase_words(self):
        for s in InteractionPhase.ALL:
            self.assertRegex(s, r"^[a-z_]+$")

    def test_all_values_are_unique_inside_each_kind(self):
        for kind, values in list_all_states().items():
            self.assertEqual(len(values), len(set(values)), f"{kind}: 存在重复状态值")

    def test_module_level_validation_passes(self):
        validate_transition_table()

    def test_no_isolated_target_states(self):
        """每个作为 target 的状态都必须是该种的合法状态（已被 validate 覆盖，
        但在这里独立断言一次，作为 spec 可读文档）。"""
        all_states = list_all_states()
        for kind, targets in {k: flatten_targets(k) for k in all_states}.items():
            self.assertTrue(
                targets.issubset(set(all_states[kind])),
                f"{kind}: 目标集 {targets} 不是合法状态子集",
            )


# ---------------------------------------------------------------------------
# StateMachine 行为
# ---------------------------------------------------------------------------
class TestStateMachineBehavior(unittest.TestCase):
    def test_legal_transition_fires_listener(self):
        sm = StateMachine("connection", initial=ConnectionStatus.IDLE)
        seen: list[tuple[str, str]] = []
        sm.on_change(lambda p, n: seen.append((p, n)))
        sm.transition(ConnectionStatus.CONNECTING)
        sm.transition(ConnectionStatus.CONNECTED)
        self.assertEqual(
            seen,
            [
                (ConnectionStatus.IDLE, ConnectionStatus.CONNECTING),
                (ConnectionStatus.CONNECTING, ConnectionStatus.CONNECTED),
            ],
        )
        self.assertEqual(sm.status, ConnectionStatus.CONNECTED)

    def test_noop_transition_does_not_fire_listener(self):
        sm = StateMachine("connection", initial=ConnectionStatus.IDLE)
        fired = 0

        def cb(_p: str, _n: str) -> None:
            nonlocal fired
            fired += 1

        sm.on_change(cb)
        sm.transition(ConnectionStatus.IDLE)
        self.assertEqual(fired, 0)

    def test_illegal_transition_raises(self):
        sm = StateMachine("connection", initial=ConnectionStatus.IDLE)
        with self.assertRaises(InvalidTransition):
            sm.transition(ConnectionStatus.CONNECTED)

    def test_unsubscribe_stops_listener(self):
        sm = StateMachine("content", initial=ContentStatus.SKELETON)
        calls = []
        unsub = sm.on_change(lambda p, n: calls.append((p, n)))
        sm.transition(ContentStatus.LOADING)
        unsub()
        sm.transition(ContentStatus.READY)
        self.assertEqual(len(calls), 1)

    def test_listener_exception_does_not_break_state(self):
        sm = StateMachine("interaction", initial=InteractionPhase.VIEWING)

        def boom(_p: str, _n: str) -> None:
            raise RuntimeError("boom")

        sm.on_change(boom)
        sm.transition(InteractionPhase.COMPOSING)
        self.assertEqual(sm.status, InteractionPhase.COMPOSING)

    def test_reset_ignores_transition_rules(self):
        sm = StateMachine("connection", initial=ConnectionStatus.IDLE)
        sm.transition(ConnectionStatus.CONNECTING)
        sm.transition(ConnectionStatus.CONNECTED)
        sm.reset(ConnectionStatus.IDLE)
        self.assertEqual(sm.status, ConnectionStatus.IDLE)

    def test_unknown_kind_raises(self):
        with self.assertRaises(ValueError):
            StateMachine("unknown", initial="x")

    def test_illegal_initial_raises(self):
        with self.assertRaises(ValueError):
            StateMachine("connection", initial="ghost")


# ---------------------------------------------------------------------------
# JS 同步回归
# ---------------------------------------------------------------------------
# 抓取形如 ``IDLE: 'idle',`` 的字面量键值
_JS_KV_RE = re.compile(r"\b([A-Z_][A-Z0-9_]*)\s*:\s*'([a-z_]+)'")


def _parse_js_const_block(js: str, name: str) -> dict[str, str]:
    """从 JS 源里抓取形如::

        var ConnectionStatus = Object.freeze({
          IDLE: 'idle',
          ...
        })

    返回 ``{'IDLE': 'idle', ...}``。找不到该块返回空字典。
    """
    # 匹配紧跟在 `var <Name> = Object.freeze({` 后面的第一个花括号块
    pattern = re.compile(
        r"var\s+" + re.escape(name) + r"\s*=\s*Object\.freeze\(\s*\{([^}]*)\}\s*\)",
        re.DOTALL,
    )
    m = pattern.search(js)
    if not m:
        return {}
    body = m.group(1)
    return dict(_JS_KV_RE.findall(body))


class TestJsSync(unittest.TestCase):
    def setUp(self) -> None:
        self.assertTrue(WEB_STATE_JS.exists(), f"缺少文件: {WEB_STATE_JS}")
        self.assertTrue(VSCODE_STATE_JS.exists(), f"缺少文件: {VSCODE_STATE_JS}")
        self.web_src = WEB_STATE_JS.read_text(encoding="utf-8")
        self.vsc_src = VSCODE_STATE_JS.read_text(encoding="utf-8")

    def test_two_js_files_are_byte_identical(self):
        self.assertEqual(
            self.web_src,
            self.vsc_src,
            "state.js 两端内容必须完全一致；如需差异请重新同步或重构为共享构建产物",
        )

    def test_connection_status_constants_match_python(self):
        js_map = _parse_js_const_block(self.web_src, "ConnectionStatus")
        py_map = {
            "IDLE": ConnectionStatus.IDLE,
            "CONNECTING": ConnectionStatus.CONNECTING,
            "CONNECTED": ConnectionStatus.CONNECTED,
            "DISCONNECTED": ConnectionStatus.DISCONNECTED,
            "RETRYING": ConnectionStatus.RETRYING,
            "CLOSED": ConnectionStatus.CLOSED,
        }
        self.assertEqual(js_map, py_map, "JS ConnectionStatus 与 Python 不一致")

    def test_content_status_constants_match_python(self):
        js_map = _parse_js_const_block(self.web_src, "ContentStatus")
        py_map = {
            "SKELETON": ContentStatus.SKELETON,
            "LOADING": ContentStatus.LOADING,
            "READY": ContentStatus.READY,
            "EMPTY": ContentStatus.EMPTY,
            "ERROR": ContentStatus.ERROR,
        }
        self.assertEqual(js_map, py_map, "JS ContentStatus 与 Python 不一致")

    def test_interaction_phase_constants_match_python(self):
        js_map = _parse_js_const_block(self.web_src, "InteractionPhase")
        py_map = {
            "VIEWING": InteractionPhase.VIEWING,
            "COMPOSING": InteractionPhase.COMPOSING,
            "SUBMITTING": InteractionPhase.SUBMITTING,
            "COOLDOWN": InteractionPhase.COOLDOWN,
        }
        self.assertEqual(js_map, py_map, "JS InteractionPhase 与 Python 不一致")

    def test_transitions_table_keys_match_python(self):
        """JS 文件 TRANSITIONS 块应与 Python 的迁移起点集一致。

        仅对 keys 做断言（JS 数组 value 里的字符串列表在 minify 后可能被
        写成多行，这里不强行解析，避免脆弱）。
        """
        py_trans = list_transitions()
        for kind in py_trans:
            expected_states = set(py_trans[kind].keys())
            for state in expected_states:
                self.assertIn(
                    f"{state}:",
                    self.web_src,
                    f"state.js 的 TRANSITIONS.{kind} 块缺少起点 {state!r}",
                )

    def test_iife_attaches_global_AIIAState(self):
        self.assertIn("global.AIIAState = api", self.web_src)
        self.assertIn("module.exports = api", self.web_src)


if __name__ == "__main__":
    unittest.main()
