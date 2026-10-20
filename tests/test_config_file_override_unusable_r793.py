"""R793 — 指向"无法检查的路径"的 ``AI_INTERVENTION_AGENT_CONFIG_FILE`` 不再让整个产品起不来。

事故现场
--------
``find_config_file`` 在查标准配置位置时整段包在 ``except Exception`` 里（出错就回退到
当前目录并打一条警告），但 **环境变量覆盖这一支没有任何保护**：

    if override_path.is_dir() or override.endswith(("/", backslash)):

``Path.is_dir()`` 只把"路径不存在"这一类错误（ENOENT / ENOTDIR / ELOOP / EBADF）当成
``False``，其它错误照常抛出。于是下面三种写法让 ``import ai_intervention_agent.server`` 直接
带着原始 traceback 失败——MCP 服务器起不来、Web UI 起不来、``--print-config`` 也起不来
（``config_manager`` 在 import 时就实例化了全局 ``ConfigManager()``）：

* 路径落在一个当前用户没有搜索权限的目录里（``EACCES``，比如 ``/root/...``、别的用户的家目录、
  chmod 000 的目录）→ ``PermissionError``；
* 路径的某一段超过文件系统上限（``ENAMETOOLONG``，把一整段文字误贴进环境变量就会这样）→
  ``OSError``；
* ``~没有这个用户/...`` → ``Path.expanduser()`` 抛 ``RuntimeError``。

同类的环境变量（``..._WEB_UI_PORT=abc``、``..._LOG_LEVEL=bogus``）早就是"忽略 + 警告"。
这条覆盖是唯一一个写错就让进程崩溃的。

契约
----
* 覆盖路径检查不了（``stat`` 报了"不存在"以外的错）时：忽略这个环境变量，打**一条**警告
  （写明变量名、原值、原因、后果），按没有设置它的情况继续找标准配置位置。
* 覆盖路径"只是不存在"（目录不存在、父路径里有个普通文件、文件还没创建）照旧：用它，
  文件由后面的流程创建。
* 能用的覆盖（已有文件、目录、带 ``~``）一律不变。
"""

from __future__ import annotations

import errno
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from ai_intervention_agent import config_manager as cm

ENV_NAME = "AI_INTERVENTION_AGENT_CONFIG_FILE"
LOGGER_NAME = "ai_intervention_agent.config_manager"

POSIX_ONLY = pytest.mark.skipif(
    sys.platform == "win32", reason="chmod / ENAMETOOLONG / ~user are POSIX behaviours"
)
NOT_ROOT = pytest.mark.skipif(
    sys.platform == "win32" or os.geteuid() == 0,
    reason="root ignores directory permissions",
)


@pytest.fixture
def standard_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """让"标准配置位置"落在 tmp 里：测试不碰真实的用户配置目录。"""
    standard = tmp_path / "standard"
    monkeypatch.setattr(cm, "_is_uvx_mode", lambda: True)
    monkeypatch.setattr(cm, "_resolve_standard_user_config_dir", lambda: standard)
    monkeypatch.setattr(cm, "_macos_legacy_xdg_config_dir", lambda: None)
    return standard


def _find(
    override: str, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> tuple[Path, list[str]]:
    monkeypatch.setenv(ENV_NAME, override)
    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        found = cm.find_config_file("config.toml")
    warnings = [
        record.getMessage()
        for record in caplog.records
        if record.levelno >= logging.WARNING and record.name == LOGGER_NAME
    ]
    return found, warnings


# ---------------------------------------------------------------------------
# 1. 真实环境里的三种写法
# ---------------------------------------------------------------------------
class TestRealWorldPaths:
    @NOT_ROOT
    def test_a_directory_nobody_may_enter(
        self,
        tmp_path: Path,
        standard_dir: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        locked = tmp_path / "locked"
        locked.mkdir()
        locked.chmod(0)
        try:
            found, warnings = _find(str(locked / "config.toml"), monkeypatch, caplog)
        finally:
            locked.chmod(0o755)
        assert found == standard_dir / "config.toml"
        assert len(warnings) == 1
        assert ENV_NAME in warnings[0]
        assert "Permission denied" in warnings[0]

    @POSIX_ONLY
    def test_a_name_longer_than_the_filesystem_allows(
        self,
        tmp_path: Path,
        standard_dir: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        long_path = str(tmp_path / ("a" * 400) / "config.toml")
        found, warnings = _find(long_path, monkeypatch, caplog)
        assert found == standard_dir / "config.toml"
        assert len(warnings) == 1
        assert ENV_NAME in warnings[0]
        assert "File name too long" in warnings[0]

    @POSIX_ONLY
    def test_a_home_directory_of_nobody(
        self,
        standard_dir: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        found, warnings = _find("~no_such_user_r793/config.toml", monkeypatch, caplog)
        assert found == standard_dir / "config.toml"
        assert len(warnings) == 1
        assert ENV_NAME in warnings[0]
        assert "~no_such_user_r793/config.toml" in warnings[0]


# ---------------------------------------------------------------------------
# 2. 模拟各种 stat 失败（不依赖当前用户 / 操作系统）
# ---------------------------------------------------------------------------
UNEXAMINABLE = [
    PermissionError(errno.EACCES, "Permission denied"),
    OSError(errno.ENAMETOOLONG, "File name too long"),
    OSError(errno.EIO, "Input/output error"),
    OSError(errno.ESTALE, "Stale file handle"),
    OSError(errno.ETIMEDOUT, "Operation timed out"),
    OSError(errno.EINVAL, "Invalid argument"),
]


class Mount:
    """``tmp/mount`` 下面的任何东西都会让 ``os.stat`` 报 ``error``（由测试设置）。"""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.error: BaseException | None = None


@pytest.fixture
def unreadable_mount(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Mount:
    mount = Mount(tmp_path / "mount")
    mount.path.mkdir()
    real_stat = os.stat

    def fake_stat(path: Any, *args: Any, **kwargs: Any) -> os.stat_result:
        if mount.error is not None and str(path).startswith(str(mount.path) + os.sep):
            raise mount.error
        return real_stat(path, *args, **kwargs)

    monkeypatch.setattr(os, "stat", fake_stat)
    return mount


@pytest.mark.parametrize(
    "error", UNEXAMINABLE, ids=[errno.errorcode[e.errno or 0] for e in UNEXAMINABLE]
)
def test_any_error_other_than_not_there_means_ignore_the_variable(
    error: OSError,
    unreadable_mount: Mount,
    standard_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    unreadable_mount.error = error
    override = str(unreadable_mount.path / "deep" / "config.toml")
    found, warnings = _find(override, monkeypatch, caplog)
    assert found == standard_dir / "config.toml"
    assert len(warnings) == 1
    assert ENV_NAME in warnings[0]
    assert override in warnings[0]
    assert str(error.strerror) in warnings[0]


@pytest.mark.parametrize(
    "error",
    [
        FileNotFoundError(errno.ENOENT, "No such file or directory"),
        NotADirectoryError(errno.ENOTDIR, "Not a directory"),
        OSError(errno.ELOOP, "Too many levels of symbolic links"),
    ],
    ids=["ENOENT", "ENOTDIR", "ELOOP"],
)
def test_a_path_that_is_simply_not_there_is_still_honoured(
    error: OSError,
    unreadable_mount: Mount,
    standard_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    unreadable_mount.error = error
    override = str(unreadable_mount.path / "deep" / "config.toml")
    found, warnings = _find(override, monkeypatch, caplog)
    assert found == Path(override)
    assert warnings == []


# ---------------------------------------------------------------------------
# 3. 能用的覆盖一律不变
# ---------------------------------------------------------------------------
class TestUsableOverridesAreUnchanged:
    def test_an_existing_file(
        self,
        tmp_path: Path,
        standard_dir: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        cfg = tmp_path / "mine.toml"
        cfg.write_text("", encoding="utf-8")
        found, warnings = _find(str(cfg), monkeypatch, caplog)
        assert found == cfg
        assert warnings == []

    def test_a_file_that_is_not_created_yet(
        self,
        tmp_path: Path,
        standard_dir: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        cfg = tmp_path / "later.toml"
        found, warnings = _find(str(cfg), monkeypatch, caplog)
        assert found == cfg
        assert warnings == []

    def test_a_directory_that_does_not_exist_yet(
        self,
        tmp_path: Path,
        standard_dir: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        cfg = tmp_path / "new" / "dir" / "config.toml"
        found, warnings = _find(str(cfg), monkeypatch, caplog)
        assert found == cfg
        assert warnings == []

    def test_a_directory_gets_the_file_name_appended(
        self,
        tmp_path: Path,
        standard_dir: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        for override in (str(tmp_path), str(tmp_path) + os.sep):
            found, warnings = _find(override, monkeypatch, caplog)
            assert found == tmp_path / "config.toml"
            assert warnings == []

    def test_a_file_name_below_a_regular_file(
        self,
        tmp_path: Path,
        standard_dir: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        regular = tmp_path / "regular-file"
        regular.write_text("", encoding="utf-8")
        override = str(regular / "config.toml")
        found, warnings = _find(override, monkeypatch, caplog)
        assert found == Path(override)
        assert warnings == []

    @POSIX_ONLY
    def test_a_tilde_path(
        self,
        tmp_path: Path,
        standard_dir: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        monkeypatch.setenv("HOME", str(tmp_path))
        found, warnings = _find("~/aiia/config.toml", monkeypatch, caplog)
        assert found == tmp_path / "aiia" / "config.toml"
        assert warnings == []

    def test_an_empty_value_is_not_an_override(
        self,
        standard_dir: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        found, warnings = _find("", monkeypatch, caplog)
        assert found == standard_dir / "config.toml"
        assert warnings == []


# ---------------------------------------------------------------------------
# 3b. 判定规则本身
# ---------------------------------------------------------------------------
class TestTheVerdict:
    def test_a_file_that_exists_can_be_examined(self, tmp_path: Path) -> None:
        cfg = tmp_path / "config.toml"
        cfg.write_text("", encoding="utf-8")
        assert cm._why_path_cannot_be_examined(cfg) is None

    def test_a_path_that_is_not_there_can_be_examined(self, tmp_path: Path) -> None:
        assert (
            cm._why_path_cannot_be_examined(tmp_path / "nope" / "config.toml") is None
        )

    def test_an_embedded_nul_is_a_reason(self) -> None:
        # 环境变量里放不进 NUL，但路径可能来自别处；ValueError 同样不能逃出去
        assert "null" in (cm._why_path_cannot_be_examined(Path("a\x00b")) or "")

    def test_the_reason_is_the_system_message_not_the_whole_path(
        self, unreadable_mount: Mount
    ) -> None:
        unreadable_mount.error = PermissionError(
            errno.EACCES, "Permission denied", str(unreadable_mount.path / "x")
        )
        reason = cm._why_path_cannot_be_examined(unreadable_mount.path / "x")
        assert reason == "Permission denied"

    @pytest.mark.parametrize("winerror", [21, 123, 1921])
    def test_the_windows_not_there_family_is_not_there(
        self, unreadable_mount: Mount, winerror: int
    ) -> None:
        error = OSError(errno.EINVAL, "Invalid name")
        object.__setattr__(error, "winerror", winerror)  # 只有 Windows 的 OSError 自带
        unreadable_mount.error = error
        assert cm._why_path_cannot_be_examined(unreadable_mount.path / "x") is None


# ---------------------------------------------------------------------------
# 4. ConfigManager 用的就是回退后的路径，而且没有动用户指定的位置
# ---------------------------------------------------------------------------
@POSIX_ONLY
def test_config_manager_uses_the_standard_file_and_leaves_the_override_alone(
    tmp_path: Path,
    standard_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    long_dir = tmp_path / ("a" * 400)
    monkeypatch.setenv(ENV_NAME, str(long_dir / "config.toml"))
    manager = cm.ConfigManager()
    try:
        assert manager.config_file == standard_dir / "config.toml"
        assert manager.get_section("web_ui")["port"] > 0
    finally:
        manager.shutdown()
    assert not any(entry.name.startswith("aaaa") for entry in tmp_path.iterdir())


# ---------------------------------------------------------------------------
# 5. 真正的进程：import 服务器
# ---------------------------------------------------------------------------
IMPORT_THE_SERVER = (
    "import ai_intervention_agent.server; "
    "from ai_intervention_agent import config_manager; "
    "print('IMPORTED ' + str(config_manager.config_manager.config_file))"
)


def _import_the_server(
    tmp_path: Path, override: str
) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        ENV_NAME: override,
        "HOME": str(tmp_path / "home"),
        "XDG_CONFIG_HOME": str(tmp_path / "xdg"),
        "APPDATA": str(tmp_path / "appdata"),
        "AI_INTERVENTION_AGENT_USER_MODE": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    env.pop("AI_INTERVENTION_AGENT_DEV_MODE", None)
    return subprocess.run(
        [sys.executable, "-c", IMPORT_THE_SERVER],
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


@POSIX_ONLY
def test_the_server_imports_with_a_name_that_is_too_long(tmp_path: Path) -> None:
    proc = _import_the_server(tmp_path, str(tmp_path / ("a" * 400) / "config.toml"))
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert "IMPORTED" in proc.stdout
    assert "a" * 400 not in proc.stdout


@POSIX_ONLY
def test_the_server_imports_with_the_home_of_a_user_that_does_not_exist(
    tmp_path: Path,
) -> None:
    proc = _import_the_server(tmp_path, "~no_such_user_r793/config.toml")
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert "IMPORTED" in proc.stdout


@NOT_ROOT
def test_the_server_imports_with_a_directory_nobody_may_enter(tmp_path: Path) -> None:
    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(0)
    try:
        proc = _import_the_server(tmp_path, str(locked / "config.toml"))
    finally:
        locked.chmod(0o755)
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert "IMPORTED" in proc.stdout
    assert not (locked / "config.toml").exists()
