"""Tests for ``scripts/check_locales.py`` cross-platform aiia.* parity (IG-8).

运行：``uv run pytest tests/test_check_locales.py -v``
"""

from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CHECK_LOCALES_PATH = REPO_ROOT / "scripts" / "check_locales.py"


def _load_check_locales():
    """动态加载 ``scripts/check_locales.py`` 作为模块。"""
    spec = importlib.util.spec_from_file_location("check_locales", CHECK_LOCALES_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_locales"] = module
    spec.loader.exec_module(module)
    return module


class TestCrossPlatformAiiaParity(unittest.TestCase):
    """验证 ``check_cross_platform_aiia_parity`` 的边界行为。"""

    @classmethod
    def setUpClass(cls):
        cls.mod = _load_check_locales()

    def _make_pair(self, tmp_dir: Path, web: dict, vscode: dict) -> tuple[Path, Path]:
        web_dir = tmp_dir / "web"
        vscode_dir = tmp_dir / "vscode"
        web_dir.mkdir(parents=True, exist_ok=True)
        vscode_dir.mkdir(parents=True, exist_ok=True)
        for locale in ("en.json", "zh-CN.json"):
            (web_dir / locale).write_text(
                json.dumps(web, ensure_ascii=False), encoding="utf-8"
            )
            (vscode_dir / locale).write_text(
                json.dumps(vscode, ensure_ascii=False), encoding="utf-8"
            )
        return web_dir, vscode_dir

    def test_passes_when_no_aiia_namespace_either_side(self):
        """两端都没有 ``aiia.*`` 时，检查默认通过。"""
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            web = {"page": {"title": "Hi"}}
            vscode = {"ui": {"button": "OK"}}
            web_dir, vscode_dir = self._make_pair(tmp, web, vscode)
            errors = self.mod.check_cross_platform_aiia_parity(web_dir, vscode_dir)
            self.assertEqual(errors, [])

    def test_passes_when_aiia_matches_exactly(self):
        """两端 ``aiia.*`` 路径完全一致时通过。"""
        import tempfile

        shared = {
            "aiia": {
                "state": {
                    "loading": {"title": "Loading"},
                    "error": {"title": "Error"},
                }
            }
        }
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            web_dir, vscode_dir = self._make_pair(tmp, shared, shared)
            errors = self.mod.check_cross_platform_aiia_parity(web_dir, vscode_dir)
            self.assertEqual(errors, [])

    def test_fails_when_web_has_extra_aiia_key(self):
        """Web UI 多一个 ``aiia.*`` key，检查必须失败。"""
        import tempfile

        web = {
            "aiia": {
                "state": {
                    "loading": {"title": "Loading"},
                    "error": {"title": "Error"},
                }
            }
        }
        vscode = {"aiia": {"state": {"loading": {"title": "Loading"}}}}
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            web_dir, vscode_dir = self._make_pair(tmp, web, vscode)
            errors = self.mod.check_cross_platform_aiia_parity(web_dir, vscode_dir)
            self.assertTrue(errors)
            joined = "\n".join(errors)
            self.assertIn("aiia.state.error.title", joined)
            self.assertIn("VSCode 缺少 aiia.* key", joined)

    def test_fails_when_vscode_has_extra_aiia_key(self):
        """VSCode 多一个 ``aiia.*`` key，检查必须失败。"""
        import tempfile

        web = {"aiia": {"state": {"loading": {"title": "Loading"}}}}
        vscode = {
            "aiia": {
                "state": {
                    "loading": {"title": "Loading"},
                    "empty": {"title": "Empty"},
                }
            }
        }
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            web_dir, vscode_dir = self._make_pair(tmp, web, vscode)
            errors = self.mod.check_cross_platform_aiia_parity(web_dir, vscode_dir)
            self.assertTrue(errors)
            joined = "\n".join(errors)
            self.assertIn("aiia.state.empty.title", joined)
            self.assertIn("Web UI 缺少 aiia.* key", joined)

    def test_non_aiia_namespaces_are_ignored(self):
        """``page.*``/``ui.*`` 等两端独立的 namespace 不应触发跨端错误。"""
        import tempfile

        web = {
            "page": {"title": "Hi", "footer": "Bye"},
            "aiia": {"state": {"loading": {"title": "Loading"}}},
        }
        vscode = {
            "ui": {"command": "OK"},
            "aiia": {"state": {"loading": {"title": "Loading"}}},
        }
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            web_dir, vscode_dir = self._make_pair(tmp, web, vscode)
            errors = self.mod.check_cross_platform_aiia_parity(web_dir, vscode_dir)
            self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
