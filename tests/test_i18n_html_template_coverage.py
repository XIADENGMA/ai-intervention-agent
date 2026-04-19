"""P7·L1·step-6：``templates/web_ui.html`` 不得带硬编码 CJK 文本节点 /
属性值；所有用户可见的 label / tooltip / placeholder / alt / aria-label
必须走 ``data-i18n*`` 属性，让客户端 ``translateDOM()`` 按 locale 替换。

对应 ``scripts/check_i18n_html_coverage.py``（pytest 镜像）：dev 本地和
CI gate 都能看到违规。

豁免：同一行尾部追加 ``<!-- aiia:i18n-allow-cjk -->`` 白名单真正不可译
的串（如语言选择器里的 ``简体中文`` endonym）——每条豁免都是回归面，
审慎使用。
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
