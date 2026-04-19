"""P7·L1·step-12：Web UI JS 源码不得带硬编码 CJK 字面量。用户可见串必
须落在 ``static/locales/*.json`` 并通过 ``t('...')`` 渲染，否则 UI 文案
被绑死在单一语言，未来 locale 无从扩展。

CLI gate（``scripts/check_i18n_js_no_cjk.py``）+ pytest 双轨刻意冗余：
  * CLI gate 跑在 CI + pre-commit，挡住提交到分支的回归；
  * pytest 在本地 ``pytest`` 时响，比等 CI 红 X 更早给到行号。

当前范围：仅 Web UI（``static/js/*``）。VSCode webview（``packages/vscode/*``）
有 ~66 条 i18n 化之前的 legacy CJK 字面量，P8 里统一迁移；届时把 scope
开到 ``"all"`` 并删掉本注解。

豁免（与 CLI gate 共享）：同行尾部 ``// aiia:i18n-allow-cjk`` 标记刻意
硬编码（例如 AI prompt 默认值要求保留中文）。慎用。
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "check_i18n_js_no_cjk.py"


def _load_gate_module():
    """按模块加载 ``scripts/check_i18n_js_no_cjk.py``（scripts/ 默认不在 sys.path）。"""
    spec = importlib.util.spec_from_file_location(
        "_aiia_check_i18n_js_no_cjk", SCRIPT_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class TestWebUiJsHasNoHardcodedCjk(unittest.TestCase):
    """``static/js/`` 下任何文件都不得含 CJK 字符串字面量。"""

    def test_webui_js_is_cjk_free(self) -> None:
        gate = _load_gate_module()
        violations = gate.collect_violations("webui")
        if violations:
            formatted = "\n".join(
                f"  {path.relative_to(REPO_ROOT).as_posix()}:{line}: {literal!r}"
                for path, line, literal in violations
            )
            self.fail(
                f"Found {len(violations)} hardcoded CJK string literal(s) "
                f"in Web UI JS sources:\n{formatted}\n"
                f"Move user-visible text to static/locales/*.json and "
                f"render via t('...'), or tag the line with "
                f"'// aiia:i18n-allow-cjk' if the literal is deliberately "
                f"hardcoded (e.g. AI prompt defaults)."
            )


if __name__ == "__main__":
    unittest.main()
