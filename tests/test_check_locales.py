"""Tests for ``scripts/check_locales.py``:

- IG-8: cross-platform ``aiia.*`` namespace parity.
- R102: layer-0 path-drift sanity check in ``main()`` —— 4 个核心 locale
  资源缺失时必须 fail-loud (exit 2)，与 R88/R100/R101 同款修复对齐，
  不能再 silent skip 返回 0。

运行：``uv run pytest tests/test_check_locales.py -v``
"""

from __future__ import annotations

import importlib.util
import io
import json
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

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


class TestMainPathDriftR102(unittest.TestCase):
    """R102：``main()`` 必须在核心 locale 资源缺失时 fail-loud (exit 2)。

    历史 silent breakage：``check_locales.py`` 之前用嵌套 ``if X.exists():``
    守护每个分支：``locale_dirs`` / ``vscode_dir`` / cross-platform 任一漂移
    时对应分支 silent 0 coverage，``check_nls_pair`` 内部 ``if not en or
    not zh: return []`` 也是 silent skip。R76 重布局把 ``static/`` 挪进
    ``src/`` 包内时让 R66 brand-color guard silently broken（R88 修），R100
    /R101 把同款修复 port 到 HTML coverage 和 ts/js no-cjk 扫描器，R102
    收尾把它从最后一个 i18n 一致性扫描器里也清出去。
    """

    @classmethod
    def setUpClass(cls):
        cls.mod = _load_check_locales()

    def _capture_main(self) -> tuple[int, str, str]:
        out_buf, err_buf = io.StringIO(), io.StringIO()
        with redirect_stdout(out_buf), redirect_stderr(err_buf):
            code = self.mod.main()
        return code, out_buf.getvalue(), err_buf.getvalue()

    def _patched_path(self, missing_subpath: str):
        """构造一个 ``Path.exists()`` mock：让 missing_subpath 这条返回
        False，其他真实路径仍走真 ``exists()``。"""
        original_exists = Path.exists

        def fake_exists(path_self):
            if str(path_self).endswith(missing_subpath):
                return False
            return original_exists(path_self)

        return mock.patch.object(Path, "exists", fake_exists)

    def test_missing_web_en_locale_returns_exit_2(self) -> None:
        """``static/locales/en.json`` 缺失 → exit 2。"""
        with self._patched_path("static/locales/en.json"):
            code, _stdout, stderr = self._capture_main()
        self.assertEqual(code, 2, msg=f"exit {code}, expected 2")
        self.assertIn("ERROR", stderr)
        self.assertIn("Web UI 源 locale", stderr)
        self.assertIn("configuration drift", stderr)

    def test_missing_vscode_nls_returns_exit_2(self) -> None:
        """``packages/vscode/package.nls.json`` 缺失 → exit 2.

        R102 之前因为 ``check_nls_pair`` 内部 ``if not en.exists() or not
        zh.exists(): return []`` silent skip 导致 NLS 漂移完全无声。"""
        with self._patched_path("package.nls.json"):
            code, _stdout, stderr = self._capture_main()
        self.assertEqual(code, 2)
        self.assertIn("VS Code package.nls 源", stderr)

    def test_missing_vscode_locales_dir_returns_exit_2(self) -> None:
        """``packages/vscode/locales/zh-CN.json`` 缺失 → exit 2。"""
        with self._patched_path("packages/vscode/locales/zh-CN.json"):
            code, _stdout, stderr = self._capture_main()
        self.assertEqual(code, 2)
        self.assertIn("VS Code zh-CN locale", stderr)

    def test_existing_paths_run_normal_consistency_check(self) -> None:
        """sanity: 全部核心路径存在时仍走正常的 1-vs-2 一致性检查路径，
        不会因 R102 改动而 break happy-path."""
        code, _stdout, _stderr = self._capture_main()
        self.assertIn(
            code,
            (0, 1),
            msg=f"main() with real paths returned {code}; expected 0 or 1.",
        )

    def test_stderr_diagnostic_format_is_actionable(self) -> None:
        """漂移诊断必须包含：ERROR 标签 + 资源 label + relative path
        + absolute path + 修复指引（指向脚本顶部 path 常量）。让 reviewer
        立刻看到该改哪里。"""
        with self._patched_path("static/locales/en.json"):
            _code, _stdout, stderr = self._capture_main()
        # 必须命名缺失资源
        self.assertIn("Web UI 源 locale", stderr)
        # 必须给绝对路径（让 reviewer 不需要二次解析）
        self.assertIn("Resolved absolute path", stderr)
        # 必须告诉 reviewer 该去哪里改路径
        self.assertIn("scripts/check_locales.py", stderr)


if __name__ == "__main__":
    unittest.main()
