"""R220 / Cycle 11 · F-cycle10-4: Grafana dashboard invariant guard.

本测试锁定 `docs/observability/grafana-dashboard.json` 与 AI
Intervention Agent `/metrics` 端点实现 (`system.py` 中的
`_render_prometheus_metrics`) 之间的 silent-decay 边界。

历史教训
========

CR#23 把 `F-cycle10-4` 标为 nice-to-have：R207 新增了
`aiia_sse_schema_violation_total`、R204 新增了
`aiia_token_age_seconds`，但两者都从未在一份 ready-to-import 的
Grafana panel 里被文档化。R220 把 dashboard JSON 加进了
`docs/observability/`，但要避免**未来 refactor**——比如：

* `system.py` 把 metric 改名 (e.g. R204 → R204b)；
* dashboard 写错 metric name 拼写；
* 添加新 panel 但忘了用 `${DS_PROMETHEUS}` 模板变量；
* 把 panel 数量改了而不更新本 invariant；

让 dashboard 显示空图但 CI 全绿——这就是典型 silent decay。本测试
通过以下 contract 关闭这条 decay vector：

1. JSON 可解析 + schemaVersion 在 Grafana 10–11 支持的范围内。
2. UID / title 稳定 (匹配 README 文档里的 import 指引)。
3. 面板数量严格锁定 (改布局必须同步本测试)。
4. 每个面板有非空且全局唯一的 title。
5. 每个面板至少有 1 个 target，且 target 用 `${DS_PROMETHEUS}`
   模板变量 (避免 datasource UID hardcode 导致 import 时报错)。
6. **核心 invariant**：每个 panel target 表达式中引用的
   `aiia_*` metric 名都必须以 substring 形式出现在 `system.py`
   中——这是 dashboard ↔ `/metrics` 实现之间的 binding。
7. 配套 README (`README.md` + `README.zh-CN.md`) 存在且非空。

设计要点
========

* **零 Grafana 依赖**：纯 stdlib `json` + `re`，CI 不需要装
  Grafana CLI / grafonnet / 插件。
* **零 runtime 依赖**：dashboard 是静态文件，本测试也只读文件，
  不启 server。
* **零 false positive**：metric 名通过完整 word boundary 提取
  (regex ``\baiia_[a-zA-Z0-9_]+\b``)，避免 prefix/suffix 误匹配。
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DASHBOARD_PATH = REPO_ROOT / "docs" / "observability" / "grafana-dashboard.json"
README_EN_PATH = REPO_ROOT / "docs" / "observability" / "README.md"
README_ZH_PATH = REPO_ROOT / "docs" / "observability" / "README.zh-CN.md"
SYSTEM_PY_PATH = (
    REPO_ROOT / "src" / "ai_intervention_agent" / "web_ui_routes" / "system.py"
)


def _load_dashboard() -> dict:
    return json.loads(DASHBOARD_PATH.read_text(encoding="utf-8"))


def _extract_aiia_metric_names(text: str) -> set[str]:
    """从任意 PromQL 表达式 / Python 源中抽出 ``aiia_*`` metric name。

    用 word-boundary regex，避免 prefix/suffix 误匹配 (例如不会
    把 ``aiia_foo_bar`` 拆成 ``aiia_foo`` + ``bar``)。
    """
    return set(re.findall(r"\baiia_[a-zA-Z0-9_]+\b", text))


def _collect_panel_target_exprs(panels: list[dict]) -> list[tuple[str, str]]:
    """返回 [(panel_title, expr), ...]，跳过空 target / 缺 expr 的项。"""
    out: list[tuple[str, str]] = []
    for panel in panels:
        title = str(panel.get("title", ""))
        for target in panel.get("targets") or []:
            expr = target.get("expr")
            if isinstance(expr, str) and expr.strip():
                out.append((title, expr))
    return out


class TestDashboardFileExistsAndParses(unittest.TestCase):
    """1. 文件存在 + JSON 合法。"""

    def test_dashboard_file_exists(self) -> None:
        self.assertTrue(
            DASHBOARD_PATH.is_file(),
            f"Dashboard JSON missing: {DASHBOARD_PATH}",
        )

    def test_dashboard_json_parses(self) -> None:
        try:
            data = _load_dashboard()
        except json.JSONDecodeError as exc:
            self.fail(f"Dashboard JSON is not valid: {exc}")
        self.assertIsInstance(
            data,
            dict,
            "Dashboard root must be a JSON object",
        )


class TestDashboardSchemaAndIdentity(unittest.TestCase):
    """2 + 3. schemaVersion 范围 + uid / title 稳定。"""

    SUPPORTED_SCHEMA_VERSIONS = (38, 39, 40)

    def test_schema_version_in_supported_range(self) -> None:
        data = _load_dashboard()
        sv = data.get("schemaVersion")
        self.assertIn(
            sv,
            self.SUPPORTED_SCHEMA_VERSIONS,
            (
                f"schemaVersion={sv} outside the Grafana 10–11 range "
                f"{self.SUPPORTED_SCHEMA_VERSIONS} this dashboard was "
                "authored against. Update both the JSON and this test "
                "deliberately when adopting a newer Grafana major."
            ),
        )

    def test_uid_stable(self) -> None:
        data = _load_dashboard()
        self.assertEqual(
            data.get("uid"),
            "aiia-overview-r220",
            "uid should remain 'aiia-overview-r220' (referenced by README import steps)",
        )

    def test_title_contains_project_name(self) -> None:
        data = _load_dashboard()
        title = data.get("title", "")
        self.assertIsInstance(title, str)
        self.assertIn(
            "AI Intervention Agent",
            title,
            "Dashboard title must mention 'AI Intervention Agent' for Grafana search discoverability",
        )

    def test_datasource_template_variable_declared(self) -> None:
        data = _load_dashboard()
        templating = data.get("templating") or {}
        var_list = templating.get("list") or []
        self.assertTrue(
            any(
                isinstance(v, dict)
                and v.get("name") == "DS_PROMETHEUS"
                and v.get("type") == "datasource"
                for v in var_list
            ),
            "Dashboard must declare a 'DS_PROMETHEUS' datasource template variable "
            "so users can re-bind on import without editing JSON",
        )


class TestDashboardPanelLayout(unittest.TestCase):
    """4 + 5. 面板数量、标题非空且唯一。"""

    EXPECTED_PANEL_COUNT = 7

    def test_panel_count_locked(self) -> None:
        data = _load_dashboard()
        panels = data.get("panels") or []
        self.assertEqual(
            len(panels),
            self.EXPECTED_PANEL_COUNT,
            (
                f"Dashboard panel count drifted: expected "
                f"{self.EXPECTED_PANEL_COUNT}, got {len(panels)}. "
                "If you intentionally added / removed panels, also update "
                "EXPECTED_PANEL_COUNT here and the panel table in "
                "docs/observability/README.md."
            ),
        )

    def test_every_panel_has_non_empty_unique_title(self) -> None:
        data = _load_dashboard()
        panels = data.get("panels") or []
        titles: list[str] = []
        for idx, panel in enumerate(panels):
            title = panel.get("title")
            with self.subTest(panel_index=idx):
                self.assertIsInstance(
                    title,
                    str,
                    f"Panel #{idx} title must be a string",
                )
                self.assertTrue(
                    title and title.strip(),
                    f"Panel #{idx} title is empty",
                )
                titles.append(title)
        self.assertEqual(
            len(titles),
            len(set(titles)),
            f"Panel titles must be unique; got duplicates: {titles}",
        )

    def test_every_panel_has_at_least_one_target(self) -> None:
        data = _load_dashboard()
        panels = data.get("panels") or []
        for idx, panel in enumerate(panels):
            with self.subTest(panel_index=idx, title=panel.get("title", "")):
                targets = panel.get("targets") or []
                self.assertGreaterEqual(
                    len(targets),
                    1,
                    f"Panel #{idx} ({panel.get('title', '?')}) has no targets",
                )


class TestDashboardDatasourceBinding(unittest.TestCase):
    """6. 每个 target 都用 ${DS_PROMETHEUS} 模板变量。"""

    def test_all_targets_reference_template_datasource(self) -> None:
        data = _load_dashboard()
        panels = data.get("panels") or []
        for p_idx, panel in enumerate(panels):
            for t_idx, target in enumerate(panel.get("targets") or []):
                with self.subTest(
                    panel=panel.get("title", ""),
                    panel_index=p_idx,
                    target_index=t_idx,
                ):
                    ds = target.get("datasource") or {}
                    self.assertIsInstance(
                        ds,
                        dict,
                        "target.datasource must be a dict",
                    )
                    self.assertEqual(
                        ds.get("type"),
                        "prometheus",
                    )
                    self.assertEqual(
                        ds.get("uid"),
                        "${DS_PROMETHEUS}",
                        (
                            "Hardcoded datasource UID detected. Use "
                            "${DS_PROMETHEUS} template variable so users "
                            "can pick their own Prometheus on import."
                        ),
                    )


class TestMetricNameParityWithSystemPy(unittest.TestCase):
    """7. 核心 invariant — dashboard 引用的所有 `aiia_*` metric 名都必须出现在
    system.py 中 (substring 检查，f-string 拼接的 per-provider metric 也覆盖)。"""

    def test_every_referenced_metric_exists_in_system_py(self) -> None:
        data = _load_dashboard()
        panels = data.get("panels") or []
        exprs = _collect_panel_target_exprs(panels)
        self.assertTrue(
            exprs,
            "Dashboard has no panel target expressions to validate",
        )

        all_referenced_metrics: set[str] = set()
        per_expr_metrics: dict[str, set[str]] = {}
        for panel_title, expr in exprs:
            metrics = _extract_aiia_metric_names(expr)
            self.assertTrue(
                metrics,
                (
                    f"Panel '{panel_title}' target expr did not yield any "
                    f"'aiia_*' metric name: {expr!r}"
                ),
            )
            all_referenced_metrics.update(metrics)
            per_expr_metrics[f"{panel_title} | {expr}"] = metrics

        system_source = SYSTEM_PY_PATH.read_text(encoding="utf-8")
        missing: dict[str, list[str]] = {}
        for label, metrics in per_expr_metrics.items():
            absent = sorted(m for m in metrics if m not in system_source)
            if absent:
                missing[label] = absent

        if missing:
            details = "\n".join(
                f"  - {label}: {names}" for label, names in sorted(missing.items())
            )
            self.fail(
                "Grafana dashboard references metric names that do not appear "
                "in src/ai_intervention_agent/web_ui_routes/system.py — either "
                "the metric was renamed in /metrics impl, or the dashboard "
                "expr has a typo. Mismatches:\n" + details
            )

    def test_at_least_seven_distinct_metrics_covered(self) -> None:
        """Cycle 11 R220 contract: dashboard panels collectively reference
        at least 7 distinct `aiia_*` metric series so that the dashboard
        stays a meaningful "overview" rather than degrading to a one-trick
        billboard."""
        data = _load_dashboard()
        panels = data.get("panels") or []
        exprs = _collect_panel_target_exprs(panels)
        all_metrics: set[str] = set()
        for _, expr in exprs:
            all_metrics.update(_extract_aiia_metric_names(expr))
        self.assertGreaterEqual(
            len(all_metrics),
            7,
            (
                f"Dashboard covers only {len(all_metrics)} distinct aiia_* "
                f"metrics: {sorted(all_metrics)}; expected ≥ 7 to remain "
                "a substantive overview."
            ),
        )


class TestObservabilityReadmes(unittest.TestCase):
    """8. 双语 README 存在并提到 dashboard 文件名 + uid。"""

    def test_readme_en_exists_and_references_dashboard(self) -> None:
        self.assertTrue(
            README_EN_PATH.is_file(),
            f"English README missing: {README_EN_PATH}",
        )
        text = README_EN_PATH.read_text(encoding="utf-8")
        self.assertIn(
            "grafana-dashboard.json",
            text,
            "EN README must mention the dashboard filename for import steps",
        )
        self.assertIn(
            "aiia-overview-r220",
            text,
            "EN README must reference the dashboard uid",
        )

    def test_readme_zh_exists_and_references_dashboard(self) -> None:
        self.assertTrue(
            README_ZH_PATH.is_file(),
            f"Chinese README missing: {README_ZH_PATH}",
        )
        text = README_ZH_PATH.read_text(encoding="utf-8")
        self.assertIn(
            "grafana-dashboard.json",
            text,
            "zh-CN README must mention the dashboard filename for import steps",
        )
        self.assertIn(
            "aiia-overview-r220",
            text,
            "zh-CN README must reference the dashboard uid",
        )


if __name__ == "__main__":
    unittest.main()
