"""R318 · `/api/system/*` POST endpoint 幂等性 contract invariant
(v3.8 idempotent endpoint contract pattern 2nd app)。

背景
----

cr62 §5 把 v3.8 idempotent endpoint contract pattern 列为 cycle-33 重点推
进项 (C1 task)。R313 (cr62, 1st app) 锁定了 ``/api/tasks/<task_id>/*``
POST endpoints 的幂等性 contract:

- 白名单 (幂等): ``freeze_task_deadline`` / ``close_task`` / ``activate_task``
- 黑名单 (非幂等): ``extend_task_deadline`` / ``submit_task_feedback``

R318 是 2nd app, 覆盖**另一个 API 命名空间** ``/api/system/*``, 锁定 4 个
POST endpoint 的幂等性 contract:

**白名单 (幂等, idempotent)**:

- ``system_log_level_post`` — 设置同一 ``level`` N 次, root logger 最终状
  态收敛 (重复 SSE emit 不影响 contract)

**黑名单 (非幂等, non-idempotent)** — 必须**明确写**不幂等理由 + 客户端
不要重试警告:

- ``system_notifications_test`` — 每次发真实通知 (用户手机响铃 / 振动)
- ``open_config_file`` — 每次 spawn 新 subprocess (PID / fd 消耗)
- ``rotate_api_token`` — 每次生成新 token (旧 token 立即失效, security
  blast radius)

**Pattern lineage (v3.8 idempotent endpoint contract)**:

- 1st app: R313 (cr62) — ``/api/tasks/<task_id>/*``
- **2nd app: R318 (本 commit)** — ``/api/system/*``

**为什么不同 API 命名空间分别锁?** API contract 由 client 期望决定:
``/api/tasks/`` 的客户端是 web UI + 单一用户; ``/api/system/`` 的客户端
是运维 dashboard + 监控脚本 + 自动化。后者更容易写 retry loop (因为是
"系统脚本"心智), 所以**额外强调** "非幂等不要重试" 警告。
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
_SYSTEM_PY = SRC / "ai_intervention_agent" / "web_ui_routes" / "system.py"


_IDEMPOTENT_SYSTEM_ENDPOINTS_WHITELIST = ("system_log_level_post",)
"""幂等 ``/api/system/*`` POST endpoints — docstring 必须显式声明幂等性。"""

_NON_IDEMPOTENT_SYSTEM_ENDPOINTS_BLACKLIST = (
    "system_notifications_test",
    "open_config_file",
    "rotate_api_token",
)
"""非幂等 ``/api/system/*`` POST endpoints — docstring 必须显式声明**非**幂
等性 + 客户端不要重试警告。"""

_IDEMPOTENCY_KEYWORDS = (
    "幂等",
    "idempotent",
    "收敛",
    "短路",
    "short-circuit",
)
_NON_IDEMPOTENCY_KEYWORDS = (
    "不幂等",
    "non-idempotent",
    "non idempotent",
    "non-pure",
    "禁止重试",
    "不要重试",
    "不能重试",
    "绝对不能",
    "严禁",
    "no retry",
    "do not retry",
)


def _extract_function_docstring(file_text: str, func_name: str) -> str | None:
    """从 Python 源码文本里抽取指定函数的 docstring (允许 leading newlines)。"""
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


class TestSystemEndpointFunctionsExist:
    """Layer 1: 4 个目标函数都必须存在于源码 (anchor verification)。"""

    def test_notification_py_exists(self):
        assert _NOTIFICATION_PY.is_file()

    def test_system_py_exists(self):
        assert _SYSTEM_PY.is_file()

    def test_all_4_target_endpoints_exist(self, subtests):
        notif_text = _NOTIFICATION_PY.read_text(encoding="utf-8")
        sys_text = _SYSTEM_PY.read_text(encoding="utf-8")
        all_funcs = (
            _IDEMPOTENT_SYSTEM_ENDPOINTS_WHITELIST
            + _NON_IDEMPOTENT_SYSTEM_ENDPOINTS_BLACKLIST
        )
        for func_name in all_funcs:
            with subtests.test(func=func_name):
                # function 必须在 notification.py 或 system.py 至少一个里出现
                found = re.search(
                    rf"def\s+{re.escape(func_name)}\s*\(", notif_text
                ) or re.search(rf"def\s+{re.escape(func_name)}\s*\(", sys_text)
                assert found, (
                    f"R318 anchor missing: function `{func_name}` not found "
                    "in notification.py or system.py"
                )


class TestIdempotentSystemEndpointsDeclareIdempotency:
    """Layer 2 (白名单): 幂等 ``/api/system/*`` endpoints docstring 必须显式
    声明 "幂等"。"""

    def _load_file_text_for(self, func_name: str) -> str:
        if func_name == "system_notifications_test":
            return _NOTIFICATION_PY.read_text(encoding="utf-8")
        return _SYSTEM_PY.read_text(encoding="utf-8")

    def test_idempotent_endpoint_declares_idempotency(self, subtests):
        for func_name in _IDEMPOTENT_SYSTEM_ENDPOINTS_WHITELIST:
            with subtests.test(func=func_name):
                file_text = self._load_file_text_for(func_name)
                doc = _extract_function_docstring(file_text, func_name)
                assert doc, (
                    f"R318: cannot extract docstring for `{func_name}` "
                    f"(white-list idempotent endpoint)"
                )
                doc_lower = doc.lower()
                hits = [kw for kw in _IDEMPOTENCY_KEYWORDS if kw.lower() in doc_lower]
                assert hits, (
                    f"R318: idempotent endpoint `{func_name}` docstring must "
                    f"explicitly declare idempotency via one of "
                    f"{_IDEMPOTENCY_KEYWORDS}. Found none. Doc preview: "
                    f"{doc[:200]!r}"
                )


class TestNonIdempotentSystemEndpointsDeclareNonIdempotency:
    """Layer 2 (黑名单): 非幂等 ``/api/system/*`` endpoints docstring 必须
    显式声明 "不幂等" + 不要重试警告。"""

    def _load_file_text_for(self, func_name: str) -> str:
        if func_name == "system_notifications_test":
            return _NOTIFICATION_PY.read_text(encoding="utf-8")
        return _SYSTEM_PY.read_text(encoding="utf-8")

    def test_non_idempotent_endpoint_declares_non_idempotency(self, subtests):
        for func_name in _NON_IDEMPOTENT_SYSTEM_ENDPOINTS_BLACKLIST:
            with subtests.test(func=func_name):
                file_text = self._load_file_text_for(func_name)
                doc = _extract_function_docstring(file_text, func_name)
                assert doc, (
                    f"R318: cannot extract docstring for `{func_name}` "
                    f"(black-list non-idempotent endpoint)"
                )
                doc_lower = doc.lower()
                hits = [
                    kw for kw in _NON_IDEMPOTENCY_KEYWORDS if kw.lower() in doc_lower
                ]
                assert hits, (
                    f"R318: non-idempotent endpoint `{func_name}` docstring "
                    f"must explicitly warn (one of {_NON_IDEMPOTENCY_KEYWORDS}). "
                    f"Found none. Doc preview: {doc[:200]!r}"
                )


class TestSystemEndpointsFutureGuard:
    """Layer 3 (future-guard): 任何新增 ``/api/system/*`` POST endpoint 必须
    被显式分类到白名单或黑名单, 否则 invariant fail, 强制 review。

    这是和 R313 同款的 future-guard. 当未来 PR 加新 ``/api/system/*``
    POST endpoint 时, R318 立即 fail, 阻止 silent contract drift.
    """

    def _enumerate_system_post_endpoints(self) -> list[str]:
        """枚举两个 routes module 里**所有** ``/api/system/*`` POST 端点的
        Python 函数名。"""
        endpoints: list[str] = []
        for path in (_NOTIFICATION_PY, _SYSTEM_PY):
            text = path.read_text(encoding="utf-8")
            # @self.app.route("/api/system/...", methods=["POST"])
            # 或 methods=["POST", ...]
            route_pattern = re.compile(
                r"@self\.app\.route\(\s*[\"']/api/system/[^\"']*[\"']\s*,"
                r"[^)]*methods=\[[^\]]*[\"']POST[\"'][^\]]*\]"
                r"[^)]*\)\s*\n"
                r"(?:\s*@[^\n]+\n)*"  # 任意装饰器 (limiter 等)
                r"\s*def\s+(\w+)\s*\(",
                re.MULTILINE,
            )
            endpoints.extend(route_pattern.findall(text))
        return endpoints

    def test_at_least_4_system_post_endpoints_found(self):
        endpoints = self._enumerate_system_post_endpoints()
        assert len(endpoints) >= 4, (
            f"R318: expected at least 4 /api/system/* POST endpoints "
            f"(matches white+black list), but only found {len(endpoints)}: "
            f"{endpoints}. If you removed an endpoint, update "
            f"_IDEMPOTENT_SYSTEM_ENDPOINTS_WHITELIST / "
            f"_NON_IDEMPOTENT_SYSTEM_ENDPOINTS_BLACKLIST to match."
        )

    def test_every_system_post_endpoint_classified(self, subtests):
        endpoints = self._enumerate_system_post_endpoints()
        classified = set(
            _IDEMPOTENT_SYSTEM_ENDPOINTS_WHITELIST
            + _NON_IDEMPOTENT_SYSTEM_ENDPOINTS_BLACKLIST
        )
        for ep in endpoints:
            with subtests.test(endpoint=ep):
                assert ep in classified, (
                    f"R318 future-guard: NEW /api/system/* POST endpoint "
                    f"`{ep}` is NOT classified as idempotent or "
                    f"non-idempotent. **You must**:\n"
                    f"  1. Decide whether `{ep}` is idempotent (same call "
                    f"N times → state converges) or non-idempotent (side "
                    f"effects on every call)\n"
                    f"  2. Add to _IDEMPOTENT_SYSTEM_ENDPOINTS_WHITELIST or "
                    f"_NON_IDEMPOTENT_SYSTEM_ENDPOINTS_BLACKLIST in "
                    f"test_feat_system_endpoint_idempotency_r318.py\n"
                    f"  3. Document the choice in `{ep}` docstring with "
                    f"idempotency keyword (whitelist) or non-idempotency "
                    f"warning (blacklist)\n"
                    f"This is R313 / R318 / v3.8 contract requirement."
                )


class TestR318LineageMarker:
    """Pattern lineage marker — 锁定 R318 是 v3.8 idempotent pattern 2nd app。"""

    def test_this_file_contains_r318_marker(self):
        text = Path(__file__).read_text(encoding="utf-8")
        assert "R318" in text
        assert "idempotent" in text.lower() or "幂等" in text

    def test_this_file_references_prior_app_r313(self):
        text = Path(__file__).read_text(encoding="utf-8")
        assert "R313" in text, (
            "R318 docstring must cite R313 as v3.8 idempotent pattern 1st app"
        )

    def test_this_file_documents_white_and_black_list(self):
        text = Path(__file__).read_text(encoding="utf-8")
        for kw in (
            "白名单",
            "黑名单",
            "system_log_level_post",
            "system_notifications_test",
            "rotate_api_token",
        ):
            assert kw in text, f"R318 docstring missing keyword: {kw!r}"
