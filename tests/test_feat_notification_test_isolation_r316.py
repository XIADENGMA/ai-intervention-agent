"""R316 · NotificationManager 测试隔离 invariant (test-isolation pattern 1st app)。

背景
----

R145 ``TestStreakInRealNotificationManagerSendPath`` 在 cycle-30 / cycle-31 /
cycle-32 全 regression 跑出现**间歇性 (flake) fail**:

- 第一次跑 fail 3 个 test (``success_increments_streak`` /
  ``success_then_failure_resets_streak`` / ``failure_increments_streak``)
- 第二次跑全过
- 单独 (``-n 1``) 跑也全过

**根因**: R145 setUp 用 ``NotificationManager.__new__(NotificationManager)``
拿到的是 **singleton instance** (`_instance` 已存在的话)。setUp 然后**手动**
初始化部分 instance attrs (``_stats_lock`` / ``_stats`` / ``_providers`` /
...), 但**漏掉**了 ``_send_single_notification`` 路径上依赖的:

- ``_provider_latency_histograms`` (R191 latency histogram dict)
- ``_finalized_event_ids`` (重试去重 dict)
- ``_finalized_max_size`` (去重 cap int)

当 ``_send_single_notification`` 调用 ``self._record_provider_latency_bucket()``
访问 ``self._provider_latency_histograms.get(...)`` 时:

- 如果**先**有测试触发了 ``NotificationManager().__init__()``, singleton instance
  已有 ``_provider_latency_histograms = {}``, R145 setUp 也没显式覆盖, 那么
  `_record_provider_latency_bucket` 正常工作 → streak 更新成功 → 测试 pass
- 如果**没有**先行的测试触发完整 ``__init__``, singleton instance 只有
  setUp 手动设的属性, ``_record_provider_latency_bucket`` 抛 ``AttributeError``
  → 被外层 ``except Exception: pass`` 吞掉 → ``if ok: stats["success_streak"]
  += 1`` 那段**不执行** → streak 始终是 0 → 测试 fail

R316 fix (已落地在 ``test_notification_health_streak_r145.py`` setUp 里):

显式补充 3 个缺失 attr::

    self.mgr._provider_latency_histograms = {}
    self.mgr._finalized_event_ids = {}
    self.mgr._finalized_max_size = 500

R316 invariant (本文件): **锁定** R145 setUp 必须显式初始化 `_send_single_
notification` 路径上引用的所有 instance attrs, 未来若有人:

- 给 `NotificationManager.__init__` 加新 instance attr (e.g. ``_xxx_lock``)
- 而 ``_send_single_notification`` 或它的下游 (``_record_provider_latency_
  bucket`` 等) 用到这个新 attr
- 但**没**在 R145 setUp 显式初始化

那么 invariant test fail, 强制开发者:
1. 补 R145 setUp 的属性初始化, 或
2. 把新 attr 移出 ``_send_single_notification`` 路径, 或
3. 显式标注 (whitelist) 这个 attr 与 R145 setUp 无关

这是 cycle-33 #A1 任务, 解决 cr62 §4A 风险, 引入新的 **test-isolation
invariant pattern** (v3.8 第 2 个 pattern; v3.8 第 1 个 pattern = R313
幂等 contract).

Pattern lineage (cycle-33 起步, 后续会有 2nd / 3rd app):

- 1st app: **R316 (本 commit)** — NotificationManager singleton attribute
  pollution → R145 setUp 显式初始化 invariant
- 2nd app (候选): 其他类似 singleton 测试隔离 (如果有)
"""

from __future__ import annotations

import inspect
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


_R145_TEST_PATH = REPO_ROOT / "tests" / "test_notification_health_streak_r145.py"
_NOTIFICATION_MANAGER_PATH = (
    REPO_ROOT / "src" / "ai_intervention_agent" / "notification_manager.py"
)

REQUIRED_R145_SETUP_ATTRS = (
    "_provider_latency_histograms",
    "_finalized_event_ids",
    "_finalized_max_size",
)
"""``_send_single_notification`` 路径上必须显式初始化的 attr 列表。

R316 锁定: 这 3 个 attr 必须在 ``TestStreakInRealNotificationManagerSendPath
.setUp`` 里被显式初始化, 否则 R145 fresh ``__new__`` 后 ``_send_single_
notification`` (调用 ``_record_provider_latency_bucket``) 会 throw
``AttributeError``, 被外层 ``except`` 吞掉, 导致 streak 没更新, 测试 flake fail。
"""


class TestR145SetupCoversAllSendPathAttrs:
    """Layer 1: R145 setUp 必须**全覆盖** ``_send_single_notification`` 路径
    引用的 NotificationManager instance attrs。

    **R319 后**: 接受两种合法实现:

    1. **旧模式 (R316)**: R145 setUp 直接 ``self.mgr.{attr} = ...`` 显式 init
    2. **新模式 (R319)**: R145 setUp 调用 ``NotificationManager._create_test_
       instance()``, 由 helper 集中初始化全部 attr (是 test-isolation pattern
       2nd app, 推荐)

    R319 把"R145 setUp 维护 13 行属性列表"的责任收编到 NotificationManager
    自己暴露的 ``_create_test_instance()``, 减少 setUp 漂移风险。
    """

    def test_r145_test_file_exists(self):
        assert _R145_TEST_PATH.is_file(), f"R145 test file missing: {_R145_TEST_PATH}"

    def test_r145_setup_covers_required_attrs_via_one_of_two_modes(self, subtests):
        text = _R145_TEST_PATH.read_text(encoding="utf-8")
        # R319 模式: 整个 file 含 ``_create_test_instance()`` 调用
        uses_r319_helper = bool(re.search(r"_create_test_instance\s*\(\s*\)", text))
        for attr in REQUIRED_R145_SETUP_ATTRS:
            with subtests.test(attr=attr):
                # 旧模式: 直接 self.mgr.<attr> = ...
                old_pattern = rf"self\.mgr\.{re.escape(attr)}\s*="
                old_mode_ok = bool(re.search(old_pattern, text))
                if uses_r319_helper or old_mode_ok:
                    # 至少一种模式覆盖 → 通过
                    continue
                raise AssertionError(
                    f"R145 setUp missing coverage for `self.mgr.{attr}` — "
                    f"R316 invariant: required for `_send_single_notification` "
                    f"path. Options:\n"
                    f"  - Old (R316): add `self.mgr.{attr} = ...` in setUp\n"
                    f"  - New (R319, preferred): use "
                    f"`NotificationManager._create_test_instance()` in setUp "
                    f"(let helper init all attrs centrally)\n"
                    f"See test_feat_notification_test_isolation_r316.py + "
                    f"NotificationManager._create_test_instance() docstrings."
                )


class TestR319HelperInitializesRequiredAttrs:
    """Layer 1b (R319): 如果 R145 setUp 用了 R319 helper, 那么 helper 自身
    必须显式初始化全部 REQUIRED_R145_SETUP_ATTRS — 这是 R319 contract 的
    锚点。"""

    def test_r319_helper_exists_in_notification_manager(self):
        from ai_intervention_agent.notification_manager import NotificationManager

        assert hasattr(NotificationManager, "_create_test_instance"), (
            "R319 contract: NotificationManager must expose "
            "`_create_test_instance()` classmethod for test isolation"
        )
        assert callable(NotificationManager._create_test_instance)

    def test_r319_helper_initializes_required_attrs(self, subtests):
        """端到端: 调 helper 后, 全 REQUIRED_R145_SETUP_ATTRS 都存在。"""
        from ai_intervention_agent.notification_manager import NotificationManager

        inst = NotificationManager._create_test_instance()
        for attr in REQUIRED_R145_SETUP_ATTRS:
            with subtests.test(attr=attr):
                assert hasattr(inst, attr), (
                    f"R319 contract: NotificationManager._create_test_instance"
                    f"() must initialize `{attr}` "
                    f"(R316 invariant requirement). Current helper missing "
                    f"this attr — update _create_test_instance() body."
                )


class TestSendSinglePathReferencesRequiredAttrs:
    """Layer 2: 源码 `_send_single_notification` (含下游) 必须引用 R316 列出
    的 attr — 锁定 invariant target 的代码事实, 防止 attr 在源码被改名后
    invariant 失效。"""

    def test_source_file_exists(self):
        assert _NOTIFICATION_MANAGER_PATH.is_file()

    def test_send_single_notification_method_exists(self):
        from ai_intervention_agent.notification_manager import NotificationManager

        assert hasattr(NotificationManager, "_send_single_notification"), (
            "R316 anchor missing: NotificationManager._send_single_notification"
        )

    def test_record_provider_latency_bucket_method_exists(self):
        from ai_intervention_agent.notification_manager import NotificationManager

        assert hasattr(NotificationManager, "_record_provider_latency_bucket"), (
            "R316 anchor missing: NotificationManager._record_provider_latency_bucket"
        )

    def test_record_provider_latency_bucket_reads_histograms_attr(self):
        from ai_intervention_agent.notification_manager import NotificationManager

        source = inspect.getsource(NotificationManager._record_provider_latency_bucket)
        assert "self._provider_latency_histograms" in source, (
            "R316 invariant: `_record_provider_latency_bucket` must read "
            "`self._provider_latency_histograms` so missing-attr → "
            "AttributeError → silent test fail loop is reproducible. "
            "If you renamed the attr, update REQUIRED_R145_SETUP_ATTRS too."
        )


class TestR316InitInitializesRequiredAttrs:
    """Layer 3: NotificationManager.__init__ 必须初始化 R316 锁的全部 attr,
    确保 `_send_single_notification` 在生产路径上有完整状态。"""

    def test_init_source_initializes_all_required_attrs(self, subtests):
        from ai_intervention_agent.notification_manager import NotificationManager

        source = inspect.getsource(NotificationManager.__init__)
        for attr in REQUIRED_R145_SETUP_ATTRS:
            with subtests.test(attr=attr):
                pattern = rf"self\.{re.escape(attr)}\s*[:=]"
                assert re.search(pattern, source), (
                    f"R316 invariant: NotificationManager.__init__ must "
                    f"initialize `self.{attr}` (referenced on "
                    f"`_send_single_notification` path). If you moved it "
                    f"elsewhere, update REQUIRED_R145_SETUP_ATTRS."
                )


class TestR316SetupActuallyExercisesSendPath:
    """Layer 4: 调用真实 R145 setUp 后, 模拟 _send_single_notification 流程
    不会 throw AttributeError (runtime contract — 比静态正则检查更强)。"""

    def test_r145_setup_followed_by_send_does_not_raise_attribute_error(self):
        import importlib.machinery
        import importlib.util

        spec_loader = importlib.machinery.SourceFileLoader(
            "_r316_load_r145_module", str(_R145_TEST_PATH)
        )
        spec = importlib.util.spec_from_loader("_r316_load_r145_module", spec_loader)
        assert spec is not None
        mod = importlib.util.module_from_spec(spec)
        spec_loader.exec_module(mod)

        TestClass = mod.TestStreakInRealNotificationManagerSendPath
        case = TestClass()
        case.setUp()

        from unittest.mock import MagicMock

        from ai_intervention_agent.notification_manager import NotificationType

        prov = MagicMock()
        prov.send.return_value = True
        case.mgr._providers[NotificationType.BARK] = prov

        event = case._make_event()
        ok = case.mgr._send_single_notification(NotificationType.BARK, event)

        assert ok is True, (
            "R316: _send_single_notification should return True for "
            "successful provider after R145 setUp"
        )
        bark = case.mgr._stats["providers"]["bark"]
        assert bark["success_streak"] == 1, (
            f"R316 invariant: success_streak must be 1 after 1 successful "
            f"send, but got {bark['success_streak']}. This is the cr62 §4A "
            f"flake — R145 setUp probably missing an attr in "
            f"REQUIRED_R145_SETUP_ATTRS list. Check `_send_single_"
            f"notification` source for new attribute references."
        )


class TestR316LineageMarker:
    """R316 lineage marker — 锁定文档里 R316 是 test-isolation pattern 1st app。"""

    def test_this_file_contains_r316_marker(self):
        text = Path(__file__).read_text(encoding="utf-8")
        assert "R316" in text
        assert "test-isolation" in text or "singleton" in text

    def test_this_file_documents_root_cause(self):
        text = Path(__file__).read_text(encoding="utf-8")
        for keyword in (
            "singleton",
            "_send_single_notification",
            "AttributeError",
            "_record_provider_latency_bucket",
        ):
            assert keyword in text, (
                f"R316 docstring missing root-cause keyword: {keyword!r}"
            )
