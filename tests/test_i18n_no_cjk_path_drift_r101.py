"""R101 回归：``check_i18n_{ts,js}_no_cjk.py`` 在 scan root 漂移 / 不
存在时必须 fail-loud (exit 2)，不能 silent skip 返回 0。

历史 silent breakage（与 R88 / R100 同源）
-----------------------------------------
R76 重布局把 ``static/`` 从仓库根挪进 ``src/ai_intervention_agent/`` 包
内，导致 R66 brand-color guard 的 ``DEFAULT_ROOT = "static/css"`` 解析
后指向不存在的目录、scanner 变成 silent no-op；R88 修复时把 missing
root 路径从 ``return 0`` 改为 ``return 2 + diagnostic``。R100 在 HTML
template coverage 扫描器上做了同款修复。

R101 把同款 anti-pattern 从两个 i18n CJK 字面量扫描器里清出去：

- ``check_i18n_ts_no_cjk.py``：``_iter_ts_source_files`` 之前在
  ``_VSCODE_ROOT`` 不存在时 ``return []``，``main()`` 看到 0
  violations 然后 print "OK" + exit 0；
- ``check_i18n_js_no_cjk.py``：``_iter_js_source_files`` 之前在 root
  不存在时 ``continue``，``--scope vscode`` 且 ``packages/vscode``
  路径漂移时整条 scope 静默 0 文件、main() 仍 print "OK"。

两个 scanner 的 ``main()`` 现在都做 layer-0 path-drift sanity，
检测到核心 scan root 不存在 → ``return 2 + stderr 诊断``。本测试
族用 monkey-patch 模拟漂移，逐 scenario 验证 R101 修复有效。
"""

from __future__ import annotations

import importlib.util
import io
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
TS_SCRIPT = REPO_ROOT / "scripts" / "check_i18n_ts_no_cjk.py"
JS_SCRIPT = REPO_ROOT / "scripts" / "check_i18n_js_no_cjk.py"


def _load_module(label: str, path: Path):
    spec = importlib.util.spec_from_file_location(f"_aiia_r101_{label}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _capture_main(module, *argv: str) -> tuple[int, str, str]:
    out_buf, err_buf = io.StringIO(), io.StringIO()
    with redirect_stdout(out_buf), redirect_stderr(err_buf):
        code = module.main(list(argv))
    return code, out_buf.getvalue(), err_buf.getvalue()


class TestTsNoCjkPathDriftR101(unittest.TestCase):
    """``check_i18n_ts_no_cjk.py`` 的 ``_VSCODE_ROOT`` 不存在场景。"""

    def test_missing_vscode_root_returns_exit_2(self) -> None:
        gate = _load_module("ts_a", TS_SCRIPT)
        bogus = REPO_ROOT / "packages" / "__r101_drift__vscode__"
        self.assertFalse(bogus.exists())

        with mock.patch.object(gate, "_VSCODE_ROOT", bogus):
            code, _stdout, stderr = _capture_main(gate)

        self.assertEqual(
            code,
            2,
            msg=(
                f"main() returned exit {code} for non-existent _VSCODE_ROOT. "
                f"Per R101 must be 2 (configuration drift), not 0 (silent skip)."
            ),
        )
        self.assertIn("ERROR", stderr)
        self.assertIn("configuration drift", stderr)

    def test_existing_vscode_root_still_works_normally(self) -> None:
        """sanity: 真 ``_VSCODE_ROOT`` 仍走正常扫描，不会因为 R101 改动
        而破坏 happy-path."""
        gate = _load_module("ts_b", TS_SCRIPT)
        code, _stdout, _stderr = _capture_main(gate)
        self.assertIn(
            code,
            (0, 1),
            msg=(
                f"main() with real _VSCODE_ROOT returned {code}; expected 0 "
                f"(clean) or 1 (violations), not 2. R101 must not regress "
                f"happy-path."
            ),
        )


class TestJsNoCjkPathDriftR101(unittest.TestCase):
    """``check_i18n_js_no_cjk.py`` 的 scope 对应 root 不存在场景。"""

    def test_missing_webui_root_returns_exit_2(self) -> None:
        """``--scope webui`` 但 ``static/js`` 漂移到不存在的位置。"""
        gate = _load_module("js_a", JS_SCRIPT)
        bogus_webui = REPO_ROOT / "src" / "__r101_drift__static_js__"
        self.assertFalse(bogus_webui.exists())

        original_scopes = gate.SCOPES.copy()
        patched_scopes = original_scopes.copy()
        patched_scopes["webui"] = (bogus_webui,)
        with mock.patch.object(gate, "SCOPES", patched_scopes):
            code, _stdout, stderr = _capture_main(gate, "--scope", "webui")

        self.assertEqual(code, 2, msg=f"exit code {code}, expected 2")
        self.assertIn("ERROR", stderr)
        self.assertIn("configuration drift", stderr)

    def test_missing_vscode_root_returns_exit_2(self) -> None:
        """``--scope vscode`` 但 ``packages/vscode`` 漂移。"""
        gate = _load_module("js_b", JS_SCRIPT)
        bogus_vscode = REPO_ROOT / "packages" / "__r101_drift__pkgs_vscode__"
        self.assertFalse(bogus_vscode.exists())

        patched_scopes = gate.SCOPES.copy()
        patched_scopes["vscode"] = (bogus_vscode,)
        with mock.patch.object(gate, "SCOPES", patched_scopes):
            code, _stdout, stderr = _capture_main(gate, "--scope", "vscode")

        self.assertEqual(code, 2)
        self.assertIn("ERROR", stderr)
        self.assertIn("configuration drift", stderr)

    def test_partial_drift_in_all_scope_returns_exit_2(self) -> None:
        """``--scope all`` 时一个 root 漂移、另一个还在——partial drift 同样
        必须 fail-loud（不允许"还有数据可扫所以 OK"的妥协）。"""
        gate = _load_module("js_c", JS_SCRIPT)
        bogus = REPO_ROOT / "packages" / "__r101_drift__partial__"
        self.assertFalse(bogus.exists())

        # 真 webui root 保留，vscode root 替换成不存在的
        original_webui = gate.SCOPES["webui"][0]
        patched_scopes = gate.SCOPES.copy()
        patched_scopes["all"] = (original_webui, bogus)
        with mock.patch.object(gate, "SCOPES", patched_scopes):
            code, _stdout, stderr = _capture_main(gate, "--scope", "all")

        self.assertEqual(
            code,
            2,
            msg=(
                f"--scope all with one drifted root returned {code}; expected "
                f"2. Partial drift is also silent breakage — extension half "
                f"silently uncovered while web half passes."
            ),
        )
        self.assertIn("ERROR", stderr)

    def test_all_scopes_existing_still_work_normally(self) -> None:
        """sanity: 三种 scope 在真 root 下都能正常扫描。"""
        gate = _load_module("js_d", JS_SCRIPT)
        for scope in ("webui", "vscode", "all"):
            with self.subTest(scope=scope):
                code, _stdout, _stderr = _capture_main(gate, "--scope", scope)
                self.assertIn(
                    code,
                    (0, 1),
                    msg=f"scope={scope}: exit {code}, expected 0 or 1",
                )


if __name__ == "__main__":
    unittest.main()
