"""R224 / Cycle 12 · F-cycle11-3: per-provider notification dashboard invariant.

Sibling of `tests/test_grafana_dashboard_invariant_r220.py`. R220 ships
the **overview** Grafana dashboard with 7 high-signal panels covering
SSE health, token age, and aggregate notification health. R224 adds a
**drill-down** dashboard focused entirely on per-provider notification
metrics (R142 / R145 / R191) — useful when the overview's aggregate
`delivery_success_rate` panel turns red and ops needs to identify
*which* provider is at fault.

This test enforces the same silent-decay shield contracts as R220:

1. JSON parses successfully.
2. `schemaVersion` is within the Grafana 10–11 supported range.
3. UID is the stable `aiia-notification-providers-r224` (referenced
   in `docs/observability/README{,.zh-CN}.md`).
4. Title mentions both "AI Intervention Agent" and "Notification" so
   Grafana's search bar can find it alongside the overview.
5. Panel count is locked at 6.
6. Each panel has a non-empty + globally-unique title.
7. Each panel has ≥ 1 target, each target uses the `${DS_PROMETHEUS}`
   template variable (no hardcoded datasource UID).
8. **Core invariant** (same as R220): every `aiia_*` metric name
   referenced by any panel target expr must substring-appear in
   `src/ai_intervention_agent/web_ui_routes/system.py`. This is the
   `/metrics` ↔ dashboard parity contract.
9. Each panel target expr breaks down by `provider` (either via
   `sum by (provider)` aggregation or by carrying a `{{provider}}`
   legend, since R142 / R145 metrics already carry the label
   natively). Without this, the dashboard degrades silently into a
   duplicate of R220's overview.
10. README cross-references the dashboard file by name in both
    EN and zh-CN.

Implemented 2026-05-14, 14 cases / ~24 subtests.
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DASHBOARD_PATH = (
    REPO_ROOT
    / "docs"
    / "observability"
    / "grafana-dashboard-notification-providers.json"
)
README_EN_PATH = REPO_ROOT / "docs" / "observability" / "README.md"
README_ZH_PATH = REPO_ROOT / "docs" / "observability" / "README.zh-CN.md"
SYSTEM_PY_PATH = (
    REPO_ROOT / "src" / "ai_intervention_agent" / "web_ui_routes" / "system.py"
)


def _load_dashboard() -> dict:
    return json.loads(DASHBOARD_PATH.read_text(encoding="utf-8"))


_AIIA_METRIC_RE = re.compile(r"\baiia_[a-zA-Z0-9_]+\b")


def _extract_aiia_metric_names(text: str) -> set[str]:
    """Strip the histogram `_bucket` / `_sum` / `_count` suffixes so the
    parity check against `system.py` finds the family name actually
    emitted by `_format_prom_histogram_family`."""
    raw = set(_AIIA_METRIC_RE.findall(text))
    out: set[str] = set()
    for m in raw:
        for suffix in ("_bucket", "_sum", "_count"):
            if m.endswith(suffix):
                m = m[: -len(suffix)]
                break
        out.add(m)
    return out


def _collect_panel_target_exprs(panels: list[dict]) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for panel in panels:
        title = str(panel.get("title", ""))
        for target in panel.get("targets") or []:
            expr = target.get("expr")
            if isinstance(expr, str) and expr.strip():
                out.append((title, expr))
    return out


class TestDashboardFileExistsAndParses(unittest.TestCase):
    """1. File exists + valid JSON."""

    def test_dashboard_file_exists(self) -> None:
        self.assertTrue(
            DASHBOARD_PATH.is_file(),
            f"R224 dashboard JSON missing: {DASHBOARD_PATH}",
        )

    def test_dashboard_json_parses(self) -> None:
        try:
            data = _load_dashboard()
        except json.JSONDecodeError as exc:
            self.fail(f"R224 dashboard JSON is not valid: {exc}")
        self.assertIsInstance(data, dict)


class TestDashboardIdentity(unittest.TestCase):
    """2 + 3 + 4. schemaVersion range + stable uid + searchable title."""

    SUPPORTED_SCHEMA_VERSIONS = (38, 39, 40)

    def test_schema_version_in_supported_range(self) -> None:
        data = _load_dashboard()
        self.assertIn(data.get("schemaVersion"), self.SUPPORTED_SCHEMA_VERSIONS)

    def test_uid_stable(self) -> None:
        data = _load_dashboard()
        self.assertEqual(data.get("uid"), "aiia-notification-providers-r224")

    def test_title_mentions_project_and_notification(self) -> None:
        data = _load_dashboard()
        title = str(data.get("title", ""))
        for kw in ("AI Intervention Agent", "Notification"):
            with self.subTest(keyword=kw):
                self.assertIn(kw, title)

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
        )


class TestDashboardPanelLayout(unittest.TestCase):
    """5 + 6 + 7. Panel count + titles + per-panel target sanity."""

    EXPECTED_PANEL_COUNT = 6

    def test_panel_count_locked(self) -> None:
        data = _load_dashboard()
        panels = data.get("panels") or []
        self.assertEqual(
            len(panels),
            self.EXPECTED_PANEL_COUNT,
            (
                f"R224 dashboard panel count drifted: expected "
                f"{self.EXPECTED_PANEL_COUNT}, got {len(panels)}. If "
                "you intentionally added / removed panels, also update "
                "EXPECTED_PANEL_COUNT here."
            ),
        )

    def test_every_panel_has_non_empty_unique_title(self) -> None:
        data = _load_dashboard()
        panels = data.get("panels") or []
        titles: list[str] = []
        for idx, panel in enumerate(panels):
            t = panel.get("title")
            with self.subTest(panel_index=idx):
                self.assertIsInstance(t, str)
                self.assertTrue(t and t.strip())
                titles.append(t)
        self.assertEqual(len(titles), len(set(titles)))

    def test_every_panel_has_at_least_one_target(self) -> None:
        data = _load_dashboard()
        panels = data.get("panels") or []
        for idx, panel in enumerate(panels):
            with self.subTest(panel_index=idx, title=panel.get("title", "")):
                self.assertGreaterEqual(len(panel.get("targets") or []), 1)


class TestDashboardDatasourceBinding(unittest.TestCase):
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
                    self.assertEqual(ds.get("type"), "prometheus")
                    self.assertEqual(ds.get("uid"), "${DS_PROMETHEUS}")


class TestMetricNameParityWithSystemPy(unittest.TestCase):
    """8. Every `aiia_*` metric in target exprs is produced by system.py.

    Two acceptance paths because per-provider notification families are
    emitted via ``f"aiia_notification_{metric_suffix}"`` dynamic
    construction (see system.py ``_per_provider_field_specs`` at the
    R142 section), so the full literal name never appears:

    - **Direct hit**: the full metric name appears verbatim somewhere
      in system.py (covers static metric names like
      ``aiia_notification_send_duration_seconds`` and
      ``aiia_notification_attempts_total`` which has a docstring
      mention plus the f-string assembly site).
    - **Suffix hit**: the metric has the ``aiia_notification_`` prefix
      AND the remaining suffix appears as a quoted string in system.py
      AND ``aiia_notification_`` appears anywhere (the f-string
      assembly anchor). This catches the dynamically-emitted families:
      success_rate / avg_latency_ms / success_streak / failure_streak
      etc. The contract is that any future contributor renaming the
      suffix tuple in ``_per_provider_field_specs`` must also update
      this dashboard.
    """

    def _metric_is_produced_by_system_py(self, metric: str, system_source: str) -> bool:
        if metric in system_source:
            return True
        if metric.startswith("aiia_notification_"):
            suffix = metric[len("aiia_notification_") :]
            quoted_suffix = '"' + suffix + '"'
            if quoted_suffix in system_source and "aiia_notification_" in system_source:
                return True
        return False

    def test_every_referenced_metric_exists_in_system_py(self) -> None:
        data = _load_dashboard()
        panels = data.get("panels") or []
        exprs = _collect_panel_target_exprs(panels)
        self.assertTrue(exprs)

        per_expr_metrics: dict[str, set[str]] = {}
        for panel_title, expr in exprs:
            metrics = _extract_aiia_metric_names(expr)
            self.assertTrue(
                metrics,
                f"Panel {panel_title!r} expr yielded no aiia_* metric: {expr!r}",
            )
            per_expr_metrics[f"{panel_title} | {expr}"] = metrics

        system_source = SYSTEM_PY_PATH.read_text(encoding="utf-8")
        missing: dict[str, list[str]] = {}
        for label, metrics in per_expr_metrics.items():
            absent = sorted(
                m
                for m in metrics
                if not self._metric_is_produced_by_system_py(m, system_source)
            )
            if absent:
                missing[label] = absent
        if missing:
            details = "\n".join(
                f"  - {lab}: {names}" for lab, names in sorted(missing.items())
            )
            self.fail(
                "R224 dashboard references metric names not produced by "
                "src/ai_intervention_agent/web_ui_routes/system.py — "
                "rename drift or typo. Mismatches:\n" + details
            )


class TestPerProviderBreakdown(unittest.TestCase):
    """9. Each panel actually drills down by provider — otherwise we're
    not really a drill-down dashboard but a duplicate of the overview."""

    def test_each_panel_breaks_down_by_provider(self) -> None:
        data = _load_dashboard()
        panels = data.get("panels") or []
        for idx, panel in enumerate(panels):
            with self.subTest(panel_index=idx, title=panel.get("title", "")):
                targets = panel.get("targets") or []
                has_provider_breakdown = False
                for target in targets:
                    expr = target.get("expr", "")
                    legend = target.get("legendFormat", "")
                    if "by (provider" in expr or "{{provider}}" in legend:
                        has_provider_breakdown = True
                        break
                self.assertTrue(
                    has_provider_breakdown,
                    (
                        f"Panel {panel.get('title', '?')} does not appear "
                        "to break down by `provider` — either the expr "
                        "lacks `sum by (provider)` aggregation or the "
                        "legendFormat lacks `{{provider}}` placeholder. "
                        "Without provider breakdown this dashboard "
                        "duplicates R220's aggregate view."
                    ),
                )


class TestReadmeCrossReference(unittest.TestCase):
    """10. Both bilingual READMEs must reference the new dashboard file."""

    def test_en_readme_references_dashboard(self) -> None:
        text = README_EN_PATH.read_text(encoding="utf-8")
        self.assertIn(
            "grafana-dashboard-notification-providers.json",
            text,
            (
                "docs/observability/README.md does not reference "
                "the R224 drill-down dashboard filename. Users will "
                "import the overview but never discover the drill-down."
            ),
        )
        self.assertIn(
            "aiia-notification-providers-r224",
            text,
            (
                "docs/observability/README.md does not reference "
                "the R224 dashboard uid (aiia-notification-providers-r224)."
            ),
        )

    def test_zh_readme_references_dashboard(self) -> None:
        text = README_ZH_PATH.read_text(encoding="utf-8")
        self.assertIn(
            "grafana-dashboard-notification-providers.json",
            text,
            "docs/observability/README.zh-CN.md does not reference the R224 dashboard filename.",
        )
        self.assertIn(
            "aiia-notification-providers-r224",
            text,
            "docs/observability/README.zh-CN.md does not reference the R224 dashboard uid.",
        )


if __name__ == "__main__":
    unittest.main()
