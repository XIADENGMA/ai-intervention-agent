"""R63 — server_info_resource ``build`` 块（git commit / branch / dirty）。

设计目标：

* 与 R62 ``runtime`` 互补：``runtime`` 是 Python 解释器视角，``build`` 是
  源码视角——「这个 process 跑的是哪个 commit、是不是 dirty 工作树」；
* ``_resolve_build_info()`` 返回 ``{git_commit, git_branch, git_dirty}``，
  失败字段填 ``"unknown"``；
* 单次 lazy 缓存：第一次调用 fork 3 个 git subprocess，后续直接返回 cache
  浅拷贝；
* 在 .git 不可访问时（pip install / docker / pyinstaller）所有字段降级到
  ``"unknown"``，不抛、不影响其他块；
* Thread-safe：双重检查锁定。

覆盖：

* ``build`` 块顶级 key 存在；
* 三个核心字段（git_commit / git_branch / git_dirty）都在；
* 字段值类型是字符串；
* 真实 git 仓库下 commit 是 7 字符 hex；
* cache 命中：第二次调用不再 fork subprocess；
* `.git` 缺失时三字段全 ``unknown``，不抛；
* 锁存在；
* 与其他 server_info 块互不影响。
"""

from __future__ import annotations

import unittest
from typing import cast
from unittest.mock import patch

import ai_intervention_agent.server as server


class TestResolveBuildInfoBasic(unittest.TestCase):
    def setUp(self) -> None:
        # 每个测试都从干净的 cache 起，避免上一个测试的 cache 影响
        with server._BUILD_INFO_CACHE_LOCK:
            server._BUILD_INFO_CACHE.clear()

    def test_returns_dict_with_three_keys(self) -> None:
        info = server._resolve_build_info()
        self.assertIsInstance(info, dict)
        self.assertIn("git_commit", info)
        self.assertIn("git_branch", info)
        self.assertIn("git_dirty", info)

    def test_all_values_are_strings(self) -> None:
        info = server._resolve_build_info()
        for k, v in info.items():
            self.assertIsInstance(v, str, f"{k!r} 应该是 str，实际 {type(v).__name__}")

    def test_returns_copy_not_internal_cache(self) -> None:
        info1 = server._resolve_build_info()
        info1["git_commit"] = "polluted"
        info2 = server._resolve_build_info()
        self.assertNotEqual(info2["git_commit"], "polluted")


class TestRealGitRepoOutput(unittest.TestCase):
    """本仓库就是 git 仓库，所以应该拿到合法 commit / branch / dirty。"""

    def setUp(self) -> None:
        with server._BUILD_INFO_CACHE_LOCK:
            server._BUILD_INFO_CACHE.clear()

    def test_commit_is_seven_char_hex(self) -> None:
        info = server._resolve_build_info()
        commit = info["git_commit"]
        # ``--short`` 默认 7 字符，但 git 配置可能给 7-12 之间
        # 至少应该是 hex
        self.assertNotEqual(commit, "unknown", "本测试仓库下 commit 不应是 unknown")
        self.assertRegex(commit, r"^[0-9a-f]{7,40}$")

    def test_branch_is_non_empty_string(self) -> None:
        info = server._resolve_build_info()
        branch = info["git_branch"]
        self.assertNotEqual(branch, "unknown")
        # branch 名通常是 ASCII，但 git 允许非 ASCII，所以只检查非空
        self.assertGreater(len(branch), 0)

    def test_dirty_is_yes_or_no(self) -> None:
        info = server._resolve_build_info()
        dirty = info["git_dirty"]
        self.assertIn(dirty, {"yes", "no"})


class TestCacheBehavior(unittest.TestCase):
    """第一次调用 fork subprocess，第二次直接返回 cache。"""

    def setUp(self) -> None:
        with server._BUILD_INFO_CACHE_LOCK:
            server._BUILD_INFO_CACHE.clear()

    def test_second_call_does_not_fork_subprocess(self) -> None:
        with patch("subprocess.check_output") as mock_co:
            mock_co.return_value = b"cached-commit\n"
            info1 = server._resolve_build_info()
            call_count_after_first = mock_co.call_count

        # 第二次：cache 已 warm，不应该再 fork
        with patch("subprocess.check_output") as mock_co_2:
            info2 = server._resolve_build_info()
            self.assertEqual(
                mock_co_2.call_count,
                0,
                "cache warm 后第二次调用不应再 fork subprocess",
            )

        # 内容相同
        self.assertEqual(info1, info2)
        # 第一次至少 fork 过 1 次（实际是 3 次：commit / branch / dirty）
        self.assertGreaterEqual(call_count_after_first, 1)

    def test_cache_persists_through_independent_calls(self) -> None:
        info1 = server._resolve_build_info()
        info2 = server._resolve_build_info()
        info3 = server._resolve_build_info()
        self.assertEqual(info1, info2)
        self.assertEqual(info2, info3)


class TestGitFailureGracefulDegradation(unittest.TestCase):
    """git 不可用 / .git 缺失 / corrupt 时所有字段降级到 ``unknown``。"""

    def setUp(self) -> None:
        with server._BUILD_INFO_CACHE_LOCK:
            server._BUILD_INFO_CACHE.clear()

    def test_subprocess_raises_returns_unknown_for_all_fields(self) -> None:
        with patch(
            "subprocess.check_output", side_effect=FileNotFoundError("git not in PATH")
        ):
            info = server._resolve_build_info()
        self.assertEqual(info["git_commit"], "unknown")
        self.assertEqual(info["git_branch"], "unknown")
        self.assertEqual(info["git_dirty"], "unknown")

    def test_subprocess_timeout_returns_unknown(self) -> None:
        import subprocess as _sp

        with patch(
            "subprocess.check_output",
            side_effect=_sp.TimeoutExpired(cmd="git", timeout=2),
        ):
            info = server._resolve_build_info()
        self.assertEqual(info["git_commit"], "unknown")
        self.assertEqual(info["git_branch"], "unknown")
        self.assertEqual(info["git_dirty"], "unknown")


class TestServerInfoResourceIntegration(unittest.TestCase):
    """server_info_resource 顶层应当包含 build 块。"""

    def setUp(self) -> None:
        with server._BUILD_INFO_CACHE_LOCK:
            server._BUILD_INFO_CACHE.clear()

    def test_top_level_build_key_present(self) -> None:
        info = cast(dict, server.server_info_resource())
        self.assertIn("build", info)

    def test_build_block_is_dict_with_three_fields(self) -> None:
        info = cast(dict, server.server_info_resource())
        build = cast(dict, info["build"])
        for k in ("git_commit", "git_branch", "git_dirty"):
            self.assertIn(k, build)

    def test_outer_failure_recorded_in_build_error(self) -> None:
        with patch.object(
            server, "_resolve_build_info", side_effect=RuntimeError("boom")
        ):
            info = cast(dict, server.server_info_resource())
        self.assertIn("build", info)
        build = cast(dict, info["build"])
        self.assertIn("error", build)
        self.assertIn("boom", build["error"])

    def test_other_blocks_still_present(self) -> None:
        info = cast(dict, server.server_info_resource())
        for k in ("name", "version", "build", "runtime", "process", "fastmcp"):
            self.assertIn(k, info, f"顶层缺 {k}")


class TestModuleLevelAttributes(unittest.TestCase):
    def test_cache_dict_exists(self) -> None:
        self.assertTrue(hasattr(server, "_BUILD_INFO_CACHE"))
        self.assertIsInstance(server._BUILD_INFO_CACHE, dict)

    def test_cache_lock_exists(self) -> None:
        self.assertTrue(hasattr(server, "_BUILD_INFO_CACHE_LOCK"))
        # threading.Lock 不是 class，没法 isinstance；用 acquire/release 鸭子检查
        self.assertTrue(hasattr(server._BUILD_INFO_CACHE_LOCK, "acquire"))
        self.assertTrue(hasattr(server._BUILD_INFO_CACHE_LOCK, "release"))


if __name__ == "__main__":
    unittest.main()
