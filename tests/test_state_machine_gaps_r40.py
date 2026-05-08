"""``state_machine`` 边界 + 错误路径补全测试 (R40)

R40 之前 ``state_machine.py`` 整体覆盖率 85.37%，``test_state_machine.py``
覆盖了"主流程合法迁移"和"非法迁移抛 InvalidTransition"，但缺：

* ``StateMachine.kind`` 公共属性 (line 172)。
* ``on_change`` 返回的 unsubscribe 闭包二次调用——``self._listeners.remove``
  会抛 ``ValueError``，必须被 ``except ValueError: pass`` 吃掉
  (lines 207-209)。否则用户 wiring 乱了想 unsub 两次时整个状态机崩。
* ``StateMachine.reset`` 复位到不在合法状态列表里的目标 (line 215-216)。
* ``flatten_targets(kind)`` 在 ``kind`` 不在 TRANSITIONS 中时
  raise ValueError (line 240) —— 当前由"调用方传错 kind 名"触发。
* ``validate_transition_table`` 内部检查"src 不在合法列表"
  (line 258) 与"target 不在合法列表" (line 261)。这两条历史上是
  *load-time guard*，但只在源代码错配时被触发；测试用 monkey-patch
  把表写错来主动触发，锁住 fail-loud 行为。
* ``_iter_all_states`` 调试 helper (lines 283-287)。

为什么这些"小"分支也要单测：

- 状态机是 **多端共享契约**（Python + 前端 state.js + VSCode webview-state.js）；
  任何一处 silent fall-through 都会让前后端状态发散，调试成本远高于
  写单元测试的成本。
- 这些路径只在 *配置错配 / 用户误用* 时被命中，正常 happy path 不会
  走到——但失败时不能"静默接受"，必须让调用方在测试期就看到错误。
- 项目其它模块（``server_feedback``、``service_manager``）会订阅
  状态机，``unsubscribe`` 双调用是真实场景：测试用例 setUp 注册一条
  listener、tearDown 调一次 unsub，然后 GC 触发 ``__del__`` 又再调一次。
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from ai_intervention_agent.state_machine import (
    TRANSITIONS,
    ConnectionStatus,
    ContentStatus,
    InteractionPhase,
    StateMachine,
    _iter_all_states,
    flatten_targets,
    list_all_states,
    validate_transition_table,
)


class TestStateMachineKindProperty(unittest.TestCase):
    """``kind`` 属性访问 (line 172)。"""

    def test_kind_property_returns_constructor_arg(self) -> None:
        sm = StateMachine("connection", initial=ConnectionStatus.IDLE)
        self.assertEqual(sm.kind, "connection")

    def test_kind_property_for_each_kind(self) -> None:
        kinds_initials = {
            "connection": ConnectionStatus.IDLE,
            "content": ContentStatus.SKELETON,
            "interaction": InteractionPhase.VIEWING,
        }
        for kind, initial in kinds_initials.items():
            with self.subTest(kind=kind):
                sm = StateMachine(kind, initial=initial)
                self.assertEqual(sm.kind, kind)


class TestStateMachineUnsubscribeIdempotent(unittest.TestCase):
    """``on_change`` 返回的 unsubscribe 闭包必须支持 *多次* 调用 (line 207-209)。"""

    def test_double_unsubscribe_is_safe(self) -> None:
        sm = StateMachine("content", initial=ContentStatus.SKELETON)
        unsub = sm.on_change(lambda _p, _n: None)
        unsub()
        # 第二次调用：内部 ``self._listeners.remove(cb)`` 会抛 ValueError，
        # 必须被吃掉。否则用户做"幂等清理"会冒一个不该出现的异常。
        unsub()  # not raising == passing

    def test_unsubscribe_after_listener_already_dropped(self) -> None:
        """如果别处已经把 listener 数组重置（极端 corner case，例如测试
        clear），unsubscribe 再调用也不能 raise。"""
        sm = StateMachine("interaction", initial=InteractionPhase.VIEWING)
        unsub = sm.on_change(lambda _p, _n: None)
        sm._listeners.clear()
        unsub()  # 同样不能 raise


class TestStateMachineResetValidation(unittest.TestCase):
    """``reset`` 必须校验目标合法性 (line 215-216)。"""

    def test_reset_to_unknown_state_raises(self) -> None:
        sm = StateMachine("connection", initial=ConnectionStatus.IDLE)
        with self.assertRaises(ValueError) as ctx:
            sm.reset("ghost")
        self.assertIn("ghost", str(ctx.exception))

    def test_reset_to_other_kind_state_raises(self) -> None:
        """连接状态机 reset 到内容状态（``"skeleton"``）也要拒绝——状态值
        虽然合法但不属于本机种。"""
        sm = StateMachine("connection", initial=ConnectionStatus.IDLE)
        with self.assertRaises(ValueError):
            sm.reset(ContentStatus.SKELETON)


class TestFlattenTargetsUnknownKind(unittest.TestCase):
    """``flatten_targets`` 对未知 kind 必须 raise ValueError (line 240)。"""

    def test_unknown_kind_raises(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            flatten_targets("nonexistent_kind")
        self.assertIn("nonexistent_kind", str(ctx.exception))

    def test_known_kinds_return_targets(self) -> None:
        """sanity check：合法 kind 都能取到非空 target 集合。"""
        for kind in ("connection", "content", "interaction"):
            with self.subTest(kind=kind):
                targets = flatten_targets(kind)
                self.assertIsInstance(targets, set)
                self.assertGreater(len(targets), 0)


class TestValidateTransitionTableErrors(unittest.TestCase):
    """``validate_transition_table`` 在表格写错时 fail-loud (line 258, 261)。

    通过 monkey-patching 给 ``TRANSITIONS`` 临时注入坏表，验证 helper 真的
    在 src 非法 / target 非法两条分支上 raise。这两条 if 在源代码层面是
    "import-time guard"，正常情况下永远不会触发；但任何一次后续修改若
    引入坏表，必须立刻看到 RuntimeError 而不是被吃掉。
    """

    def test_invalid_src_state_raises_runtime_error(self) -> None:
        bad = dict(TRANSITIONS)
        bad["connection"] = {
            "this_is_not_a_legal_state": (ConnectionStatus.IDLE,),
        }
        with patch("ai_intervention_agent.state_machine.TRANSITIONS", bad):
            with self.assertRaises(RuntimeError) as ctx:
                validate_transition_table()
        self.assertIn("起始态", str(ctx.exception))
        self.assertIn("this_is_not_a_legal_state", str(ctx.exception))

    def test_invalid_target_state_raises_runtime_error(self) -> None:
        bad = dict(TRANSITIONS)
        bad["connection"] = {
            ConnectionStatus.IDLE: ("ghost_target",),
        }
        with patch("ai_intervention_agent.state_machine.TRANSITIONS", bad):
            with self.assertRaises(RuntimeError) as ctx:
                validate_transition_table()
        self.assertIn("迁移目标", str(ctx.exception))
        self.assertIn("ghost_target", str(ctx.exception))


class TestIterAllStatesDebugHelper(unittest.TestCase):
    """``_iter_all_states`` 调试遍历 (lines 283-287)。"""

    def test_yields_every_kind_state_pair(self) -> None:
        pairs = list(_iter_all_states())
        # 每个 (kind, state) 元组应当都出现在 list_all_states 里
        all_states = list_all_states()
        for kind, state in pairs:
            with self.subTest(kind=kind, state=state):
                self.assertIn(state, all_states[kind])

    def test_total_count_matches_flat_state_set(self) -> None:
        pairs = list(_iter_all_states())
        all_states = list_all_states()
        expected_total = sum(len(states) for states in all_states.values())
        self.assertEqual(
            len(pairs),
            expected_total,
            "_iter_all_states 的元组总数应当 = 所有 (kind, state) 对的笛卡尔和",
        )

    def test_every_kind_appears_at_least_once(self) -> None:
        seen_kinds = {kind for kind, _state in _iter_all_states()}
        self.assertEqual(seen_kinds, {"connection", "content", "interaction"})


if __name__ == "__main__":
    unittest.main()
