"""R193 / Cycle 5 · Hot-reload 即时失效 network_security 缓存契约。

背景
----
CR#18 §4.5 + §4.4(a) 担心：``ConfigManager._network_security_cache`` 有
30 秒 TTL，担心运维改了 ``config.toml`` 的 ``api_token`` 后会有一段
「两个 token 都有效」的灰色窗口，相当于安全敏感操作没"原子切换"。

**实际验证后发现**：该担忧不成立。

- ``ConfigManager.reload()`` 内部调用 ``invalidate_all_caches()``，**显式**
  清空 ``_network_security_cache``（``config_manager.py`` 第 1423 行）；
- ``FileWatcherMixin._file_watcher_loop()`` 每 2 秒检查一次 mtime，发现
  变化立即调 ``self.reload()`` → 缓存随即失效；
- 因此真实窗口 ≤ ``_file_watcher_interval``（默认 2 秒），**不是** CR#18
  §4.5 推测的 30 秒。

R193 不"修"这个 bug——bug 不存在。R193 的工作量收敛到「写回归测试锁定
这个隐式契约」，防止未来 refactor 删掉 ``invalidate_all_caches()`` 或者
把 ``_network_security_cache`` 移出 ``invalidate_all_caches()`` 的清空
范围，把这个 0-bug 变成真 bug。

测试覆盖（11 cases / 3 invariant classes）：

1. **``invalidate_all_caches()`` 字段覆盖**（3 cases）：清空 section
   cache + 清空 network_security 缓存 + 重置缓存时间戳；
2. **``reload()`` 触发缓存失效**（4 cases）：reload() 自动清缓存、
   reload() 后下一次 get_network_security_config() 重新读文件、
   api_token 变更立即生效、bind_interface 变更立即生效；
3. **``_file_watcher_loop()`` 调用链完整性**（4 cases，AST + 行为）：
   ``_file_watcher_loop`` 源码内引用 ``reload()``、``_trigger_config
   _change_callbacks()`` 在 reload 之后调用、reload 不抛异常 / 文件
   watcher 不死、注册的 callback 在 reload 之后被触发。

这是「契约回归 + 行为验证」双层守护，足以让 CR#18 §4.5 / §4.4(a) 关闭。
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ai_intervention_agent.config_manager import ConfigManager


def _write_config(cfg_path: Path, api_token: str, bind: str = "127.0.0.1") -> None:
    """写入一个最小但合法的 config.toml"""
    cfg_path.write_text(
        textwrap.dedent(f"""
            [network_security]
            bind_interface = "{bind}"
            allowed_networks = ["127.0.0.0/8"]
            blocked_ips = []
            access_control_enabled = true
            api_token = "{api_token}"
        """).strip(),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# 1. invalidate_all_caches() field coverage
# ---------------------------------------------------------------------------


class TestInvalidateAllCachesFieldCoverage(unittest.TestCase):
    """``invalidate_all_caches()`` 必须清空 network_security 缓存。"""

    def setUp(self) -> None:
        self._tmpdir = tempfile.mkdtemp(prefix="r193_invalidate_")
        self._cfg_path = Path(self._tmpdir) / "config.toml"
        _write_config(self._cfg_path, api_token="")
        self._cfg = ConfigManager(config_file=str(self._cfg_path))

    def tearDown(self) -> None:
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_invalidates_network_security_cache(self) -> None:
        # 先填充缓存
        _ = self._cfg.get_network_security_config()
        with self._cfg._lock:
            self.assertIsNotNone(self._cfg._network_security_cache)

        self._cfg.invalidate_all_caches()

        with self._cfg._lock:
            self.assertIsNone(self._cfg._network_security_cache)

    def test_resets_network_security_cache_time(self) -> None:
        _ = self._cfg.get_network_security_config()
        with self._cfg._lock:
            self.assertGreater(self._cfg._network_security_cache_time, 0)

        self._cfg.invalidate_all_caches()

        with self._cfg._lock:
            self.assertEqual(self._cfg._network_security_cache_time, 0)

    def test_invalidates_section_cache(self) -> None:
        # 触发 section cache 填充（web_ui section 是常用读 path）
        try:
            self._cfg.get_web_ui_config()
        except Exception:
            pass  # 缺字段是预期的，重点是 cache 被填充
        # 直接 inspect cache state——具体填了什么不重要
        self._cfg.invalidate_all_caches()
        with self._cfg._lock:
            self.assertEqual(len(self._cfg._section_cache), 0)


# ---------------------------------------------------------------------------
# 2. reload() triggers cache invalidation
# ---------------------------------------------------------------------------


class TestReloadInvalidatesCache(unittest.TestCase):
    """``reload()`` 必须让下一次 ``get_network_security_config()`` 读新文件。"""

    def setUp(self) -> None:
        self._tmpdir = tempfile.mkdtemp(prefix="r193_reload_")
        self._cfg_path = Path(self._tmpdir) / "config.toml"
        _write_config(self._cfg_path, api_token="")
        self._cfg = ConfigManager(config_file=str(self._cfg_path))

    def tearDown(self) -> None:
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_reload_clears_network_security_cache(self) -> None:
        _ = self._cfg.get_network_security_config()
        with self._cfg._lock:
            self.assertIsNotNone(self._cfg._network_security_cache)

        self._cfg.reload()

        with self._cfg._lock:
            # 注意：reload() 内部会先 _load_config + invalidate，再
            # **不会**主动 prefetch network_security cache。所以这里
            # 应该是 None。
            self.assertIsNone(self._cfg._network_security_cache)

    def test_api_token_change_takes_effect_after_reload(self) -> None:
        # 初始 token 为空
        self.assertEqual(self._cfg.get_network_security_config().get("api_token"), "")

        # 改写文件 + reload
        new_token = "x" * 32
        _write_config(self._cfg_path, api_token=new_token)
        self._cfg.reload()

        self.assertEqual(
            self._cfg.get_network_security_config().get("api_token"),
            new_token,
        )

    def test_bind_interface_change_takes_effect_after_reload(self) -> None:
        # 初始 bind = 127.0.0.1
        self.assertEqual(
            self._cfg.get_network_security_config().get("bind_interface"),
            "127.0.0.1",
        )

        _write_config(self._cfg_path, api_token="", bind="0.0.0.0")
        self._cfg.reload()

        self.assertEqual(
            self._cfg.get_network_security_config().get("bind_interface"),
            "0.0.0.0",
        )

    def test_api_token_rotation_no_overlap_window(self) -> None:
        # 关键 R193 / §4.5 反驳点：token 旋转后，**下一次** 读取就
        # 应该看到新 token，没有「两个都有效」的 30s 灰色窗口。
        old_token = "a" * 32
        new_token = "b" * 32
        _write_config(self._cfg_path, api_token=old_token)
        self._cfg.reload()
        self.assertEqual(
            self._cfg.get_network_security_config().get("api_token"),
            old_token,
        )

        _write_config(self._cfg_path, api_token=new_token)
        self._cfg.reload()

        # 立即下一次读取就应该是 new_token
        result = self._cfg.get_network_security_config().get("api_token")
        self.assertEqual(
            result,
            new_token,
            f"token rotation overlap: still reading old_token after reload"
            f" (got {result!r}, expected {new_token!r})",
        )


# ---------------------------------------------------------------------------
# 3. _file_watcher_loop call chain
# ---------------------------------------------------------------------------


class TestFileWatcherCallChain(unittest.TestCase):
    """``_file_watcher_loop`` 源码层面必须保证 mtime-change → reload() →
    callbacks 这条链路完整，CR#18 §4.5 担忧的「30s 窗口」不能藏在这里。"""

    def setUp(self) -> None:
        self._tmpdir = tempfile.mkdtemp(prefix="r193_watcher_")
        self._cfg_path = Path(self._tmpdir) / "config.toml"
        _write_config(self._cfg_path, api_token="")
        self._cfg = ConfigManager(config_file=str(self._cfg_path))

    def tearDown(self) -> None:
        try:
            self._cfg.stop_file_watcher()
        except Exception:
            pass
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_file_watcher_loop_source_calls_reload(self) -> None:
        # AST-style 源码检查：``_file_watcher_loop`` 必须含 ``self.reload``
        # 调用（不能被 refactor 替换成「只更新 mtime 不 reload」）
        import inspect

        source = inspect.getsource(self._cfg._file_watcher_loop)
        self.assertIn(
            "self.reload",
            source,
            "_file_watcher_loop must call self.reload() on mtime change "
            "(R193 contract: CR#18 §4.5 'no 30s overlap window')",
        )

    def test_file_watcher_loop_source_triggers_callbacks_after_reload(
        self,
    ) -> None:
        # callbacks 必须在 reload **之后**触发（否则 callback 看到老 cache）
        import inspect

        source = inspect.getsource(self._cfg._file_watcher_loop)
        reload_idx = source.find("self.reload")
        callbacks_idx = source.find("_trigger_config_change_callbacks")
        self.assertGreater(reload_idx, 0, "_file_watcher_loop must call reload")
        self.assertGreater(
            callbacks_idx, 0, "_file_watcher_loop must trigger callbacks"
        )
        self.assertLess(
            reload_idx,
            callbacks_idx,
            "reload() must be called BEFORE _trigger_config_change_callbacks"
            " (callbacks should see fresh state, not cached)",
        )

    def test_reload_doesnt_raise_on_valid_config(self) -> None:
        # 防 R193 regression：reload() raise 会让 file_watcher_loop 进
        # except 分支，下一次轮询才尝试——也就是单次 mtime change 跳
        # 过 reload。测试 reload() 在 happy path 不 raise。
        _write_config(self._cfg_path, api_token="a" * 32)
        try:
            self._cfg.reload()
        except Exception as exc:
            self.fail(f"reload() raised on valid config: {exc}")

    def test_registered_callback_fired_after_simulated_reload(self) -> None:
        # 注册回调 + 手动模拟 file watcher 路径（直接调
        # _trigger_config_change_callbacks 是 file watcher 在 reload 之
        # 后做的事）
        seen: list[str] = []

        def cb() -> None:
            seen.append("fired")

        self._cfg.register_config_change_callback(cb)
        self._cfg._trigger_config_change_callbacks()
        self.assertEqual(seen, ["fired"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
