"""L2·G6：VSCode extension host TypeScript 源码不得带硬编码 CJK 字面量。

对应 ``scripts/check_i18n_ts_no_cjk.py`` 的 pytest 镜像；extension host
（``packages/vscode/*.ts``）跑在 Node 侧，用户可见串必须走
``vscode.l10n.t(...)`` → ``l10n/bundle.l10n.*.json`` 链路。任何 inline CJK
要么绕过翻译（zh-CN 串进 en IDE 反之），要么漏进状态栏 / 错误 toast /
诊断日志。

Webview JS 侧由 ``tests/test_i18n_js_no_hardcoded_cjk.py`` 覆盖，合起来
锁住所有面向终端用户的 runtime。

豁免：行尾 ``// aiia:i18n-allow-cjk``。慎用——受影响的用户往往读不懂
英文测试输出，回归很难在 issue tracker 露头。
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "check_i18n_ts_no_cjk.py"


def _load_gate_module():
    """按模块加载 ``scripts/check_i18n_ts_no_cjk.py``（scripts/ 默认不在 sys.path）。"""
    spec = importlib.util.spec_from_file_location(
        "_aiia_check_i18n_ts_no_cjk", SCRIPT_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class TestVscodeExtensionHostTsHasNoHardcodedCjk(unittest.TestCase):
    """No file under ``packages/vscode/*.ts`` may contain a CJK string
    literal outside ``// aiia:i18n-allow-cjk``-tagged lines."""

    def test_extension_host_ts_is_cjk_free(self) -> None:
        gate = _load_gate_module()
        violations = gate.collect_violations()
        if violations:
            formatted = "\n".join(
                f"  {path.relative_to(REPO_ROOT).as_posix()}:{line}: {literal!r}"
                for path, line, literal in violations
            )
            self.fail(
                f"Found {len(violations)} hardcoded CJK string literal(s) "
                f"in packages/vscode/*.ts sources:\n{formatted}\n"
                f"Wrap user-visible text in vscode.l10n.t(...) and add "
                f"the English source string to packages/vscode/l10n/"
                f"bundle.l10n.json (plus matching locale bundles), or tag "
                f"the line with '// aiia:i18n-allow-cjk' if the literal "
                f"is deliberately hardcoded."
            )


if __name__ == "__main__":
    unittest.main()
