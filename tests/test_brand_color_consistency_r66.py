"""R66：CSS 品牌色硬编码漂移检测器测试。

锁定 ``scripts/check_brand_color_consistency.py`` 的核心行为：

1. ``strip_css_comments`` 正确剔除 ``/* ... */`` 块（防止注释里的
   ``rgba(0, 122, 255, X)`` 文档引用被误计为样式硬编码）；
2. ``count_ios_blue`` 与 ``find_ios_blue_locations`` 容忍 rgba/rgb、
   任意空白、不同 alpha 通道；
3. CLI 在 ``count == baseline`` 时 ``exit 0``、``count > baseline`` 时
   ``exit 1`` 并给出文件位置、``count < baseline`` 时 ``exit 0`` 并
   warn 提示降 baseline；
4. 当前 ``static/css/main.css`` 实际硬编码数 == 脚本默认 baseline，
   保证 R66 commit 时刻的 baseline 数字与代码同步。

这是「护栏脚本本身的测试」，对应 R64/R65 的「修复结果测试」。
"""

from __future__ import annotations

import io
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"

sys.path.insert(0, str(SCRIPTS_DIR))
import check_brand_color_consistency as guard  # ty: ignore[unresolved-import]


class TestStripCssComments(unittest.TestCase):
    """``strip_css_comments`` 必须移除所有 ``/* ... */`` 块。"""

    def test_single_line_block(self) -> None:
        src = ".x { color: red; } /* comment */ .y { color: blue; }"
        out = guard.strip_css_comments(src)
        self.assertNotIn("comment", out)
        self.assertIn(".x", out)
        self.assertIn(".y", out)

    def test_multiline_block(self) -> None:
        src = "/*\n * 多行\n * 注释\n */\n.x { color: red; }"
        out = guard.strip_css_comments(src)
        self.assertNotIn("多行", out)
        self.assertIn(".x", out)

    def test_strips_rgba_inside_comment(self) -> None:
        """关键场景：R65 commit 在注释里写了 ``rgba(0, 122, 255, X)``。"""
        src = "/* 说明 rgba(0, 122, 255, 0.3) 是 iOS 蓝 */\n.x { color: red; }"
        out = guard.strip_css_comments(src)
        # 注释里那段 rgba 引用被剥掉
        self.assertNotIn("rgba(0, 122, 255", out)

    def test_preserves_rgba_in_actual_rule(self) -> None:
        src = "/* note */ .x { color: rgba(0, 122, 255, 0.3); }"
        out = guard.strip_css_comments(src)
        self.assertIn("rgba(0, 122, 255, 0.3)", out)

    def test_empty_input(self) -> None:
        self.assertEqual(guard.strip_css_comments(""), "")


class TestCountIosBlue(unittest.TestCase):
    """``count_ios_blue`` 容忍多种 RGB 字面量写法。"""

    def test_basic_rgba(self) -> None:
        src = "color: rgba(0, 122, 255, 0.3);"
        self.assertEqual(guard.count_ios_blue(src), 1)

    def test_basic_rgb(self) -> None:
        src = "color: rgb(0, 122, 255);"
        self.assertEqual(guard.count_ios_blue(src), 1)

    def test_extra_whitespace(self) -> None:
        """``rgba(  0,122 , 255  ,0.3)`` 也应该被识别。"""
        src = "color: rgba(  0,122 , 255  ,0.3);"
        self.assertEqual(guard.count_ios_blue(src), 1)

    def test_multiple_occurrences(self) -> None:
        src = (
            "a { color: rgba(0, 122, 255, 0.5); } "
            "b { color: rgb(0,122,255); border: 1px solid rgba(0, 122, 255, 0.3); }"
        )
        self.assertEqual(guard.count_ios_blue(src), 3)

    def test_does_not_match_other_blues(self) -> None:
        """``rgba(0, 122, 254, ...)`` / ``rgba(1, 122, 255, ...)`` 不算。"""
        src = "rgba(0, 122, 254, 0.3); rgba(1, 122, 255, 0.3)"
        self.assertEqual(guard.count_ios_blue(src), 0)

    def test_does_not_match_zero_padded(self) -> None:
        """正则 ``\\b`` 边界：``rgba(0, 122, 2550)`` 不应误匹配。"""
        src = "rgba(0, 122, 2550)"
        self.assertEqual(guard.count_ios_blue(src), 0)


class TestFindIosBlueLocations(unittest.TestCase):
    """``find_ios_blue_locations`` 返回行号 + 行内容供错误信息使用。"""

    def test_returns_line_number_and_content(self) -> None:
        src = "first line\n.x { color: rgba(0, 122, 255, 0.3); }\nthird line\n"
        locs = guard.find_ios_blue_locations(src)
        self.assertEqual(len(locs), 1)
        lineno, line = locs[0]
        self.assertEqual(lineno, 2)
        self.assertIn("rgba(0, 122, 255, 0.3)", line)

    def test_empty_when_no_match(self) -> None:
        self.assertEqual(guard.find_ios_blue_locations(".x { color: red; }"), [])


class TestCliExitCodes(unittest.TestCase):
    """CLI ``main()`` 入口的退出码语义。"""

    def setUp(self) -> None:
        self.css_dir = REPO_ROOT / "static" / "css"
        self.assertTrue(
            self.css_dir.exists(),
            "static/css 必须存在才能跑这个测试。",
        )

    def _run_main(self, *argv: str) -> tuple[int, str, str]:
        out_buf, err_buf = io.StringIO(), io.StringIO()
        with redirect_stdout(out_buf), redirect_stderr(err_buf):
            code = guard.main(list(argv))
        return code, out_buf.getvalue(), err_buf.getvalue()

    def test_exit_0_at_baseline(self) -> None:
        """count == baseline → exit 0 + ✅ 输出。"""
        # 用一个**临时**目录跑，避免脚本相对路径耦合
        code, out, err = self._run_main(
            "--root",
            str(self.css_dir),
            "--baseline",
            str(guard.DEFAULT_BASELINE),
        )
        self.assertEqual(code, 0, f"exit code 应为 0，实际 {code}\nstderr: {err}")
        self.assertIn("✅", out, f"应该有成功提示\nstdout: {out}")

    def test_exit_1_when_above_baseline(self) -> None:
        """count > baseline → exit 1 + ❌ + 文件列表。"""
        code, _out, err = self._run_main(
            "--root",
            str(self.css_dir),
            "--baseline",
            "0",  # 极低 baseline 强制触发 fail
        )
        self.assertEqual(code, 1, "exit code 应为 1（超过 baseline）")
        self.assertIn("❌", err)
        self.assertIn("baseline", err)

    def test_exit_0_when_below_baseline_with_warn(self) -> None:
        """count < baseline → exit 0 + ℹ️ 提示降 baseline。"""
        code, out, _err = self._run_main(
            "--root",
            str(self.css_dir),
            "--baseline",
            str(guard.DEFAULT_BASELINE + 100),
        )
        self.assertEqual(code, 0, "exit code 应为 0（小于 baseline 不算 fail）")
        self.assertIn("ℹ️", out)

    def test_exit_2_on_missing_root(self) -> None:
        code, _out, err = self._run_main(
            "--root",
            "/nonexistent/path/__r66_test__",
        )
        self.assertEqual(code, 2)
        self.assertIn("不存在", err)

    def test_quiet_mode_suppresses_success_output(self) -> None:
        """``--quiet`` 在通过时不输出（适合 pre-commit）。"""
        code, out, _err = self._run_main(
            "--root",
            str(self.css_dir),
            "--baseline",
            str(guard.DEFAULT_BASELINE),
            "--quiet",
        )
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), "")


class TestBaselineMatchesActualCount(unittest.TestCase):
    """关键回归守护：脚本默认 baseline 必须与当前 main.css 实际数同步。

    若有人改动 ``main.css`` 但忘了同步 ``DEFAULT_BASELINE``：
    * 增加硬编码 → ``test_exit_0_at_baseline`` 仍然过（因为 baseline 也增了
      但脚本 fail）—— 不会被 catch；
    * 减少硬编码 → 脚本退化到 ``ℹ️`` 模式，不 fail，但 baseline 数字
      与现实脱节，下次再有人新增就感觉不到压力。
    本测试直接断言 ``DEFAULT_BASELINE == 实际扫描数``，强迫两者必须
    一起改、一起 commit。
    """

    def test_default_baseline_matches_main_css_count(self) -> None:
        css_dir = REPO_ROOT / "static" / "css"
        total, _per_file = guard.scan_css_files(css_dir)
        self.assertEqual(
            total,
            guard.DEFAULT_BASELINE,
            f"DEFAULT_BASELINE ({guard.DEFAULT_BASELINE}) 与实际扫描数 "
            f"({total}) 不一致。请：\n"
            f"  - 若新增了 iOS 蓝硬编码：先重构成 var() 或 Orange override；\n"
            f"  - 若重构去掉了硬编码：把 scripts/check_brand_color_consistency.py "
            f"的 DEFAULT_BASELINE 改成 {total} 锁定本次进度。",
        )


class TestPreCommitHookRegistered(unittest.TestCase):
    """守护：``.pre-commit-config.yaml`` 必须把 R66 hook 接进来。

    若有人因某个原因移除了这个 hook，本测试 fail —— 不让护栏静默
    退化。
    """

    def test_hook_id_present_in_config(self) -> None:
        config = REPO_ROOT / ".pre-commit-config.yaml"
        self.assertTrue(config.exists(), ".pre-commit-config.yaml 必须存在")
        text = config.read_text(encoding="utf-8")
        self.assertIn(
            "check-brand-color-consistency",
            text,
            "R66 在 .pre-commit-config.yaml 注册的 hook id 缺失。",
        )
        self.assertIn(
            "scripts/check_brand_color_consistency.py",
            text,
            "R66 hook entry 必须指向 scripts/check_brand_color_consistency.py。",
        )


if __name__ == "__main__":
    # patch 避免 pre-commit 测试在 isolated 环境里找不到 sys.path 注入
    with patch.dict(sys.modules, {"check_brand_color_consistency": guard}):
        unittest.main()
