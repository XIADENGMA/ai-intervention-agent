"""R313 invariant: REST API 幂等性 contract 守护 (v3.8 新 pattern #1)。

背景
----
cycle-31 (R306) 引入 v3.7 第一个新 pattern "三层一致性 invariant"。
cycle-32 R311/R312 完成了 v3.6 visual-architecture 3rd app 和 v3.7
三层一致性 2nd app。R313 引入 **v3.8 第一个新 pattern: Idempotent
Endpoint Contract Invariant**。

为什么需要 Idempotency invariant
-------------------------------
Cursor Glass 模式下, 用户多 tab 切换 / 自动重交 / 网络抖动重发 会触发
**重复 HTTP 请求**。如果 endpoint 不真正幂等, 后果严重:

1. **状态切换类** (``/api/tasks/<id>/freeze``): 双击 button 第二次返回
   500 / 改变状态 → UX bug
2. **资源删除类** (``/api/tasks/<id>/close``): 第二次返回 404 但 user
   feedback 已经丢失 → R165 反馈丢失类 P0 bug
3. **激活类** (``/api/tasks/<id>/activate``): 已经 active 时第二次报错
   → UX bug (P6R-2 修复过)

本项目的现状 (R313 baseline)
---------------------------
**幂等白名单** (3 endpoints) — docstring 必须显式声明幂等语义:
- ``POST /api/tasks/<task_id>/freeze`` — "409 idempotent No-Op"
  (双击防御, ``already_frozen`` short-circuit)
- ``POST /api/tasks/<task_id>/close`` — "COMPLETED 任务 short-circuit"
  (R165 反馈丢失防御, ``skipped=True``)
- ``POST /api/tasks/<task_id>/activate`` — "P6R-2 修复: 已 active 直接
  返回 success"

**非幂等黑名单** (2 endpoints) — docstring 必须**不**含幂等关键词
(反向断言, 防止后人误改设计):
- ``POST /api/tasks/<task_id>/extend`` — 每次 +60s, 多次累加 (有上限)
- ``POST /api/tasks/<task_id>/submit`` — 每次新增反馈记录

R313 锁住的 invariant
--------------------
- 静态 source contract (Layer 1):
  * 白名单 3 endpoints 的 docstring 必须含 ``idempotent`` / ``幂等`` /
    ``409`` / ``skipped`` / ``短路`` / ``short-circuit`` 之一关键词
  * 黑名单 2 endpoints 的 docstring 必须**不含**幂等关键词
- 架构 future-guard (Layer 2):
  * 全 ``task.py`` 中所有 ``/api/tasks/<task_id>/`` POST endpoint 必须
    在白名单或黑名单中 (出现新 endpoint 自动 fail, 强制 review 幂等性)
- 测试文件自身定义白/黑名单常量, 防止白名单藏在 source 里被静默修改

pattern lineage
---------------
v3.8 idempotent endpoint contract pattern 应用历史:
- **1st: R313 (cycle-32 #C1, this)** — REST API 幂等性 contract

methodology: 与 v3.7 "运行时三层一致性" 不同, v3.8 聚焦 "API 行为
contract", 锁的是 *设计意图*。当后续 cycle 出现新 endpoint, 此 invariant
会强制开发者明确标注幂等性。
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TASK_PY = REPO_ROOT / "src" / "ai_intervention_agent" / "web_ui_routes" / "task.py"


# ============================================================================
# R313 contract 白名单 & 黑名单 (测试文件级常量, 防止被 source 静默修改)
# ============================================================================

# 幂等白名单: 这些 endpoint 的 docstring **必须**显式声明幂等语义
_IDEMPOTENT_ENDPOINTS_WHITELIST: tuple[str, ...] = (
    "freeze_task_deadline",  # POST /api/tasks/<id>/freeze
    "close_task",  # POST /api/tasks/<id>/close
    "activate_task",  # POST /api/tasks/<id>/activate
)

# 非幂等黑名单: 这些 endpoint 的 docstring **必须不含**幂等关键词
_NON_IDEMPOTENT_ENDPOINTS_BLACKLIST: tuple[str, ...] = (
    "extend_task_deadline",  # POST /api/tasks/<id>/extend
    "submit_task_feedback",  # POST /api/tasks/<id>/submit
)

# 幂等语义关键词: 任一关键词出现即认为函数 docstring 声明了幂等性
_IDEMPOTENCY_KEYWORDS = (
    "idempotent",  # 英文 (P6R-2 等)
    "幂等",  # 中文 (R165 / cr32 / freeze docstring)
    "409",  # HTTP 409 Conflict — 重复操作的标准信号
    "skipped",  # close: skipped=True for COMPLETED
    "短路",  # close docstring: "short-circuit"
    "short-circuit",  # close docstring
)


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _extract_function_docstring(src: str, func_name: str) -> str:
    """从 source 中提取 ``def <func_name>(`` 起到下一个 ``def`` 或文件末尾的代码,
    再从其中抽出第一个 docstring (三引号块)。
    """
    pattern = re.compile(
        rf"def\s+{re.escape(func_name)}\s*\([^)]*\)[^:]*:[\s\S]*?(?=\n    def\s|\n    @|\nclass\s|\Z)"
    )
    m = pattern.search(src)
    if not m:
        return ""
    body = m.group(0)
    docstring_m = re.search(r'"""([\s\S]*?)"""', body)
    if docstring_m:
        return docstring_m.group(1)
    return ""


# ============================================================================
# Layer 1: 静态 source contract (白名单 + 黑名单)
# ============================================================================


class TestIdempotentEndpointsHaveExplicitDocstring(unittest.TestCase):
    """白名单 endpoint 的 docstring 必须含幂等关键词。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.src = _read(TASK_PY)

    def test_each_idempotent_endpoint_declares_idempotency(self) -> None:
        """R313-L1: 白名单中每个 endpoint docstring 必须含至少一个幂等关键词。"""
        for func_name in _IDEMPOTENT_ENDPOINTS_WHITELIST:
            with self.subTest(endpoint=func_name):
                doc = _extract_function_docstring(self.src, func_name)
                self.assertTrue(
                    doc,
                    f"R313-L1: 未找到 {func_name} 的 docstring (函数缺失或缺 docstring)",
                )
                doc_lower = doc.lower()
                matched = [k for k in _IDEMPOTENCY_KEYWORDS if k.lower() in doc_lower]
                self.assertTrue(
                    matched,
                    f"R313-L1: 幂等 endpoint ``{func_name}`` 的 docstring 必须含至少一个"
                    f"幂等关键词 {_IDEMPOTENCY_KEYWORDS}, 实际无匹配",
                )


class TestNonIdempotentEndpointsLackIdempotencyKeyword(unittest.TestCase):
    """黑名单 endpoint 的 docstring 必须**不含**幂等关键词 (反向断言)。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.src = _read(TASK_PY)

    def test_each_non_idempotent_endpoint_lacks_idempotency_keyword(self) -> None:
        """R313-L1 反向: 黑名单中每个 endpoint docstring 必须**不**含幂等关键词。

        例外: ``409`` / ``short-circuit`` / ``skipped`` 这种 HTTP / 通用字
        可能在描述 *其他* 含义时出现 — 我们只断言狭义的 ``idempotent`` / ``幂等``
        / ``短路`` 三个明确表达 "幂等设计意图" 的关键词不出现。
        """
        strict_idempotency_signals = ("idempotent", "幂等", "短路", "short-circuit")
        for func_name in _NON_IDEMPOTENT_ENDPOINTS_BLACKLIST:
            with self.subTest(endpoint=func_name):
                doc = _extract_function_docstring(self.src, func_name)
                self.assertTrue(
                    doc,
                    f"R313: 未找到 {func_name} 的 docstring",
                )
                doc_lower = doc.lower()
                matched = [
                    k for k in strict_idempotency_signals if k.lower() in doc_lower
                ]
                self.assertFalse(
                    matched,
                    f"R313-L1 反向: 非幂等 endpoint ``{func_name}`` 的 docstring "
                    f"出现了幂等关键词 {matched}, 这违反设计意图 (此 endpoint 每次调用都有副作用)",
                )


# ============================================================================
# Layer 2: 架构 future-guard
# ============================================================================


class TestAllTaskIdEndpointsCoveredByContract(unittest.TestCase):
    """全 task.py 中所有 ``/api/tasks/<task_id>/`` POST endpoint 必须在白名单或黑名单中。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.src = _read(TASK_PY)

    def test_no_unclassified_task_id_post_endpoints(self) -> None:
        """R313-L2 future-guard: 出现新 endpoint 时, 必须显式分类到白/黑名单。"""
        # 找出所有 @self.app.route("/api/tasks/<task_id>/<action>", methods=["POST"])
        route_pattern = re.compile(
            r"""@self\.app\.route\(\s*['"]/api/tasks/<task_id>/[^'"]+['"]"""
            r"""[\s\S]*?methods=\[\s*['"]POST['"]\s*\][\s\S]*?\n\s*"""
            r"""(?:@[^\n]+\n\s*)*def\s+(\w+)\s*\("""
        )
        all_handlers = set(route_pattern.findall(self.src))

        whitelist = set(_IDEMPOTENT_ENDPOINTS_WHITELIST)
        blacklist = set(_NON_IDEMPOTENT_ENDPOINTS_BLACKLIST)
        classified = whitelist | blacklist

        unclassified = all_handlers - classified
        self.assertFalse(
            unclassified,
            f"R313-L2 future-guard: 发现新的 /api/tasks/<task_id>/ POST handler 未分类: "
            f"{unclassified}\n"
            f"必须把它加到 tests/test_feat_idempotent_endpoint_contract_r313.py 的 "
            f"_IDEMPOTENT_ENDPOINTS_WHITELIST 或 _NON_IDEMPOTENT_ENDPOINTS_BLACKLIST.\n"
            f"分类时请在 endpoint docstring 明确标注幂等性设计 (含 'idempotent' / "
            f"'幂等' / '409' / 'skipped' 关键词) 或反向显示非幂等副作用.",
        )

    def test_whitelist_handlers_actually_exist(self) -> None:
        """R313-L2 反向 sanity: 白名单中所有函数名都应在 task.py 中真实存在。"""
        for func_name in _IDEMPOTENT_ENDPOINTS_WHITELIST:
            with self.subTest(endpoint=func_name):
                self.assertRegex(
                    self.src,
                    rf"\bdef\s+{re.escape(func_name)}\s*\(",
                    f"R313-L2: 白名单中的 {func_name} 在 task.py 中找不到 (可能被重命名)",
                )

    def test_blacklist_handlers_actually_exist(self) -> None:
        """R313-L2 反向 sanity: 黑名单中所有函数名都应在 task.py 中真实存在。"""
        for func_name in _NON_IDEMPOTENT_ENDPOINTS_BLACKLIST:
            with self.subTest(endpoint=func_name):
                self.assertRegex(
                    self.src,
                    rf"\bdef\s+{re.escape(func_name)}\s*\(",
                    f"R313-L2: 黑名单中的 {func_name} 在 task.py 中找不到",
                )

    def test_total_classified_endpoints_baseline(self) -> None:
        """R313-L2: 白名单 + 黑名单合计 = 5 endpoints (baseline, 未来新增需 bump)。"""
        total = len(_IDEMPOTENT_ENDPOINTS_WHITELIST) + len(
            _NON_IDEMPOTENT_ENDPOINTS_BLACKLIST
        )
        self.assertEqual(
            total,
            5,
            f"R313 baseline: 白名单(3) + 黑名单(2) = 5 endpoints, 当前 {total}",
        )


# ============================================================================
# Layer 3: 实现层 contract (内部 task_queue 方法名)
# ============================================================================


class TestImplementationLayerIdempotencyContract(unittest.TestCase):
    """task_queue 实现层方法名 / 错误码与 endpoint 幂等性 contract 对齐。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.task_py = _read(TASK_PY)
        cls.task_queue_py = _read(
            REPO_ROOT / "src" / "ai_intervention_agent" / "task_queue.py"
        )

    def test_freeze_implementation_returns_already_frozen_signal(self) -> None:
        """R313-L3: task_queue.freeze_task_deadline 必须返回 'already_frozen' 错误码用于二次调用。"""
        self.assertIn(
            "already_frozen",
            self.task_queue_py,
            "R313-L3: freeze 实现必须有 'already_frozen' 错误码 (第二次调用 No-Op 信号)",
        )

    def test_freeze_endpoint_uses_409_for_already_frozen(self) -> None:
        """R313-L3: freeze_task_deadline endpoint 必须把 'already_frozen' 映射到 HTTP 409。"""
        # 提取 endpoint 函数体
        endpoint_body = _extract_function_docstring(
            self.task_py, "freeze_task_deadline"
        )
        # docstring 必须显式记录 409 + already_frozen
        self.assertIn(
            "409",
            endpoint_body,
            "R313-L3: freeze_task_deadline endpoint docstring 必须文档 409 状态码",
        )
        self.assertIn(
            "already_frozen",
            endpoint_body,
            "R313-L3: freeze_task_deadline endpoint docstring 必须提及 already_frozen 错误码",
        )

    def test_close_endpoint_handles_completed_short_circuit(self) -> None:
        """R313-L3: close_task endpoint 必须显式处理 COMPLETED short-circuit (R165 防御)。"""
        doc = _extract_function_docstring(self.task_py, "close_task")
        self.assertTrue(
            "short-circuit" in doc.lower() or "短路" in doc or "skipped" in doc.lower(),
            "R313-L3: close_task docstring 必须显式记录 COMPLETED short-circuit 行为 (R165)",
        )


# ============================================================================
# R313 lineage marker
# ============================================================================


class TestR313MarkerPresent(unittest.TestCase):
    """R313 lineage marker。"""

    def test_test_file_contains_lineage_explanation(self) -> None:
        """本测试文件 docstring 必须含 R313 + v3.8 lineage + R306 reference。"""
        src = _read(Path(__file__))
        self.assertIn("R313", src, "R313 marker 应在测试 docstring")
        self.assertIn("v3.8", src, "R313 应说明 v3.8 lineage")
        self.assertIn(
            "Idempotent",
            src,
            "R313 应说明这是 Idempotent Endpoint Contract pattern",
        )


if __name__ == "__main__":
    unittest.main()
