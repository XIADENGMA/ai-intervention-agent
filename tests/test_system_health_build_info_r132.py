"""R132 · ``GET /api/system/health`` 暴露 build info（git commit / branch / dirty）契约。

背景
----
R63 早就在 ``server._resolve_build_info()`` 里 lazy 解析了 git_commit
/ git_branch / git_dirty 三个 build 元信息（用于 ``aiia://server/info``
MCP resource）。R121-A 把 health 端点扩展到 K8s probe 主流形态时只
带了 ``version`` / ``uptime_seconds`` / ``config_file_path``——但是
``version`` 字符串（如 ``v1.5.45``）可能对应过 100 个 commit，对监
控做 PR rollout 时仍不够精确：「新版本上线了吗 / 这个实例还在跑老
commit 吗 / 是 dirty 工作树吗」三个问题没法一眼回答。

R132 把 R63 既有的 ``_resolve_build_info()`` 投影到 health 顶层
``build`` 字段：

    {
      ...
      "version": "v1.5.45",
      "build": {
        "git_commit": "8196168",
        "git_branch": "main",
        "git_dirty": "no"
      },
      ...
    }

实现策略：
- 复用 R63 的 lazy + module-level cache（``_BUILD_INFO_CACHE``），10s
  K8s probe 周期性拉取 health 时不会炸 fork 风暴；
- pip / docker / pyinstaller 没 ``.git`` 时字段全是 ``"unknown"``，
  handler 不当作错误返回——保留 R63 的"unknown 不是失败"契约；
- 整体 import / 调用失败时返回 None，handler 兜底为 null。

设计意图：health endpoint 是监控仪表板的命脉，新字段必须有自动化
回归保护，特别是「pip 部署没 .git 时也不能炸」这条边界行为。

测试覆盖三个层面（共 9 cases / 3 invariant classes）：

1.  **handler 顶层暴露** — ``system_health()`` body 含 ``"build"`` 顶层
    字段 + 调用 ``_safe_build_info()`` helper（不直接调 ``server._resolve_build_info``，
    保留 R53-F 的"handler 不直接读 server module"契约）；Swagger
    docstring 描述 ``build`` 字段。
2.  **helper 行为契约** — ``_safe_build_info`` 在 module 级别可调；
    正常情况下返回 dict，含三个字段 + 字段值都是 str；任何 import
    错误 / 异常都 graceful 返回 None；`server._resolve_build_info`
    返回非 dict 时返回 None。
3.  **R53-F / R121-A 回归** — handler body 不含 ``server._resolve_build_info()``
    直接调用（必须走 helper）；不引入新 ``get_config()`` 调用；
    既有 ``version`` / ``uptime_seconds`` / ``config_file_path`` 字段
    仍存在；``status`` enum 三个值不变。
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ai_intervention_agent.web_ui_routes import system as system_module

SOURCE = Path(system_module.__file__).read_text(encoding="utf-8")


def _system_health_body() -> str:
    """提取 ``system_health()`` handler 的源码片段（与 R121 测试同款实现）。"""
    m = re.search(
        r"def system_health\(\).*?(?=\n        @self\.app\.route|\nclass )",
        SOURCE,
        re.DOTALL,
    )
    if not m:
        raise AssertionError("无法在 system.py 里定位 system_health() handler 体")
    return m.group(0)


# ---------------------------------------------------------------------------
# 1. handler 顶层暴露
# ---------------------------------------------------------------------------


class TestBuildInfoExposedInHandler(unittest.TestCase):
    def setUp(self) -> None:
        self.body = _system_health_body()

    def test_handler_emits_build_top_level_field(self) -> None:
        # payload 字典字面量里必须有 ``"build":`` 键，与 ``version`` /
        # ``uptime_seconds`` / ``config_file_path`` 同一个 dict
        self.assertIn(
            '"build"',
            self.body,
            "/api/system/health payload 必须含顶层 build 字段（R132）",
        )

    def test_handler_uses_safe_build_info_helper(self) -> None:
        self.assertIn(
            "_safe_build_info()",
            self.body,
            "build 字段必须走 _safe_build_info() helper（避免 handler 直接调 server._resolve_build_info）",
        )

    def test_handler_does_not_call_resolve_build_info_directly(self) -> None:
        # handler 不能绕过 helper 直接调 ``server._resolve_build_info``，
        # 否则任何抛异常的修改都会让 health 端点 5xx
        self.assertNotIn(
            "_resolve_build_info()",
            self.body,
            "handler 不能直接调 server._resolve_build_info()，必须走 _safe_build_info helper",
        )

    def test_swagger_doc_describes_build_field(self) -> None:
        # docstring 是 flasgger 生成 OpenAPI spec 的源头；R132 字段必须
        # 在文档里有提（与 version / uptime_seconds 等并列）
        self.assertRegex(
            self.body,
            r"``build``\s*[（(]R132[)）]",
            "system_health docstring 必须提到 build 字段（R132 标记）",
        )


# ---------------------------------------------------------------------------
# 2. helper 行为契约
# ---------------------------------------------------------------------------


class TestSafeBuildInfoHelper(unittest.TestCase):
    def test_helper_defined_at_module_level(self) -> None:
        self.assertTrue(
            hasattr(system_module, "_safe_build_info"),
            "_safe_build_info 必须在 module 级别可调用（与其它 _safe_* helper 同级）",
        )

    def test_returns_dict_with_three_fields_when_healthy(self) -> None:
        result = system_module._safe_build_info()
        self.assertIsNotNone(result, "正常情况下应返回 dict（即便字段值是 'unknown'）")
        assert result is not None
        self.assertIsInstance(result, dict)
        self.assertEqual(
            set(result.keys()),
            {"git_commit", "git_branch", "git_dirty"},
            "build 字段必须严格是 git_commit / git_branch / git_dirty 三件套",
        )
        for key, value in result.items():
            self.assertIsInstance(
                value, str, f"build.{key} 必须是字符串（含 'unknown' 兜底）"
            )

    def test_returns_none_when_resolve_build_info_returns_non_dict(self) -> None:
        with patch(
            "ai_intervention_agent.server._resolve_build_info",
            return_value="not a dict",
        ):
            result = system_module._safe_build_info()
            self.assertIsNone(
                result,
                "_resolve_build_info 返回非 dict 时必须 graceful 返回 None",
            )

    def test_returns_none_on_resolve_exception(self) -> None:
        with patch(
            "ai_intervention_agent.server._resolve_build_info",
            side_effect=RuntimeError("simulated git subprocess failure"),
        ):
            result = system_module._safe_build_info()
            self.assertIsNone(
                result,
                "_resolve_build_info 抛异常时必须 graceful 返回 None（health 端点不应 5xx）",
            )

    def test_unknown_values_pass_through_when_dot_git_missing(self) -> None:
        # 模拟 pip 部署没 .git 的场景：_resolve_build_info 返回全 "unknown"
        # helper 仍应返回 dict（保留 R63 契约：unknown 不是失败）
        fake_info = {
            "git_commit": "unknown",
            "git_branch": "unknown",
            "git_dirty": "unknown",
        }
        with patch(
            "ai_intervention_agent.server._resolve_build_info",
            return_value=fake_info,
        ):
            result = system_module._safe_build_info()
            self.assertEqual(
                result,
                fake_info,
                "全 'unknown' 是 R63 契约下的合法值，helper 不能把它当失败处理",
            )


# ---------------------------------------------------------------------------
# 3. R53-F / R121-A 回归保护
# ---------------------------------------------------------------------------


class TestNoExistingContractsBroken(unittest.TestCase):
    def setUp(self) -> None:
        self.body = _system_health_body()

    def test_existing_top_level_fields_still_present(self) -> None:
        for field in ('"version"', '"uptime_seconds"', '"config_file_path"'):
            self.assertIn(
                field,
                self.body,
                f"R132 不应破坏 R121-A 既有 {field} 字段",
            )

    def test_no_new_get_config_in_handler_body(self) -> None:
        # R53-F 契约：handler 不能直接读 config。R132 仅复用既有 helper
        # 路径，不应引入新的 get_config() 调用
        self.assertNotIn(
            "get_config()",
            self.body,
            "R132 不应破坏 R53-F 契约（handler 不直接调 get_config）",
        )

    def test_status_enum_unchanged(self) -> None:
        for value in ('"healthy"', '"degraded"', '"unhealthy"'):
            self.assertIn(
                value,
                self.body,
                f"R132 不应改变 R53-F status enum：{value}",
            )

    def test_503_decision_intact(self) -> None:
        self.assertRegex(
            self.body,
            r'503\s+if\s+status\s*==\s*"unhealthy"',
            "R132 不应破坏 503 ↔ unhealthy 决策（R53-F）",
        )


if __name__ == "__main__":
    unittest.main()
