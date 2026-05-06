"""R12·A4 · ``scripts/package_vscode_vsix.mjs`` 尺寸预算静态守护。

打包脚本里 ``WARN_PACKED_MB_DEFAULT`` / ``FAIL_PACKED_MB_DEFAULT`` 是
"出厂"阈值；env var 只能在临时 escape hatch 场景覆盖。这条测试
做两件事：

1. **常量存在性**：确认两个默认值还在脚本里、还在 1-50 MB 这个
   合理区间。防止"为通过 CI 把阈值改到 100 MB"这种自残式改动
   被悄悄合并 —— 任何对默认值的调整必须同步修改本测试，从而
   被 PR review 看见。

2. **WARN ≤ FAIL 顺序**：硬性要求 ``WARN_PACKED_MB_DEFAULT
   <= FAIL_PACKED_MB_DEFAULT``。如果作者把 WARN 写得比 FAIL
   高，运行时会 ``process.exit(1)``（脚本里另有运行时 guard），
   但这条静态 check 让作者在 PR 阶段就被卡住，不用等到 CI 跑
   到打包步骤才发现。

3. **当前 VSIX 尺寸 < FAIL_PACKED_MB_DEFAULT**：如果上一次
   打包产物 ``packages/vscode/*.vsix`` 存在，确认它没超 FAIL
   阈值；这一步是软 check，仅当文件存在时才比较，避免在
   "刚 clone、还没打过包"的 dev 机器上无效红屏。

为什么写在 Python 端：本仓库 ci_gate 唯一驱动器是 pytest，把
dev-experience guard 都集中在 ``tests/`` 下能让一次 ``make ci``
全跑完，无需另外发明 mocha/jest job。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "package_vscode_vsix.mjs"
VSIX_DIR = REPO_ROOT / "packages" / "vscode"

# 历史经验：marketplace 实际允许 ~100 MB；超过 50 MB 已经反映
# 出"打错文件"的等级。所以"合理上限"卡在 50 MB；"合理下限"
# 卡在 1 MB（再低就连主入口和 webview-ui.js 都装不下了）。
SANE_MIN_MB = 1
SANE_MAX_MB = 50


def _read_script_text() -> str:
    assert SCRIPT_PATH.exists(), f"打包脚本缺失：{SCRIPT_PATH}"
    return SCRIPT_PATH.read_text(encoding="utf-8")


def _extract_default_mb(name: str) -> int:
    """从 mjs 里抓 ``const NAME = 整数`` 字面量。

    脚本里的写法形如 ``const WARN_PACKED_MB_DEFAULT = 4``，
    用正则就够了；不用上 acorn —— 增加依赖只为这一行不划算。
    """
    text = _read_script_text()
    m = re.search(rf"\bconst\s+{re.escape(name)}\s*=\s*(\d+)\b", text)
    assert m, (
        f"未在 {SCRIPT_PATH.name} 里找到 ``const {name} = <int>``；"
        "可能被 rename 或删除——请同步更新本测试。"
    )
    return int(m.group(1))


class TestSizeBudgetDefaultsArePresent:
    """常量存在性 + 数值在合理区间。"""

    def test_warn_default_in_sane_range(self) -> None:
        warn_mb = _extract_default_mb("WARN_PACKED_MB_DEFAULT")
        assert SANE_MIN_MB <= warn_mb <= SANE_MAX_MB, (
            f"WARN_PACKED_MB_DEFAULT={warn_mb} MB 不在合理区间 "
            f"[{SANE_MIN_MB}, {SANE_MAX_MB}] MB；"
            "上调到 >50 MB 通常意味着误打包了大资源，请审查。"
        )

    def test_fail_default_in_sane_range(self) -> None:
        fail_mb = _extract_default_mb("FAIL_PACKED_MB_DEFAULT")
        assert SANE_MIN_MB <= fail_mb <= SANE_MAX_MB, (
            f"FAIL_PACKED_MB_DEFAULT={fail_mb} MB 不在合理区间 "
            f"[{SANE_MIN_MB}, {SANE_MAX_MB}] MB；"
            "上调到 >50 MB 等于关掉硬上限，请审查。"
        )

    def test_warn_le_fail(self) -> None:
        warn_mb = _extract_default_mb("WARN_PACKED_MB_DEFAULT")
        fail_mb = _extract_default_mb("FAIL_PACKED_MB_DEFAULT")
        assert warn_mb <= fail_mb, (
            f"WARN_PACKED_MB_DEFAULT={warn_mb} > FAIL_PACKED_MB_DEFAULT={fail_mb}；"
            "脚本里另有运行时 guard 会 process.exit(1)，但这里也得卡住，"
            "避免 PR 合并后才在 release 流水线被发现。"
        )

    def test_runtime_guard_for_warn_gt_fail_present(self) -> None:
        text = _read_script_text()
        assert "failMb < warnMb" in text, (
            "scripts/package_vscode_vsix.mjs 应保留 ``failMb < warnMb`` 的运行时 "
            "guard，否则 env var 覆盖时可能让 WARN > FAIL 而不报错。"
        )

    def test_size_check_uses_packed_bytes_via_statSync(self) -> None:
        """守卫真在打包后跑——而不是 grep 不到的 dead code。"""
        text = _read_script_text()
        assert "fs.statSync(outVsix).size" in text, (
            "尺寸 check 必须用 ``fs.statSync(outVsix).size`` 读 packed 字节数；"
            "如果改成 unpacked 大小（5.11 MB）会让阈值含义和注释偏离。"
        )
        assert "process.exit(1)" in text, (
            "超 FAIL 阈值时必须 fail-closed（``process.exit(1)``），不能只 warn。"
        )

    def test_success_summary_uses_neutral_threshold_labels(self) -> None:
        """成功路径不应输出 WARN/FAIL 字样，避免健康 CI 日志被误读。"""
        text = _read_script_text()
        assert "review threshold ≥ ${warnMb} MB" in text
        assert "hard limit ≥ ${failMb} MB" in text
        assert "；WARN ≥ ${warnMb} MB；FAIL ≥ ${failMb} MB" not in text


class TestExistingVsixWithinBudget:
    """如果产物存在，确认它没破阈值。"""

    def test_vsix_artifact_under_fail_budget_if_present(self) -> None:
        candidates = sorted(VSIX_DIR.glob("*.vsix"))
        if not candidates:
            msg = (
                "packages/vscode/*.vsix 不存在（dev 机器尚未打包），跳过尺寸软 check。"
                "CI 在 release.yml 里会主动跑 npm run package，触发硬 check。"
            )
            pytest.skip(msg)  # ty: ignore[too-many-positional-arguments]
        fail_mb = _extract_default_mb("FAIL_PACKED_MB_DEFAULT")
        fail_bytes = fail_mb * 1024 * 1024
        for vsix in candidates:
            size = vsix.stat().st_size
            assert size < fail_bytes, (
                f"{vsix.name} 体积 {size / (1024 * 1024):.2f} MB 已超 FAIL "
                f"阈值 {fail_mb} MB；请检查 includeList 与最新依赖。"
            )
