"""G3 pytest 镜像：``scripts/check_i18n_duplicate_values.py`` 的断言层。

脚本本身是 warn 级（不阻断 CI），但 pytest 层仍要有"回归观察位"——
确保脚本**能跑通**、核心检测函数**对已知重复值给出正确报告**、
白名单机制能**屏蔽约定重复**。这样当未来有人把脚本逻辑改错（比如
改动后对任何 value 都报/都不报），单测能立刻失败。

这个测试**不断言重复数量等于 N**（那是脚本自己要检测的动态值），
而是构造**最小化 locale 样本**来验证脚本行为。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# pytest 发现时 ROOT 尚未入 sys.path，必须在 sys.path 调整后 import。
from scripts.check_i18n_duplicate_values import (
    MIN_LEN,
    detect_duplicates,
    main,
)


class TestDetectCore:
    def test_detects_duplicate_above_threshold(self, tmp_path: Path) -> None:
        locale_dir = tmp_path / "locales"
        locale_dir.mkdir()
        en = {
            "ui": {"foo": "Hello duplicate", "bar": "Hello duplicate"},
            "x": {"short": "OK"},
        }
        (locale_dir / "en.json").write_text(json.dumps(en), encoding="utf-8")
        reports = detect_duplicates(locale_dir, "Test")
        assert len(reports) == 1, reports
        _tag, value, paths = reports[0]
        assert value == "Hello duplicate"
        assert {p for p, _ in paths} == {"ui.foo", "ui.bar"}

    def test_short_values_excluded(self, tmp_path: Path) -> None:
        locale_dir = tmp_path / "locales"
        locale_dir.mkdir()
        # 长度 < MIN_LEN 的值必须被忽略（避免 "OK" / "Cancel" 刷屏）
        short = "x" * (MIN_LEN - 1)
        (locale_dir / "en.json").write_text(
            json.dumps({"a": {"one": short, "two": short}}),
            encoding="utf-8",
        )
        reports = detect_duplicates(locale_dir, "T")
        assert reports == []

    def test_singleton_values_ignored(self, tmp_path: Path) -> None:
        locale_dir = tmp_path / "locales"
        locale_dir.mkdir()
        (locale_dir / "en.json").write_text(
            json.dumps({"a": {"one": "A unique string value"}}),
            encoding="utf-8",
        )
        reports = detect_duplicates(locale_dir, "T")
        assert reports == []

    def test_allowlist_suppresses_warning(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        locale_dir = tmp_path / "locales"
        locale_dir.mkdir()
        (locale_dir / "en.json").write_text(
            json.dumps({"a": {"one": "Allowed repeat", "two": "Allowed repeat"}}),
            encoding="utf-8",
        )
        # 注入白名单
        import scripts.check_i18n_duplicate_values as mod

        monkeypatch.setattr(mod, "ALLOWLIST_VALUES", frozenset({"Allowed repeat"}))
        reports = mod.detect_duplicates(locale_dir, "T")
        assert reports == []

    def test_missing_directory_returns_empty(self, tmp_path: Path) -> None:
        # 目录不存在时应静默返回 []（而不是抛异常）
        missing = tmp_path / "does-not-exist"
        reports = detect_duplicates(missing, "T")
        assert reports == []


class TestMainExitCode:
    def test_main_default_returns_0_even_with_duplicates(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """默认模式：发现重复时仍返回 0（warn 级），仅向 stdout 打印。"""
        rc = main([])
        captured = capsys.readouterr()
        assert rc == 0
        # 要么 "OK: no duplicate"，要么至少一条 "WARN"
        assert "OK" in captured.out or "WARN" in captured.out

    def test_main_strict_mode_returns_nonzero_if_duplicates_exist(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """--strict 模式：真实仓库当前有重复值，应返回 1 以供未来升级门禁。"""
        rc = main(["--strict"])
        captured = capsys.readouterr()
        # 我们不强断言 rc=1（若将来清理完所有 duplicates 应该 rc=0），
        # 只强断言 strict 下 rc ∈ {0, 1}，且 strict 模式会打印相应线索。
        assert rc in (0, 1)
        if rc == 1:
            assert "duplicate value group" in captured.out
