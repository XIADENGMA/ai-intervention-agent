"""R703 — macOS 上 ``XDG_CONFIG_HOME`` 骑劫标准路径导致 R686 自迁移清零配置的回归。

事故复盘（v1.8.2 现场）
----

R686 的迁移逻辑隐含假设：「标准配置路径（platformdirs 解析）」与「legacy
路径（硬编码 ``~/.config/ai-intervention-agent/``）」在 macOS 上**必然不同**。
该假设被 platformdirs 4.5.0（2025-10）打破——macOS 加入 ``XDGMixin`` 后，
只要用户 shell 导出了 ``XDG_CONFIG_HOME``（最常见的值恰是 ``~/.config``），
``user_config_dir()`` 就返回 ``$XDG_CONFIG_HOME/ai-intervention-agent``：

1. 「标准路径」与「legacy 路径」解析到**同一个文件**；
2. R686 的「双路径内容一致性检查」变成同一文件自比，恒判「一致」；
3. 触发「退休 legacy」分支，把唯一的配置文件改名 ``config.toml.migrated-<ts>``；
4. 返回的「标准路径」已不存在 → ``ConfigManager`` 重建纯默认配置；
5. **每次进程启动重复 1-4**，任何用户自定义（prompt_suffix / 端口 / 声音开关）
   都活不过一次重启；真正的权威配置 ``~/Library/Application Support/...``
   永远不会被读取。

仓库 ``uv.lock`` 锁定 platformdirs 4.3.8（无 XDGMixin），所以仓库内测试全绿、
测不出——本文件通过 patch ``user_config_dir`` 模拟 >= 4.5.0 的 XDG 行为。

R703 修复（两条守卫）
----

* :func:`_resolve_standard_user_config_dir`：macOS 上检测到 platformdirs 结果
  被 ``XDG_CONFIG_HOME`` 改写（返回值 == ``$XDG_CONFIG_HOME/ai-intervention-agent``）
  时，强制改回 Apple 标准路径 ``~/Library/Application Support/ai-intervention-agent``。
  macOS 上标准路径的优先级**恒高于** ``~/.config/...``；想自定义的用户走
  最高优先级的 ``AI_INTERVENTION_AGENT_CONFIG_FILE``。
* :func:`_is_same_physical_file`：R686 退休/迁移分支前先判「同一物理文件」
  （samefile，降级 resolve），命中即跳过——防 symlink（dotfiles 用户把
  ``~/.config/ai-intervention-agent`` 软链到标准目录）等任何路径同一化场景
  把唯一配置真身改名掉。

Linux 行为不变：``$XDG_CONFIG_HOME`` 本来就是 Linux 的标准语义，不干预。
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))


class _R703TestBase(unittest.TestCase):
    """共享 fixture：临时 HOME + 可配置 XDG_CONFIG_HOME + 可配置 platformdirs 返回值。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._home = Path(self._tmp.name)
        self._apple_dir = (
            self._home / "Library" / "Application Support" / "ai-intervention-agent"
        )
        self._apple_file = self._apple_dir / "config.toml"
        self._xdg_dir = self._home / ".config" / "ai-intervention-agent"
        self._xdg_file = self._xdg_dir / "config.toml"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _patch_env(
        self,
        stack: ExitStack,
        system: str,
        *,
        xdg_config_home: str | None,
        platformdirs_returns: Path,
    ) -> None:
        """patch 平台、HOME、env、platformdirs 解析结果。

        ``platformdirs_returns`` 用于模拟不同版本 platformdirs 的行为：
        * 4.3.8（仓库锁定版）：macOS 上恒返回 Apple 路径，无视 XDG env；
        * >= 4.5.0（uvx 线上版）：``XDG_CONFIG_HOME`` 已设置时返回
          ``$XDG_CONFIG_HOME/ai-intervention-agent``。
        """
        from ai_intervention_agent import config_manager

        stack.enter_context(
            patch.object(config_manager.platform, "system", return_value=system)
        )
        stack.enter_context(patch.object(Path, "home", return_value=self._home))
        env: dict[str, str] = {
            "AI_INTERVENTION_AGENT_USER_MODE": "1",
            "AI_INTERVENTION_AGENT_DEV_MODE": "",
            "AI_INTERVENTION_AGENT_CONFIG_FILE": "",
        }
        if xdg_config_home is None:
            env["XDG_CONFIG_HOME"] = ""
        else:
            env["XDG_CONFIG_HOME"] = xdg_config_home
        stack.enter_context(patch.dict(os.environ, env, clear=False))
        stack.enter_context(
            patch.object(
                config_manager,
                "user_config_dir",
                lambda appname: str(platformdirs_returns),
                create=True,
            )
        )
        stack.enter_context(
            patch.object(config_manager, "PLATFORMDIRS_AVAILABLE", True)
        )


class TestResolveStandardUserConfigDirR703(_R703TestBase):
    """``_resolve_standard_user_config_dir`` 单元测试。"""

    def test_macos_xdg_hijack_forced_back_to_apple_path(self) -> None:
        """核心根因：XDG=~/.config + 新版 platformdirs → 必须强制回 Apple 路径。"""
        from ai_intervention_agent.config_manager import (
            _resolve_standard_user_config_dir,
        )

        with ExitStack() as stack:
            self._patch_env(
                stack,
                "Darwin",
                xdg_config_home=str(self._home / ".config"),
                platformdirs_returns=self._xdg_dir,  # 模拟 XDGMixin 改写
            )
            result = _resolve_standard_user_config_dir()

        self.assertEqual(
            result,
            self._apple_dir,
            "macOS 上标准路径必须恒为 Apple 路径，不被 XDG_CONFIG_HOME 改写",
        )

    def test_macos_xdg_custom_dir_also_forced_back(self) -> None:
        """XDG_CONFIG_HOME 指向非 ``~/.config`` 的自定义目录同样要免疫。"""
        from ai_intervention_agent.config_manager import (
            _resolve_standard_user_config_dir,
        )

        custom_xdg = self._home / "xdg-custom"
        with ExitStack() as stack:
            self._patch_env(
                stack,
                "Darwin",
                xdg_config_home=str(custom_xdg),
                platformdirs_returns=custom_xdg / "ai-intervention-agent",
            )
            result = _resolve_standard_user_config_dir()

        self.assertEqual(result, self._apple_dir)

    def test_macos_no_xdg_env_keeps_platformdirs_result(self) -> None:
        """未导出 XDG_CONFIG_HOME → platformdirs 结果（Apple 路径）原样使用。"""
        from ai_intervention_agent.config_manager import (
            _resolve_standard_user_config_dir,
        )

        with ExitStack() as stack:
            self._patch_env(
                stack,
                "Darwin",
                xdg_config_home=None,
                platformdirs_returns=self._apple_dir,
            )
            result = _resolve_standard_user_config_dir()

        self.assertEqual(result, self._apple_dir)

    def test_macos_old_platformdirs_ignoring_xdg_untouched(self) -> None:
        """老版 platformdirs（4.3.8）无视 XDG 返回 Apple 路径 → 守卫不触发。"""
        from ai_intervention_agent.config_manager import (
            _resolve_standard_user_config_dir,
        )

        with ExitStack() as stack:
            self._patch_env(
                stack,
                "Darwin",
                xdg_config_home=str(self._home / ".config"),
                platformdirs_returns=self._apple_dir,  # 老版行为：不理 XDG
            )
            result = _resolve_standard_user_config_dir()

        self.assertEqual(result, self._apple_dir)

    def test_linux_xdg_result_untouched(self) -> None:
        """Linux 上 XDG_CONFIG_HOME 是标准语义，绝不干预。"""
        from ai_intervention_agent.config_manager import (
            _resolve_standard_user_config_dir,
        )

        with ExitStack() as stack:
            self._patch_env(
                stack,
                "Linux",
                xdg_config_home=str(self._home / ".config"),
                platformdirs_returns=self._xdg_dir,
            )
            result = _resolve_standard_user_config_dir()

        self.assertEqual(
            result,
            self._xdg_dir,
            "Linux 上 $XDG_CONFIG_HOME/ai-intervention-agent 就是标准路径",
        )

    def test_platformdirs_unavailable_falls_back_to_apple_on_macos(self) -> None:
        """platformdirs 不可用 → fallback 的 darwin 分支即 Apple 路径。"""
        from ai_intervention_agent import config_manager
        from ai_intervention_agent.config_manager import (
            _resolve_standard_user_config_dir,
        )

        with ExitStack() as stack:
            self._patch_env(
                stack,
                "Darwin",
                xdg_config_home=str(self._home / ".config"),
                platformdirs_returns=self._xdg_dir,
            )
            stack.enter_context(
                patch.object(config_manager, "PLATFORMDIRS_AVAILABLE", False)
            )
            result = _resolve_standard_user_config_dir()

        self.assertEqual(result, self._apple_dir)


class TestIsSamePhysicalFileR703(_R703TestBase):
    """``_is_same_physical_file`` 单元测试。"""

    def test_same_path_is_same_file(self) -> None:
        from ai_intervention_agent.config_manager import _is_same_physical_file

        self._apple_dir.mkdir(parents=True)
        self._apple_file.write_text("x")
        self.assertTrue(_is_same_physical_file(self._apple_file, self._apple_file))

    def test_symlink_resolves_to_same_file(self) -> None:
        from ai_intervention_agent.config_manager import _is_same_physical_file

        self._apple_dir.mkdir(parents=True)
        self._apple_file.write_text("x")
        self._xdg_dir.parent.mkdir(parents=True)
        self._xdg_dir.symlink_to(self._apple_dir, target_is_directory=True)
        self.assertTrue(_is_same_physical_file(self._apple_file, self._xdg_file))

    def test_distinct_files_not_same(self) -> None:
        from ai_intervention_agent.config_manager import _is_same_physical_file

        self._apple_dir.mkdir(parents=True)
        self._apple_file.write_text("x")
        self._xdg_dir.mkdir(parents=True)
        self._xdg_file.write_text("x")  # 内容相同但物理上是两个文件
        self.assertFalse(_is_same_physical_file(self._apple_file, self._xdg_file))

    def test_missing_file_not_same(self) -> None:
        from ai_intervention_agent.config_manager import _is_same_physical_file

        self._apple_dir.mkdir(parents=True)
        self._apple_file.write_text("x")
        self.assertFalse(_is_same_physical_file(self._apple_file, self._xdg_file))


class TestFindConfigFileXdgHijackEndToEndR703(_R703TestBase):
    """端到端复现 v1.8.2 事故场景并验证修复后行为。"""

    def _find(self) -> Path:
        from ai_intervention_agent.config_manager import find_config_file

        return find_config_file()

    def test_v182_incident_config_survives_restarts(self) -> None:
        """事故主场景：XDG 骑劫 + 仅 ``~/.config`` 有配置。

        修复前：每次启动配置被改名 → 重建默认（配置活不过重启）。
        修复后：一次性迁移到 Apple 标准路径，之后每次启动幂等复用。
        """
        content = 'prompt_suffix = "my custom suffix"\n'
        self._xdg_dir.mkdir(parents=True)
        self._xdg_file.write_text(content)

        with ExitStack() as stack:
            self._patch_env(
                stack,
                "Darwin",
                xdg_config_home=str(self._home / ".config"),
                platformdirs_returns=self._xdg_dir,  # 模拟 XDGMixin 改写
            )
            first = self._find()

            # 第一次启动：迁移到 Apple 标准路径
            self.assertEqual(first, self._apple_file, "应迁移并返回 Apple 标准路径")
            self.assertTrue(first.exists(), "返回的路径必须真实存在（修复前不存在）")
            self.assertEqual(first.read_text(), content, "用户自定义必须原样保留")
            migrated_after_first = list(self._xdg_dir.glob("config.toml.migrated-*"))
            self.assertEqual(len(migrated_after_first), 1, "legacy 留一个迁移备份")

            # 第二次启动（模拟重启）：幂等，不再产生新的 migrated 备份
            second = self._find()
            self.assertEqual(second, self._apple_file)
            self.assertEqual(second.read_text(), content, "配置必须活过重启")
            migrated_after_second = list(self._xdg_dir.glob("config.toml.migrated-*"))
            self.assertEqual(
                len(migrated_after_second),
                1,
                "重启不得再次触发迁移（修复前每次启动 +1 个备份）",
            )

    def test_v182_incident_authoritative_library_config_wins(self) -> None:
        """XDG 骑劫 + Library 与 ``~/.config`` 都有且内容不同 → 权威配置必须胜出。"""
        apple_content = 'source = "library"\n'
        xdg_content = 'source = "xdg"\n'
        self._apple_dir.mkdir(parents=True)
        self._apple_file.write_text(apple_content)
        self._xdg_dir.mkdir(parents=True)
        self._xdg_file.write_text(xdg_content)

        with ExitStack() as stack:
            self._patch_env(
                stack,
                "Darwin",
                xdg_config_home=str(self._home / ".config"),
                platformdirs_returns=self._xdg_dir,
            )
            result = self._find()

        self.assertEqual(
            result,
            self._apple_file,
            "修复前 Library 权威配置永远不被读取；修复后必须胜出",
        )
        self.assertEqual(result.read_text(), apple_content)
        self.assertTrue(
            self._xdg_file.exists(),
            "内容不一致时 legacy 保留（warn 由用户人工取舍），不得擅自改名",
        )

    def test_symlinked_legacy_dir_not_retired(self) -> None:
        """samefile 守卫：``~/.config/ai-intervention-agent`` 软链到标准目录。

        dotfiles 用户常见做法。standard 与 legacy 命中同一真身，修复前会把
        真身改名（symlink 目录下的 rename 直接作用于目标文件）导致配置丢失。
        """
        content = 'linked = "yes"\n'
        self._apple_dir.mkdir(parents=True)
        self._apple_file.write_text(content)
        self._xdg_dir.parent.mkdir(parents=True)
        self._xdg_dir.symlink_to(self._apple_dir, target_is_directory=True)

        with ExitStack() as stack:
            self._patch_env(
                stack,
                "Darwin",
                xdg_config_home=None,  # 无 XDG 骑劫，纯 symlink 场景
                platformdirs_returns=self._apple_dir,
            )
            with self.assertLogs(
                "ai_intervention_agent.config_manager", level="INFO"
            ) as cm:
                result = self._find()

        self.assertEqual(result, self._apple_file)
        self.assertTrue(self._apple_file.exists(), "配置真身必须原地保留")
        self.assertEqual(self._apple_file.read_text(), content)
        self.assertEqual(
            list(self._apple_dir.glob("config.toml.migrated-*")),
            [],
            "同一物理文件绝不能触发退休/迁移（修复前真身被改名）",
        )
        self.assertIn("R703", "\n".join(cm.output), "应留下 R703 守卫日志便于回溯")

    def test_symlinked_legacy_file_not_retired(self) -> None:
        """samefile 守卫：目录真实存在、``config.toml`` 本身是软链的变体。"""
        content = 'linked_file = "yes"\n'
        self._apple_dir.mkdir(parents=True)
        self._apple_file.write_text(content)
        self._xdg_dir.mkdir(parents=True)
        self._xdg_file.symlink_to(self._apple_file)

        with ExitStack() as stack:
            self._patch_env(
                stack,
                "Darwin",
                xdg_config_home=None,
                platformdirs_returns=self._apple_dir,
            )
            result = self._find()

        self.assertEqual(result, self._apple_file)
        self.assertTrue(self._apple_file.exists(), "真身必须保留")
        self.assertTrue(self._xdg_file.is_symlink(), "软链本身也不应被改名")
        self.assertEqual(
            list(self._apple_dir.glob("config.toml.migrated-*")),
            [],
        )

    def test_distinct_identical_files_still_retired(self) -> None:
        """回归保护：真正的双文件 + 内容一致场景，R686 退休行为必须保持。"""
        same = 'shared = "yes"\n'
        self._apple_dir.mkdir(parents=True)
        self._apple_file.write_text(same)
        self._xdg_dir.mkdir(parents=True)
        self._xdg_file.write_text(same)

        with ExitStack() as stack:
            self._patch_env(
                stack,
                "Darwin",
                xdg_config_home=None,
                platformdirs_returns=self._apple_dir,
            )
            result = self._find()

        self.assertEqual(result, self._apple_file)
        self.assertFalse(
            self._xdg_file.exists(),
            "两个独立文件内容一致时仍应退休 legacy（R686 原契约）",
        )
        self.assertEqual(
            len(list(self._xdg_dir.glob("config.toml.migrated-*"))),
            1,
        )

    def test_linux_xdg_config_still_standard(self) -> None:
        """Linux 上 ``.config/`` 是标准路径，R703 不得改变其行为。"""
        content = 'linux = "yes"\n'
        self._xdg_dir.mkdir(parents=True)
        self._xdg_file.write_text(content)

        with ExitStack() as stack:
            self._patch_env(
                stack,
                "Linux",
                xdg_config_home=str(self._home / ".config"),
                platformdirs_returns=self._xdg_dir,
            )
            result = self._find()

        self.assertEqual(result, self._xdg_file)
        self.assertEqual(result.read_text(), content)


if __name__ == "__main__":
    unittest.main()
