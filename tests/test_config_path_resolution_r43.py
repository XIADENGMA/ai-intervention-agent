"""TODO #2 / r43 — 配置路径检测端到端契约测试。

历史问题：``_is_uvx_mode`` 只识别 ``"uvx" in sys.executable``，对 2026 年常见
的 4 类隔离运行时（``uvx`` / ``uv tool install`` / ``pipx install`` / ``pip install
+ site-packages``）有大量漏判 ——

* ``uv tool install ai-intervention-agent`` 的 sys.executable 在
  ``~/.local/share/uv/tools/<name>/.venv/bin/python``，旧检测不命中。
* ``pipx install ai-intervention-agent`` 的 sys.executable 在
  ``~/.local/share/pipx/venvs/<name>/bin/python``，旧检测完全不识别 pipx。
* 新版 ``uvx`` 是 ``uv tool run``，cache 在 ``~/.cache/uv/builds-v0/<hash>/``，
  路径不含 ``uvx`` 字面量。

而漏判会让 ``find_config_file`` 错走"开发模式"，把 ``config.toml`` 创建在用户的
任意 cwd 里——典型用户体验：他在 ``~/projects/foo/`` 目录运行
``uvx ai-intervention-agent``，发现自己的项目突然多出来一个 ``config.toml``。

r43 在 ``config_manager.py`` 里：

* 新增 :func:`_path_contains_segment` / :func:`_path_under` /
  :func:`_looks_like_repo_checkout` / :func:`_is_isolated_install_runtime`
  公共/私有 helper，覆盖 4 类隔离运行时 + 用户自定义 ``UV_TOOL_DIR`` /
  ``PIPX_HOME`` / ``UV_CACHE_DIR`` 等 env-driven 路径前缀。
* 新增 ``AI_INTERVENTION_AGENT_DEV_MODE`` / ``AI_INTERVENTION_AGENT_USER_MODE``
  两个显式 env override，优先级最高，方便长期 host 服务（systemd /
  Docker entrypoint）锁定模式。
* 在 ``find_config_file`` 中给 "目录里同时存在 TOML/JSONC/JSON" 加 warn 日志，
  避免用户的 ``config.jsonc`` 被悄悄忽略。

本文件 22 个测试覆盖：

* ``_is_isolated_install_runtime``：4 类隔离运行时各 ≥ 1 case + env 前缀
  override + Windows 路径分隔符。
* ``_is_uvx_mode``：6 级优先级链（DEV_MODE → USER_MODE → UVX_PROJECT →
  isolated runtime → repo + cwd → 默认）。
* ``find_config_file``：env override / 多格式 warn / 用户配置目录回退。
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ai_intervention_agent.config_manager import (
    _is_isolated_install_runtime,
    _is_uvx_mode,
    _looks_like_repo_checkout,
    _path_contains_segment,
    _path_under,
    find_config_file,
)

# ---------------------------------------------------------------------------
# Section 1 — 内部 helper 工具函数
# ---------------------------------------------------------------------------


class TestPathContainsSegment(unittest.TestCase):
    def test_full_segment_matches(self) -> None:
        self.assertTrue(_path_contains_segment("/a/uv/b", "uv"))
        self.assertTrue(_path_contains_segment("/a/.uv/b", "uv"))

    def test_does_not_match_substring(self) -> None:
        # ``/a/uv-foo/`` 不应把 segment="uv" 视为命中——避免 ``uvloop`` /
        # ``uv-bar`` 之类的目录被误判为 uv tool 安装。
        self.assertTrue(
            _path_contains_segment("/a/uv-foo/b", "uv"),
            "前缀形式 ``uv-`` 仍应当命中（CLI tool naming）",
        )
        self.assertFalse(_path_contains_segment("/a/buv/b", "uv"))

    def test_handles_windows_separators(self) -> None:
        self.assertTrue(
            _path_contains_segment(r"C:\Users\foo\.local\share\uv\tools", "uv")
        )

    def test_invalid_inputs(self) -> None:
        # Path 对象、空串、不可 str 化对象都要 graceful。
        self.assertFalse(_path_contains_segment("", "uv"))
        self.assertFalse(_path_contains_segment(Path("/no/uvtools"), "uv"))


class TestLooksLikeRepoCheckout(unittest.TestCase):
    """R76 src/ layout 改造之后的语义：

    ``_looks_like_repo_checkout(module_dir)`` 现在要求：
    1. ``module_dir`` 自身有 ``server.py``——即 ``src/ai_intervention_agent/``；
    2. ``module_dir.parent.parent`` 有 ``pyproject.toml``——即 src layout 的仓库根。

    旧契约（``module_dir`` 是 REPO_ROOT 且包含 ``pyproject.toml`` + ``server.py``）
    在 R76 之后已不再适用：``server.py`` 移入了包内，``pyproject.toml`` 留在根。
    """

    def test_true_for_pkg_dir_in_src_layout(self) -> None:
        # src/ai_intervention_agent/ 是新布局下的"模块目录"
        pkg_dir = REPO_ROOT / "src" / "ai_intervention_agent"
        self.assertTrue(_looks_like_repo_checkout(pkg_dir))

    def test_false_for_repo_root_after_r76(self) -> None:
        # R76 之后 REPO_ROOT 不再有 server.py，所以应当返回 False
        self.assertFalse(_looks_like_repo_checkout(REPO_ROOT))

    def test_false_for_random_directory(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            self.assertFalse(_looks_like_repo_checkout(Path(td)))

    def test_false_when_only_pkg_marker_present(self) -> None:
        # 仅 server.py、缺 ../../pyproject.toml → 不是仓库
        with tempfile.TemporaryDirectory() as td:
            pkg_dir = Path(td) / "src" / "fake_pkg"
            pkg_dir.mkdir(parents=True)
            (pkg_dir / "server.py").write_text("")
            # 父父目录（td）无 pyproject.toml
            self.assertFalse(_looks_like_repo_checkout(pkg_dir))

    def test_true_when_both_layered_markers_present(self) -> None:
        # 模拟 src layout：<repo>/pyproject.toml + <repo>/src/<pkg>/server.py
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            (repo / "pyproject.toml").write_text("")
            pkg_dir = repo / "src" / "fake_pkg"
            pkg_dir.mkdir(parents=True)
            (pkg_dir / "server.py").write_text("")
            self.assertTrue(_looks_like_repo_checkout(pkg_dir))


class TestPathUnder(unittest.TestCase):
    def test_child_under_parent(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            parent = Path(td)
            child = parent / "sub" / "file"
            child.parent.mkdir(parents=True)
            child.write_text("")
            self.assertTrue(_path_under(child, (parent,)))

    def test_unrelated_returns_false(self) -> None:
        with (
            tempfile.TemporaryDirectory() as td_parent,
            tempfile.TemporaryDirectory() as td_other,
        ):
            self.assertFalse(_path_under(Path(td_other), (Path(td_parent),)))

    def test_self_equals_parent(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            self.assertTrue(_path_under(p, (p,)))


# ---------------------------------------------------------------------------
# Section 2 — _is_isolated_install_runtime 4 类隔离运行时
# ---------------------------------------------------------------------------


class TestIsIsolatedInstallRuntimeUVTools(unittest.TestCase):
    """``uv tool install`` 装好的工具，sys.executable 在 ``~/.local/share/uv/tools/<name>/.venv/bin/python``。"""

    def test_unix_uv_tools_path(self) -> None:
        with patch(
            "ai_intervention_agent.config_manager.sys.executable",
            "/Users/foo/.local/share/uv/tools/ai-intervention-agent/.venv/bin/python",
        ):
            self.assertTrue(_is_isolated_install_runtime())

    def test_windows_uv_tools_path(self) -> None:
        with patch(
            "ai_intervention_agent.config_manager.sys.executable",
            r"C:\Users\foo\AppData\Roaming\uv\tools\ai-intervention-agent\.venv\Scripts\python.exe",
        ):
            self.assertTrue(_is_isolated_install_runtime())


class TestIsIsolatedInstallRuntimeUvx(unittest.TestCase):
    """``uvx`` (uv tool run) 临时 cache，sys.executable 在 ``~/.cache/uv/builds-v0/<hash>/``。"""

    def test_uvx_cache_path(self) -> None:
        with patch(
            "ai_intervention_agent.config_manager.sys.executable",
            "/Users/foo/.cache/uv/builds-v0/abcd1234/.venv/bin/python",
        ):
            self.assertTrue(_is_isolated_install_runtime())

    def test_legacy_uvx_path(self) -> None:
        # 老版 uv 的 uvx 路径直接含 ``/uvx/`` 字面量。
        with patch(
            "ai_intervention_agent.config_manager.sys.executable",
            "/Users/foo/.local/share/uvx/python3.11/bin/python",
        ):
            self.assertTrue(_is_isolated_install_runtime())


class TestIsIsolatedInstallRuntimePipx(unittest.TestCase):
    """``pipx install`` 装好的工具，sys.executable 在 ``~/.local/share/pipx/venvs/<name>/bin/python``。"""

    def test_pipx_venvs_path(self) -> None:
        with patch(
            "ai_intervention_agent.config_manager.sys.executable",
            "/Users/foo/.local/share/pipx/venvs/ai-intervention-agent/bin/python",
        ):
            self.assertTrue(_is_isolated_install_runtime())


class TestIsIsolatedInstallRuntimeSitePackages(unittest.TestCase):
    """模块本身 import 自 ``site-packages`` —— 已经 ``pip install`` 到 venv 或全局。"""

    def test_module_in_site_packages(self) -> None:
        fake_module_path = "/some/venv/lib/python3.11/site-packages/ai_intervention_agent/config_manager.py"
        with patch("ai_intervention_agent.config_manager.__file__", fake_module_path):
            self.assertTrue(_is_isolated_install_runtime())

    def test_module_in_dist_packages(self) -> None:
        fake_module_path = (
            "/usr/lib/python3/dist-packages/ai_intervention_agent/config_manager.py"
        )
        with patch("ai_intervention_agent.config_manager.__file__", fake_module_path):
            self.assertTrue(_is_isolated_install_runtime())


class TestIsIsolatedInstallRuntimeEnvOverride(unittest.TestCase):
    """``UV_TOOL_DIR`` / ``PIPX_HOME`` / ``UV_CACHE_DIR`` 等 env 前缀匹配。"""

    def test_uv_tool_dir_prefix_match(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tool_dir = Path(td) / "uv-tools"
            tool_bin = tool_dir / "ai-intervention-agent" / ".venv" / "bin" / "python"
            tool_bin.parent.mkdir(parents=True)
            tool_bin.touch()
            with (
                patch(
                    "ai_intervention_agent.config_manager.sys.executable", str(tool_bin)
                ),
                patch.dict(os.environ, {"UV_TOOL_DIR": str(tool_dir)}, clear=False),
            ):
                self.assertTrue(_is_isolated_install_runtime())

    def test_pipx_home_prefix_match(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            pipx_root = Path(td) / "pipx-home"
            pipx_bin = pipx_root / "venvs" / "ai-intervention-agent" / "bin" / "python"
            pipx_bin.parent.mkdir(parents=True)
            pipx_bin.touch()
            with (
                patch(
                    "ai_intervention_agent.config_manager.sys.executable", str(pipx_bin)
                ),
                patch.dict(os.environ, {"PIPX_HOME": str(pipx_root)}, clear=False),
            ):
                self.assertTrue(_is_isolated_install_runtime())


class TestIsIsolatedInstallRuntimeRepoVenv(unittest.TestCase):
    """开发者在仓库内用 ``uv run`` / venv —— 不应被误判为 isolated install。"""

    def test_repo_dot_venv_not_flagged(self) -> None:
        with patch(
            "ai_intervention_agent.config_manager.sys.executable",
            str(REPO_ROOT / ".venv" / "bin" / "python"),
        ):
            # 重要：仓库内 .venv 必须仍判为非 isolated（让上层 ``_is_uvx_mode``
            # 走"仓库 + cwd"分支返回 False）。
            self.assertFalse(_is_isolated_install_runtime())

    def test_uv_managed_python_interpreter_not_flagged(self) -> None:
        # ``~/.local/share/uv/python/cpython-3.11.../bin/python`` 是 uv 给项目
        # 装的 Python 解释器本身，不代表项目已安装。
        with patch(
            "ai_intervention_agent.config_manager.sys.executable",
            "/Users/foo/.local/share/uv/python/cpython-3.11.15-macos-aarch64-none/bin/python3.11",
        ):
            self.assertFalse(_is_isolated_install_runtime())


# ---------------------------------------------------------------------------
# Section 3 — _is_uvx_mode 6 级优先级链
# ---------------------------------------------------------------------------


class TestIsUvxModePriorityChain(unittest.TestCase):
    """优先级链：DEV_MODE → USER_MODE → UVX_PROJECT → isolated → repo+cwd → default."""

    def test_dev_mode_env_overrides_everything(self) -> None:
        # 即使 sys.executable 在 isolated path 里，DEV_MODE=1 也强制开发模式。
        with (
            patch(
                "ai_intervention_agent.config_manager.sys.executable",
                "/Users/foo/.local/share/uv/tools/aiia/.venv/bin/python",
            ),
            patch.dict(
                os.environ,
                {
                    "AI_INTERVENTION_AGENT_DEV_MODE": "1",
                    "AI_INTERVENTION_AGENT_USER_MODE": "1",
                    "UVX_PROJECT": "aiia",
                },
                clear=False,
            ),
        ):
            self.assertFalse(_is_uvx_mode())

    def test_user_mode_env_forces_user_in_repo(self) -> None:
        # USER_MODE=1 即使在仓库内 cwd，也应当返回 True。
        with patch.dict(
            os.environ,
            {"AI_INTERVENTION_AGENT_USER_MODE": "1"},
            clear=False,
        ):
            os.environ.pop("AI_INTERVENTION_AGENT_DEV_MODE", None)
            self.assertTrue(_is_uvx_mode())

    def test_uvx_project_legacy(self) -> None:
        with patch.dict(os.environ, {"UVX_PROJECT": "aiia"}, clear=False):
            for name in (
                "AI_INTERVENTION_AGENT_DEV_MODE",
                "AI_INTERVENTION_AGENT_USER_MODE",
            ):
                os.environ.pop(name, None)
            self.assertTrue(_is_uvx_mode())

    def test_isolated_runtime_triggers_user_mode(self) -> None:
        with (
            patch(
                "ai_intervention_agent.config_manager.sys.executable",
                "/Users/foo/.local/share/pipx/venvs/aiia/bin/python",
            ),
            patch.dict(os.environ, {}, clear=False),
        ):
            for name in (
                "AI_INTERVENTION_AGENT_DEV_MODE",
                "AI_INTERVENTION_AGENT_USER_MODE",
                "UVX_PROJECT",
            ):
                os.environ.pop(name, None)
            self.assertTrue(_is_uvx_mode())

    def test_repo_checkout_with_cwd_inside_returns_dev(self) -> None:
        # 所有 env 都不命中 + 模块在仓库 + cwd 在仓库 → 开发模式。
        with patch.dict(os.environ, {}, clear=False):
            for name in (
                "AI_INTERVENTION_AGENT_DEV_MODE",
                "AI_INTERVENTION_AGENT_USER_MODE",
                "UVX_PROJECT",
            ):
                os.environ.pop(name, None)
            self.assertFalse(_is_uvx_mode())

    def test_default_falls_back_to_user_mode(self) -> None:
        # 模块路径在仓库（真实环境）但 cwd 在外部 → 默认用户模式。
        with tempfile.TemporaryDirectory() as outside_cwd:
            old_cwd = Path.cwd()
            try:
                os.chdir(outside_cwd)
                with patch.dict(os.environ, {}, clear=False):
                    for name in (
                        "AI_INTERVENTION_AGENT_DEV_MODE",
                        "AI_INTERVENTION_AGENT_USER_MODE",
                        "UVX_PROJECT",
                    ):
                        os.environ.pop(name, None)
                    self.assertTrue(_is_uvx_mode())
            finally:
                os.chdir(old_cwd)


class TestIsUvxModeFalsyEnvValuesIgnored(unittest.TestCase):
    """``AI_INTERVENTION_AGENT_DEV_MODE=0`` 之类的 falsy 值不应触发 override。"""

    def test_zero_does_not_force_dev(self) -> None:
        with (
            patch(
                "ai_intervention_agent.config_manager.sys.executable",
                "/Users/foo/.local/share/uv/tools/aiia/.venv/bin/python",
            ),
            patch.dict(
                os.environ,
                {"AI_INTERVENTION_AGENT_DEV_MODE": "0"},
                clear=False,
            ),
        ):
            os.environ.pop("AI_INTERVENTION_AGENT_USER_MODE", None)
            os.environ.pop("UVX_PROJECT", None)
            self.assertTrue(_is_uvx_mode())

    def test_empty_string_does_not_force_user(self) -> None:
        with patch.dict(
            os.environ,
            {"AI_INTERVENTION_AGENT_USER_MODE": "  "},
            clear=False,
        ):
            os.environ.pop("AI_INTERVENTION_AGENT_DEV_MODE", None)
            os.environ.pop("UVX_PROJECT", None)
            # 不强制 → 走仓库 + cwd 分支 → False（因为本测试就在仓库内跑）。
            self.assertFalse(_is_uvx_mode())


# ---------------------------------------------------------------------------
# Section 4 — find_config_file 多格式冲突 + env override
# ---------------------------------------------------------------------------


class TestFindConfigFileEnvOverrideAbsolute(unittest.TestCase):
    def test_env_override_full_file_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cfg = Path(td) / "explicit.toml"
            cfg.write_text("")
            with patch.dict(
                os.environ,
                {"AI_INTERVENTION_AGENT_CONFIG_FILE": str(cfg)},
                clear=False,
            ):
                result = find_config_file()
                self.assertEqual(result, cfg)

    def test_env_override_directory_appends_filename(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            with patch.dict(
                os.environ,
                {"AI_INTERVENTION_AGENT_CONFIG_FILE": td + os.sep},
                clear=False,
            ):
                result = find_config_file("config.toml")
                self.assertEqual(result, Path(td) / "config.toml")


class TestFindConfigFileMultiFormatWarning(unittest.TestCase):
    """目录里同时存在 TOML/JSONC/JSON 时必须 warn 出来——避免 user-edited
    JSONC 静默被忽略。"""

    def test_warns_when_dev_dir_has_toml_and_jsonc(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "config.toml").write_text("")
            (Path(td) / "config.jsonc").write_text("{}")
            old_cwd = Path.cwd()
            try:
                os.chdir(td)
                with (
                    patch(
                        "ai_intervention_agent.config_manager._is_uvx_mode",
                        return_value=False,
                    ),
                    patch.dict(os.environ, {}, clear=False),
                    self.assertLogs(
                        "ai_intervention_agent.config_manager", level="WARNING"
                    ) as captured,
                ):
                    os.environ.pop("AI_INTERVENTION_AGENT_CONFIG_FILE", None)
                    result = find_config_file("config.toml")
                    self.assertEqual(result.name, "config.toml")
                joined = "\n".join(captured.output)
                self.assertIn("同时存在多种格式", joined)
                self.assertIn("config.jsonc", joined)
            finally:
                os.chdir(old_cwd)

    def test_warns_when_user_dir_has_toml_and_json(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "config.toml").write_text("")
            (Path(td) / "config.json").write_text("{}")
            with (
                patch(
                    "ai_intervention_agent.config_manager._is_uvx_mode",
                    return_value=True,
                ),
                patch(
                    "ai_intervention_agent.config_manager.user_config_dir",
                    return_value=td,
                ),
                patch(
                    "ai_intervention_agent.config_manager.PLATFORMDIRS_AVAILABLE", True
                ),
                patch.dict(os.environ, {}, clear=False),
                self.assertLogs(
                    "ai_intervention_agent.config_manager", level="WARNING"
                ) as captured,
            ):
                os.environ.pop("AI_INTERVENTION_AGENT_CONFIG_FILE", None)
                result = find_config_file("config.toml")
                self.assertEqual(result, Path(td) / "config.toml")
            joined = "\n".join(captured.output)
            self.assertIn("同时存在多种格式", joined)
            self.assertIn("config.json", joined)


class TestFindConfigFileBackwardCompat(unittest.TestCase):
    """老的语义保留：开发模式只在 cwd 找；用户模式只在用户目录找；环境变量优先级最高。"""

    def test_dev_mode_skips_user_dir_when_cwd_has_config(self) -> None:
        with tempfile.TemporaryDirectory() as cwd_dir:
            (Path(cwd_dir) / "config.toml").write_text("")
            old_cwd = Path.cwd()
            try:
                os.chdir(cwd_dir)
                with (
                    patch(
                        "ai_intervention_agent.config_manager._is_uvx_mode",
                        return_value=False,
                    ),
                    patch(
                        "ai_intervention_agent.config_manager.user_config_dir"
                    ) as user_cfg,
                    patch.dict(os.environ, {}, clear=False),
                ):
                    os.environ.pop("AI_INTERVENTION_AGENT_CONFIG_FILE", None)
                    user_cfg.return_value = "/should/not/be/used"
                    result = find_config_file("config.toml")
                    # macOS 把 ``/var/folders/...`` 链接到 ``/private/var/folders/...``，
                    # 所以这里走 resolve() 再比较，防止 symlink 噪声让测试漂移。
                    self.assertEqual(
                        result.resolve(),
                        (Path(cwd_dir) / "config.toml").resolve(),
                    )
                    user_cfg.assert_not_called()
            finally:
                os.chdir(old_cwd)

    def test_user_mode_only_uses_user_dir(self) -> None:
        with (
            tempfile.TemporaryDirectory() as user_dir,
            tempfile.TemporaryDirectory() as cwd_dir,
        ):
            # cwd 有 config.toml 但用户模式应忽略它。
            (Path(cwd_dir) / "config.toml").write_text("")
            (Path(user_dir) / "config.toml").write_text("")
            old_cwd = Path.cwd()
            try:
                os.chdir(cwd_dir)
                with (
                    patch(
                        "ai_intervention_agent.config_manager._is_uvx_mode",
                        return_value=True,
                    ),
                    patch(
                        "ai_intervention_agent.config_manager.user_config_dir",
                        return_value=user_dir,
                    ),
                    patch(
                        "ai_intervention_agent.config_manager.PLATFORMDIRS_AVAILABLE",
                        True,
                    ),
                    patch.dict(os.environ, {}, clear=False),
                ):
                    os.environ.pop("AI_INTERVENTION_AGENT_CONFIG_FILE", None)
                    result = find_config_file("config.toml")
                    self.assertEqual(result, Path(user_dir) / "config.toml")
            finally:
                os.chdir(old_cwd)


if __name__ == "__main__":
    unittest.main()
