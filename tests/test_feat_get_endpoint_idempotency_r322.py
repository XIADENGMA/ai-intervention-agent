"""R322 · ``/api/get-*`` GET endpoint 幂等性 contract invariant
(v3.8 idempotent endpoint contract pattern 3rd app)。

背景
----

v3.8 idempotent endpoint contract pattern 至今已有 2 个 app:

- 1st R313 (cr62): ``/api/tasks/<task_id>/*`` POST endpoints — 区分白
  (freeze / close / activate) + 黑 (extend / submit) 名单
- 2nd R318 (cr63): ``/api/system/*`` POST endpoints — 区分白
  (system_log_level_post) + 黑 (notifications/test + open-config-file +
  rotate-api-token) 名单

R322 (cycle-34 #B1, 本 commit) 是 **3rd app**, 把 invariant 覆盖范围从
POST 扩展到 GET endpoints, 锁定 ``/api/get-*`` 命名空间下的所有 GET 端点
都显式标注 HTTP RFC 7231 §4.2.1 + §4.2.2 的 "safe + idempotent" 语义。

**为什么 GET 也要锁?**

GET 在 HTTP 语义上默认 safe + idempotent, 但**实际工程中**:

- 有些 GET 实现可能 lazy-init 缓存 / 触发 background metric / 写 audit
  log (违反 safe)
- 有些 GET 实现可能 mutate session state / consume rate-limit quota
  (违反 idempotent)
- 没有显式 docstring 声明 → 后续维护者可能不知道这些 implicit contract

R322 强制每个 ``/api/get-*`` GET endpoint:

1. **docstring 显式声明 safe + idempotent** (含 RFC 7231 引用或同义关键
   词)
2. **future-guard**: 任何新增 ``/api/get-*`` GET endpoint 必须被列入白名
   单 + 满足上述 contract, 否则 invariant fail

**Pattern lineage (v3.8 idempotent contract)**:

- 1st app: R313 — ``/api/tasks/<task_id>/*`` POST
- 2nd app: R318 — ``/api/system/*`` POST
- **3rd app: R322 (本 commit)** — ``/api/get-*`` GET

**里程碑**: v3.8 idempotent pattern 达 3 应用进入**完全工业化**, 是 v3.8
第 1 个完全工业化的 pattern (test-isolation R323 在 cycle-34 同 cycle 推
3rd 也将达到)。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

_NOTIFICATION_PY = SRC / "ai_intervention_agent" / "web_ui_routes" / "notification.py"


_IDEMPOTENT_GET_ENDPOINTS_WHITELIST = (
    "get_notification_config",
    "get_feedback_prompts_api",
)
"""``/api/get-*`` GET endpoints — 必须显式声明 safe + idempotent。"""


_GET_IDEMPOTENCY_KEYWORDS = (
    "idempotent",
    "safe",
    "幂等",
    "RFC 7231",
    "rfc 7231",
)


def _extract_function_docstring(file_text: str, func_name: str) -> str | None:
    """从 Python 源码文本里抽取指定函数的 docstring。"""
    pattern = (
        rf"def\s+{re.escape(func_name)}\s*\([^)]*\)\s*"
        r"(?:->\s*[^:]+)?:\s*\n"
        r"\s*(?:r|u|b|rb|br|f|rf|fr)?(?P<quote>[\"']{3})"
        r"(?P<body>.*?)(?P=quote)"
    )
    m = re.search(pattern, file_text, re.DOTALL)
    if not m:
        return None
    return m.group("body")


class TestGetEndpointFunctionsExist:
    """Layer 1: 所有目标 GET 函数必须存在 (anchor)。"""

    def test_notification_py_exists(self):
        assert _NOTIFICATION_PY.is_file()

    def test_all_target_endpoints_exist(self, subtests):
        text = _NOTIFICATION_PY.read_text(encoding="utf-8")
        for func_name in _IDEMPOTENT_GET_ENDPOINTS_WHITELIST:
            with subtests.test(func=func_name):
                found = re.search(rf"def\s+{re.escape(func_name)}\s*\(", text)
                assert found, (
                    f"R322 anchor missing: function `{func_name}` not found "
                    f"in notification.py"
                )


class TestIdempotentGetEndpointsDeclareIdempotency:
    """Layer 2 (白名单): 每个 ``/api/get-*`` GET endpoint docstring 必须显
    式声明 HTTP safe + idempotent 语义。"""

    def test_idempotent_get_declares_safe_and_idempotent(self, subtests):
        text = _NOTIFICATION_PY.read_text(encoding="utf-8")
        for func_name in _IDEMPOTENT_GET_ENDPOINTS_WHITELIST:
            with subtests.test(func=func_name):
                doc = _extract_function_docstring(text, func_name)
                assert doc, (
                    f"R322: cannot extract docstring for `{func_name}` "
                    f"(white-list idempotent GET endpoint)"
                )
                doc_lower = doc.lower()
                hits = [
                    kw for kw in _GET_IDEMPOTENCY_KEYWORDS if kw.lower() in doc_lower
                ]
                assert hits, (
                    f"R322: GET endpoint `{func_name}` docstring must "
                    f"explicitly declare safe + idempotent semantics via "
                    f"one of {_GET_IDEMPOTENCY_KEYWORDS}. Found none. "
                    f"Doc preview: {doc[:200]!r}"
                )

    def test_idempotent_get_mentions_no_side_effects(self, subtests):
        """更强 contract: docstring 应该提到 "no side-effect" / "0 影响" /
        "safe" 等关键词, 强调真正的 safe (RFC 7231 §4.2.1)。"""
        text = _NOTIFICATION_PY.read_text(encoding="utf-8")
        side_effect_keywords = (
            "no side",
            "side-effect",
            "无副作用",
            "无 side",
            "0 影响",
            "无影响",
            "side effect",
            "0 影响",
        )
        for func_name in _IDEMPOTENT_GET_ENDPOINTS_WHITELIST:
            with subtests.test(func=func_name):
                doc = _extract_function_docstring(text, func_name)
                assert doc
                doc_lower = doc.lower()
                hits = sum(1 for kw in side_effect_keywords if kw.lower() in doc_lower)
                assert hits >= 1, (
                    f"R322: GET endpoint `{func_name}` docstring should "
                    f"mention safe / no-side-effect explicitly (one of "
                    f"{side_effect_keywords})"
                )


class TestGetEndpointsFutureGuard:
    """Layer 3 (future-guard): 任何新增 ``/api/get-*`` GET endpoint 必须被
    显式分类到白名单, 否则 invariant fail。

    R322 不允许任何 ``/api/get-*`` GET endpoint 是 "未分类" 状态。
    """

    def _enumerate_get_dash_endpoints(self) -> list[str]:
        """枚举 ``/api/get-*`` GET 端点的 Python 函数名。"""
        endpoints: list[str] = []
        # 当前只有 notification.py 含 /api/get-* 路由, 但 future-guard
        # 应能识别其他 module
        for routes_module in (_NOTIFICATION_PY,):
            text = routes_module.read_text(encoding="utf-8")
            route_pattern = re.compile(
                r"@self\.app\.route\(\s*[\"']/api/get-[^\"']*[\"']\s*,"
                r"[^)]*methods=\[[^\]]*[\"']GET[\"'][^\]]*\]"
                r"[^)]*\)\s*\n"
                r"(?:\s*@[^\n]+\n)*"  # 任意装饰器 (limiter 等)
                r"\s*def\s+(\w+)\s*\(",
                re.MULTILINE,
            )
            endpoints.extend(route_pattern.findall(text))
        return endpoints

    def test_at_least_2_get_dash_endpoints_found(self):
        endpoints = self._enumerate_get_dash_endpoints()
        assert len(endpoints) >= 2, (
            f"R322 anchor: expected at least 2 /api/get-* GET endpoints, "
            f"found {len(endpoints)}: {endpoints}. If you removed an "
            f"endpoint, update _IDEMPOTENT_GET_ENDPOINTS_WHITELIST."
        )

    def test_every_get_dash_endpoint_classified(self, subtests):
        endpoints = self._enumerate_get_dash_endpoints()
        classified = set(_IDEMPOTENT_GET_ENDPOINTS_WHITELIST)
        for ep in endpoints:
            with subtests.test(endpoint=ep):
                assert ep in classified, (
                    f"R322 future-guard: NEW /api/get-* GET endpoint "
                    f"`{ep}` is NOT classified. **You must**:\n"
                    f"  1. Confirm it's truly safe + idempotent (RFC 7231 "
                    f"§4.2.1 + §4.2.2)\n"
                    f"  2. Add to _IDEMPOTENT_GET_ENDPOINTS_WHITELIST in "
                    f"test_feat_get_endpoint_idempotency_r322.py\n"
                    f"  3. Document the semantics in `{ep}` docstring with "
                    f"safe / idempotent / RFC 7231 keywords\n"
                    f"This is R313 / R318 / R322 / v3.8 contract requirement."
                )


class TestR322LineageMarker:
    """Pattern lineage marker — R322 是 v3.8 idempotent pattern 3rd app。"""

    def test_this_file_contains_r322_marker(self):
        text = Path(__file__).read_text(encoding="utf-8")
        assert "R322" in text
        assert "idempotent" in text.lower()

    def test_this_file_references_prior_apps(self):
        text = Path(__file__).read_text(encoding="utf-8")
        for prior in ("R313", "R318"):
            assert prior in text, (
                f"R322 docstring must cite prior idempotent app: {prior}"
            )

    def test_this_file_documents_pattern(self):
        text = Path(__file__).read_text(encoding="utf-8")
        for kw in (
            "3rd app",
            "RFC 7231",
            "get_notification_config",
            "get_feedback_prompts_api",
            "future-guard",
        ):
            assert kw in text, f"R322 docstring missing keyword: {kw!r}"
