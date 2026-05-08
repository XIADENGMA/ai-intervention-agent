"""P7·L1·step-6：``templates/web_ui.html`` 不得带硬编码 CJK 文本节点 /
属性值；所有用户可见的 label / tooltip / placeholder / alt / aria-label
必须走 ``data-i18n*`` 属性，让客户端 ``translateDOM()`` 按 locale 替换。

对应 ``scripts/check_i18n_html_coverage.py``（pytest 镜像）：dev 本地和
CI gate 都能看到违规。

豁免：同一行尾部追加 ``<!-- aiia:i18n-allow-cjk -->`` 白名单真正不可译
的串（如语言选择器里的 ``简体中文`` endonym）——每条豁免都是回归面，
审慎使用。

R100 加了一组 ``TestHtmlCoveragePathDriftR100`` 锁住 ``main()`` 在
``TEMPLATE_PATH`` 漂移 / 不存在时**必须 fail-loud (exit 2)**，不再
silent skip——R88 在 R66 brand-color guard 上做过同款修复，本测试
照搬同款 pattern 防止类似 silent breakage 在 i18n 这一族复发。
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
SCRIPT_PATH = REPO_ROOT / "scripts" / "check_i18n_html_coverage.py"


def _load_gate_module():
    spec = importlib.util.spec_from_file_location(
        "_aiia_check_i18n_html_coverage", SCRIPT_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class TestHtmlTemplateI18nCoverage(unittest.TestCase):
    def test_web_ui_template_has_no_hardcoded_cjk(self) -> None:
        gate = _load_gate_module()
        template = gate.TEMPLATE_PATH
        self.assertTrue(
            template.is_file(),
            msg=f"Expected template at {template} to exist",
        )
        violations = gate.scan_template(template)
        if violations:
            formatted = "\n".join(
                f"  line {line}: hardcoded CJK in {kind}: {snippet!r}"
                for line, kind, snippet in violations
            )
            self.fail(
                f"Found {len(violations)} hardcoded CJK occurrence(s) in "
                f"{template.relative_to(REPO_ROOT).as_posix()}:\n{formatted}\n"
                f"Replace the text with a data-i18n* attribute (data-i18n, "
                f"data-i18n-html, data-i18n-title, data-i18n-placeholder, "
                f"data-i18n-alt, data-i18n-aria-label, or data-i18n-value) "
                f"and move the copy into static/locales/*.json."
            )


class TestHtmlCoveragePathDriftR100(unittest.TestCase):
    """R100：``main()`` 在 ``TEMPLATE_PATH`` 漂移 / 不存在时必须 fail-loud
    (exit 2)，**不能** silent skip 返回 0。

    R66 的 brand-color guard 在 R76 重布局后曾因 ``DEFAULT_ROOT``
    指向不存在的目录而 silently broken（R88 修复改为 exit 2）。
    ``check_i18n_html_coverage.py`` 之前用同样的 ``return 0`` silent
    skip 模式——任何未来重命名 / 移动 ``templates/web_ui.html`` 都会
    让 CI gate 永远 pass，模板里悄悄回流的硬编码 CJK 不会被察觉。
    本测试族用 monkey-patch 模拟漂移，断言 R100 修复后路径不存在
    会显式 fail。
    """

    def _run_main_with_template(self, template_path: Path) -> tuple[int, str, str]:
        gate = _load_gate_module()
        out_buf, err_buf = io.StringIO(), io.StringIO()
        with redirect_stdout(out_buf), redirect_stderr(err_buf):
            with mock.patch.object(gate, "TEMPLATE_PATH", template_path):
                code = gate.main()
        return code, out_buf.getvalue(), err_buf.getvalue()

    def test_missing_template_returns_exit_2_not_silent_skip(self) -> None:
        """模拟 TEMPLATE_PATH 漂移到不存在的位置，main() 必须 exit 2。"""
        bogus = (
            REPO_ROOT
            / "src"
            / "ai_intervention_agent"
            / "templates"
            / "__r100_drift__.html"
        )
        self.assertFalse(
            bogus.exists(),
            msg="Test fixture path must not exist; pick a different name.",
        )

        code, _stdout, stderr = self._run_main_with_template(bogus)
        self.assertEqual(
            code,
            2,
            msg=(
                f"main() returned exit {code} for a non-existent TEMPLATE_PATH. "
                f"Per R100, this must be 2 (configuration drift), not 0 "
                f"(silent skip). Returning 0 would let CI gate pass while "
                f"the template scanner has zero coverage — same silent-"
                f"broken pattern R88 fixed on the brand-color guard."
            ),
        )

    def test_missing_template_emits_clear_stderr_diagnostic(self) -> None:
        """漂移情况必须 stderr 输出明确的诊断信息，否则等于把 silent
        skip 换成 silent fail——同样不接受。"""
        bogus = (
            REPO_ROOT
            / "src"
            / "ai_intervention_agent"
            / "templates"
            / "__r100_drift_2__.html"
        )
        self.assertFalse(bogus.exists())

        _code, _stdout, stderr = self._run_main_with_template(bogus)
        self.assertIn(
            "ERROR",
            stderr,
            msg="stderr 缺少 ERROR 标签——漂移诊断必须显眼。",
        )
        self.assertIn(
            "configuration drift",
            stderr,
            msg=(
                "stderr 缺少 'configuration drift' 关键词——R100 修复要求"
                "把消息明确指向 layout-drift 诊断方向，让 reviewer 立刻看到"
                "该改 TEMPLATE_PATH 还是恢复模板文件。"
            ),
        )

    def test_existing_template_still_works_normally(self) -> None:
        """sanity: 真正存在的 TEMPLATE_PATH 仍然走正常扫描逻辑（不 exit 2）。
        防止 R100 修改无意中破坏 happy-path."""
        gate = _load_gate_module()
        # 用真 TEMPLATE_PATH 跑一次（不打 patch）
        out_buf, err_buf = io.StringIO(), io.StringIO()
        with redirect_stdout(out_buf), redirect_stderr(err_buf):
            code = gate.main()
        self.assertIn(
            code,
            (0, 1),
            msg=(
                f"main() with the real TEMPLATE_PATH returned {code}; "
                f"expected 0 (clean) or 1 (violations found), not 2 "
                f"(config error). R100 must not regress happy-path."
            ),
        )


if __name__ == "__main__":
    unittest.main()
