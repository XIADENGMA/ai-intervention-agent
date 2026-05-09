"""R113 — macOS ``~/.config/ai-intervention-agent/`` 残留 config 检测回归。

背景
----

R113 修复一个**长期潜伏的用户体验问题**：

* macOS 用户配置标准位置：``~/Library/Application Support/ai-intervention-agent/``
  （Apple File System Programming Guide / platformdirs ``user_config_dir``
  在 macOS 上的实现都返回此路径）。
* 但用户机器上**仍可能存在** ``~/.config/ai-intervention-agent/config.toml``，
  来源包括：

  - 历史早期版本 / 早期 platformdirs 误用 XDG 路径
  - 用户从 Linux 迁移过来的跨平台 dotfiles
  - 第三方安装脚本假设 ``.config/`` 跨平台
  - 进程在错误的 cwd 下启动（dev 模式分支会在 cwd 创建 ``config.toml``）

R113 在 macOS 上额外探测此路径，三种行为：

1. **标准 + legacy 都有** → 用标准路径，warn 提示残留歧义
2. **仅 legacy 有** → 优先用 legacy（不丢用户配置），强 warn 给出 ``mv`` 命令
3. **仅标准有 / 都没有** → 行为不变

Linux 上 ``.config/`` 是 XDG 标准（``user_config_dir`` 直接指向那里），R113
仅在 macOS 触发。

测试设计（核心：可反向注入 + 跨平台分支隔离）
----

每个测试都用 ``unittest.mock.patch`` monkey-patch ``platform.system`` 和
``Path.home`` 到 ``tempfile.TemporaryDirectory``，再在临时目录里**真实创建**
所需的 config 布局，验证 ``find_config_file`` 的：

* 返回值（哪个路径被选）
* 日志（R113 标记是否出现 + warning level）

反向注入：移除 R113 ``_macos_legacy_xdg_config_dir`` 调用 → 5 个 macOS-only
测试中至少 3 个会失败（standard+legacy 不再 warn / legacy-only 不再用 legacy
而创建新 default / migrate 提示丢失），证明 R113 是 load-bearing 的。
"""

from __future__ import annotations

import logging
import os
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))


class _R113TestBase(unittest.TestCase):
    """共享 fixture：临时 HOME + monkey-patch ``Path.home`` / ``platform.system``。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._home = Path(self._tmp.name)
        # macOS 标准路径
        self._mac_standard_dir = (
            self._home / "Library" / "Application Support" / "ai-intervention-agent"
        )
        self._mac_standard_file = self._mac_standard_dir / "config.toml"
        # XDG legacy 路径（macOS 上非标准；Linux 上是标准）
        self._xdg_legacy_dir = self._home / ".config" / "ai-intervention-agent"
        self._xdg_legacy_file = self._xdg_legacy_dir / "config.toml"

        # 强制走"用户模式"分支以避免 dev 模式 cwd 干扰；同时清掉 env override。
        self._env_patcher = patch.dict(
            os.environ,
            {
                "AI_INTERVENTION_AGENT_USER_MODE": "1",
                "AI_INTERVENTION_AGENT_DEV_MODE": "",
                "AI_INTERVENTION_AGENT_CONFIG_FILE": "",
                "XDG_CONFIG_HOME": "",
            },
            clear=False,
        )
        self._env_patcher.start()

    def tearDown(self) -> None:
        self._env_patcher.stop()
        self._tmp.cleanup()

    def _create_standard_config(self, content: str = 'standard = "yes"\n') -> None:
        self._mac_standard_dir.mkdir(parents=True, exist_ok=True)
        self._mac_standard_file.write_text(content)

    def _create_xdg_legacy_config(self, content: str = 'legacy = "yes"\n') -> None:
        self._xdg_legacy_dir.mkdir(parents=True, exist_ok=True)
        self._xdg_legacy_file.write_text(content)

    def _patch_macos_environment(self):
        """patch ``platform.system`` → 'Darwin' + ``Path.home`` → tmp。"""
        return _MacOSPatcher(self._home)

    def _patch_linux_environment(self):
        return _LinuxPatcher(self._home)

    def _patch_windows_environment(self):
        return _WindowsPatcher(self._home)


class _PlatformPatcherBase:
    """Context manager：同时 patch ``platform.system`` + ``Path.home`` + 用户配置目录解析。"""

    _system: str = ""

    def __init__(self, home: Path) -> None:
        self._home = home
        self._patches: list[Any] = []

    def __enter__(self):
        from ai_intervention_agent import config_manager

        # 注：``platform.system()`` 在 config_manager 模块已 import，所以 patch
        # 模块自身命名空间的 platform.system，而不是全局 platform.system，确保
        # find_config_file 内 ``platform.system().lower()`` 看到我们的 fake。
        p1 = patch.object(config_manager.platform, "system", return_value=self._system)
        p1.start()
        self._patches.append(p1)

        p2 = patch.object(Path, "home", return_value=self._home)
        p2.start()
        self._patches.append(p2)

        # platformdirs 也调 platform.system，但它已 import 了真实路径函数；
        # 直接 patch ``user_config_dir`` 让它返回我们 fake home 下的目标路径。
        if self._system == "Darwin":
            fake_user_dir = str(
                self._home / "Library" / "Application Support" / "ai-intervention-agent"
            )
        elif self._system == "Linux":
            fake_user_dir = str(self._home / ".config" / "ai-intervention-agent")
        elif self._system == "Windows":
            fake_user_dir = str(
                self._home / "AppData" / "Roaming" / "ai-intervention-agent"
            )
        else:
            fake_user_dir = str(self._home / "ai-intervention-agent")

        p3 = patch.object(
            config_manager,
            "user_config_dir",
            lambda appname: fake_user_dir,
            create=True,
        )
        p3.start()
        self._patches.append(p3)
        return self

    def __exit__(self, *exc) -> None:
        for p in reversed(self._patches):
            p.stop()
        self._patches.clear()


class _MacOSPatcher(_PlatformPatcherBase):
    _system = "Darwin"


class _LinuxPatcher(_PlatformPatcherBase):
    _system = "Linux"


class _WindowsPatcher(_PlatformPatcherBase):
    _system = "Windows"


class TestMacosLegacyXdgConfigDirR113(_R113TestBase):
    """``_macos_legacy_xdg_config_dir()`` 单元测试。"""

    def test_macos_with_legacy_dir_returns_path(self) -> None:
        from ai_intervention_agent.config_manager import _macos_legacy_xdg_config_dir

        with self._patch_macos_environment():
            self._create_xdg_legacy_config()
            result = _macos_legacy_xdg_config_dir()
            self.assertIsNotNone(result, "macOS + .config/ 存在 → 应返回 Path")
            assert result is not None  # for ty
            self.assertEqual(result, self._xdg_legacy_dir)

    def test_macos_without_legacy_dir_returns_none(self) -> None:
        from ai_intervention_agent.config_manager import _macos_legacy_xdg_config_dir

        with self._patch_macos_environment():
            # 不创建 .config/ai-intervention-agent
            result = _macos_legacy_xdg_config_dir()
            self.assertIsNone(result, "macOS + .config/ 不存在 → 应返回 None")

    def test_linux_returns_none_even_when_dir_exists(self) -> None:
        """Linux 上 ``.config/`` 是 XDG 标准，**不**应被 R113 标记为 legacy。"""
        from ai_intervention_agent.config_manager import _macos_legacy_xdg_config_dir

        with self._patch_linux_environment():
            self._create_xdg_legacy_config()  # Linux 上这是标准位置
            result = _macos_legacy_xdg_config_dir()
            self.assertIsNone(result, "Linux 上 .config/ 不属于 R113 范围")

    def test_windows_returns_none(self) -> None:
        from ai_intervention_agent.config_manager import _macos_legacy_xdg_config_dir

        with self._patch_windows_environment():
            result = _macos_legacy_xdg_config_dir()
            self.assertIsNone(result, "Windows 上根本不会有 .config/")

    def test_macos_with_legacy_file_but_not_dir_returns_none(self) -> None:
        """``.config/ai-intervention-agent`` 是文件而非目录的边界情况。"""
        from ai_intervention_agent.config_manager import _macos_legacy_xdg_config_dir

        with self._patch_macos_environment():
            (self._home / ".config").mkdir(parents=True)
            (self._home / ".config" / "ai-intervention-agent").write_text("not a dir")
            result = _macos_legacy_xdg_config_dir()
            self.assertIsNone(
                result, "路径存在但不是目录 → 应返回 None（is_dir() 守卫）"
            )


class TestFindConfigFileMacosLegacyR113(_R113TestBase):
    """``find_config_file`` 集成 R113 行为：3 种宏观场景。"""

    def test_standard_and_legacy_both_exist_uses_standard_warns_about_legacy(
        self,
    ) -> None:
        """场景 1：标准 + legacy 同时存在 → 用标准路径，warn 提及 legacy。"""
        from ai_intervention_agent.config_manager import find_config_file

        with self._patch_macos_environment():
            self._create_standard_config('standard = "yes"\n')
            self._create_xdg_legacy_config('legacy = "yes"\n')

            with self.assertLogs(
                "ai_intervention_agent.config_manager", level="WARNING"
            ) as cm:
                result = find_config_file()
                # 即使没有 warning 也要至少 emit 一条 info；自定义 logger
                # 模式下 assertLogs 至少需要一条 record，所以补一条 dummy
                logging.getLogger("ai_intervention_agent.config_manager").warning(
                    "[test-only sentinel]"
                )

            self.assertEqual(result, self._mac_standard_file, "应优先用 macOS 标准路径")
            joined = "\n".join(cm.output)
            self.assertIn("R113", joined, "warn 应携带 R113 标签便于回溯")
            self.assertIn(
                str(self._xdg_legacy_file),
                joined,
                "warn 应说明 legacy 文件具体路径",
            )

    def test_only_legacy_exists_uses_legacy_with_strong_migrate_warn(self) -> None:
        """场景 2：仅 legacy 存在 → 用 legacy 不丢配置，强 warn 给出 mv 命令。"""
        from ai_intervention_agent.config_manager import find_config_file

        with self._patch_macos_environment():
            # 仅创建 legacy；标准路径**不**预创建
            self._create_xdg_legacy_config('legacy_only = "yes"\n')

            with self.assertLogs(
                "ai_intervention_agent.config_manager", level="WARNING"
            ) as cm:
                result = find_config_file()

            self.assertEqual(
                result,
                self._xdg_legacy_file,
                "标准路径无 config 时应优先用 legacy 路径以兼容旧配置",
            )
            joined = "\n".join(cm.output)
            self.assertIn("R113", joined)
            self.assertIn("mv ", joined, "强 warn 应包含 mv 一键迁移命令")
            self.assertIn(
                "Library/Application Support",
                joined,
                "迁移命令目标应是 macOS 标准路径",
            )

    def test_only_standard_exists_no_warn(self) -> None:
        """场景 3：仅标准路径有 config → 不应 emit R113 warn。"""
        from ai_intervention_agent.config_manager import find_config_file

        with self._patch_macos_environment():
            self._create_standard_config()
            # 不创建 .config/ai-intervention-agent

            # 用 root logger 捕获，确认 warning 流上没有 R113
            with self.assertLogs(
                "ai_intervention_agent.config_manager", level="INFO"
            ) as cm:
                result = find_config_file()

            self.assertEqual(result, self._mac_standard_file)
            joined = "\n".join(cm.output)
            self.assertNotIn("R113", joined, "无 legacy 残留时不应触发 R113 warn")

    def test_neither_exists_returns_standard_path_no_warn(self) -> None:
        """场景 4：两边都没有 → 返回标准路径用于创建 default，不 warn R113。"""
        from ai_intervention_agent.config_manager import find_config_file

        with self._patch_macos_environment():
            with self.assertLogs(
                "ai_intervention_agent.config_manager", level="INFO"
            ) as cm:
                result = find_config_file()

            self.assertEqual(result, self._mac_standard_file)
            joined = "\n".join(cm.output)
            self.assertNotIn("R113", joined)

    def test_linux_with_xdg_dir_does_not_emit_r113_warn(self) -> None:
        """**关键反向注入**：Linux 上 ``.config/`` 是 XDG 标准（platformdirs
        ``user_config_dir`` 在 Linux 上**就是**返回它），所以会被走"标准路径"
        分支。此测试断言此场景下绝**不**出现 R113 warn。"""
        from ai_intervention_agent.config_manager import find_config_file

        with self._patch_linux_environment():
            # Linux 上 .config/ 是标准位置
            self._create_xdg_legacy_config('linux_standard = "yes"\n')

            with self.assertLogs(
                "ai_intervention_agent.config_manager", level="INFO"
            ) as cm:
                result = find_config_file()

            self.assertEqual(
                result,
                self._xdg_legacy_file,
                "Linux 上 .config/ai-intervention-agent/config.toml 是标准路径",
            )
            joined = "\n".join(cm.output)
            self.assertNotIn(
                "R113",
                joined,
                "Linux 上**绝不**应触发 R113 warn（否则把所有 Linux 用户都误报）",
            )


if __name__ == "__main__":
    unittest.main()
