"""R66 / R99 / R109：CSS 品牌色硬编码漂移检测器测试。

锁定 ``scripts/check_brand_color_consistency.py`` 的核心行为：

1. ``strip_css_comments`` 正确剔除 ``/* ... */`` 块（防止注释里的
   ``rgba(0, 122, 255, X)`` 文档引用被误计为样式硬编码）；
2. ``count_ios_blue`` 与 ``find_ios_blue_locations`` 容忍 rgba/rgb、
   任意空白、不同 alpha 通道；
3. CLI 在 ``count == baseline`` 时 ``exit 0``、``count > baseline`` 时
   ``exit 1`` 并给出文件位置、``count < baseline`` 时 ``exit 0`` 并
   warn 提示降 baseline；
4. 当前 ``static/css/main.css`` 实际硬编码数 == 脚本默认 baseline，
   保证 R66/R99/R109 commit 时刻的 baseline 数字与代码同步；
5. R109：hex 端正则扩展为 union ``#007aff|#0a84ff|#0056cc`` 后，
   三个 variant 都被识别、能各自单独命中、且不会误命中到其他相似
   hex 值（如 ``#007abf``、``#0a85ff``、``#0156cc``）。

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


class TestCountIosBlueHexR99(unittest.TestCase):
    """R99：``count_ios_blue_hex`` 容忍 hex 形式 ``#007aff`` 的多种写法。"""

    def test_basic_lowercase(self) -> None:
        src = "color: #007aff;"
        self.assertEqual(guard.count_ios_blue_hex(src), 1)

    def test_basic_uppercase(self) -> None:
        """case-insensitive：``#007AFF`` 同样命中。"""
        src = "color: #007AFF;"
        self.assertEqual(guard.count_ios_blue_hex(src), 1)

    def test_mixed_case(self) -> None:
        src = "color: #007AfF;"
        self.assertEqual(guard.count_ios_blue_hex(src), 1)

    def test_multiple_occurrences(self) -> None:
        src = (
            "a { color: #007aff; } "
            "b { border: 1px solid #007aff; background: #007AFF; }"
        )
        self.assertEqual(guard.count_ios_blue_hex(src), 3)

    def test_does_not_match_other_hex(self) -> None:
        """``#007abf`` / ``#107aff`` 不应误命中。"""
        src = "color: #007abf; border-color: #107aff;"
        self.assertEqual(guard.count_ios_blue_hex(src), 0)

    def test_word_boundary(self) -> None:
        """``\\b`` 边界：``#007affab`` 不应命中（虽然 CSS 不允许这种扩展）。"""
        src = "color: #007affab;"
        self.assertEqual(guard.count_ios_blue_hex(src), 0)

    def test_does_not_match_brand_purple_or_orange(self) -> None:
        """品牌色 ``#a855f7`` / ``#d97757`` 不能误命中——它们不是 iOS 蓝。"""
        src = ":root { --brand-accent: #a855f7; --brand-light-accent: #d97757; }"
        self.assertEqual(guard.count_ios_blue_hex(src), 0)


class TestFindIosBlueHexLocationsR99(unittest.TestCase):
    """R99：``find_ios_blue_hex_locations`` 返回行号 + 行内容。"""

    def test_returns_line_number_and_content(self) -> None:
        src = "first line\n.x { color: #007aff; }\nthird line\n"
        locs = guard.find_ios_blue_hex_locations(src)
        self.assertEqual(len(locs), 1)
        lineno, line = locs[0]
        self.assertEqual(lineno, 2)
        self.assertIn("#007aff", line)

    def test_empty_when_no_match(self) -> None:
        self.assertEqual(
            guard.find_ios_blue_hex_locations(".x { color: red; }"),
            [],
        )


class TestIosBlueHexFamilyR109(unittest.TestCase):
    """R109：iOS 蓝家族扩展——``#007aff`` (light) / ``#0a84ff`` (dark) /
    ``#0056cc`` (darker hover) 三个 variant 都属同一品牌漂移源，
    合并到一条 hex baseline 9（= 7 + 1 + 1）。

    历史教训：R99 设计时只覆盖了 ``#007aff``，``main.css::1020``
    ``.btn-primary-enabled`` 直接硬编码 ``#0a84ff`` 与 ``::3982``
    ``.btn-primary:hover`` 直接硬编码 ``#0056cc``——两处都是同性质的
    iOS 蓝品牌漂移源（light mode 显示成 iOS 蓝，与 ``#a855f7`` /
    ``#d97757`` 品牌色不一致），但 R66/R99 防线完全没盖到。R109 用
    union 正则把三个 variant 合并锁定。
    """

    def test_0a84ff_dark_mode_systemblue(self) -> None:
        """R109：``#0a84ff`` (iOS 13+ dark systemBlue) 必须命中。"""
        src = ".btn-primary-enabled { background-color: #0a84ff; }"
        self.assertEqual(guard.count_ios_blue_hex(src), 1)

    def test_0a84ff_uppercase(self) -> None:
        """case-insensitive：``#0A84FF`` 同样命中。"""
        src = "color: #0A84FF;"
        self.assertEqual(guard.count_ios_blue_hex(src), 1)

    def test_0056cc_darker_hover(self) -> None:
        """R109：``#0056cc`` (iOS 蓝 darker hover variant) 必须命中。"""
        src = ".btn-primary:hover { background: #0056cc; }"
        self.assertEqual(guard.count_ios_blue_hex(src), 1)

    def test_0056cc_uppercase(self) -> None:
        src = "background: #0056CC;"
        self.assertEqual(guard.count_ios_blue_hex(src), 1)

    def test_all_three_variants_together(self) -> None:
        """三个 variant 同时出现，count = 3。"""
        src = (
            "a { color: #007aff; } "
            "b { background: #0a84ff; } "
            "c { background: #0056cc; }"
        )
        self.assertEqual(guard.count_ios_blue_hex(src), 3)

    def test_does_not_match_near_neighbors(self) -> None:
        """正则 ``\\b`` 边界 + union 精确匹配：相邻 hex 不应误命中。"""
        src = (
            "color: #0a85ff;"  # 末位差 1
            "border: 1px solid #0156cc;"  # 首位差 1
            "background: #0a84fe;"  # 末位差 1
            "color: #1056cc;"  # 首位差 1
        )
        self.assertEqual(guard.count_ios_blue_hex(src), 0)

    def test_does_not_match_brand_palette(self) -> None:
        """品牌色 ``#a855f7`` (紫) / ``#d97757`` (橙) 严格不应误命中
        到三个 variant 中任意一个——即使大小写混合。
        """
        src = (
            ":root { --brand-accent: #a855f7; --brand-light-accent: #d97757; }"
            ".x { color: #A855F7; background: #D97757; }"
        )
        self.assertEqual(guard.count_ios_blue_hex(src), 0)

    def test_find_locations_returns_all_variants(self) -> None:
        """``find_ios_blue_hex_locations`` 三个 variant 都返回行号。"""
        src = (
            "line1\n"
            ".a { color: #007aff; }\n"
            ".b { background: #0a84ff; }\n"
            ".c { background: #0056cc; }\n"
            "lastline\n"
        )
        locs = guard.find_ios_blue_hex_locations(src)
        self.assertEqual(len(locs), 3)
        line_numbers = [lineno for lineno, _line in locs]
        self.assertEqual(line_numbers, [2, 3, 4])

    def test_actual_main_css_has_each_variant(self) -> None:
        """端到端：``main.css`` 剥注释后必须能扫到三个 variant 各自的
        预期数量（R109 baseline 9 = 7 + 1 + 1 的拆解必须真实存在）。

        反向验证：若某天有 PR 把 ``#0a84ff`` 重构掉了但没同步把
        ``DEFAULT_HEX_BASELINE`` 从 9 降到 8，会同时被
        ``test_default_hex_baseline_matches_main_css_count`` 抓到（实际
        数 8 != baseline 9）；但本测试**直接**断言变体数量分布，给出
        更精确的诊断信息（"是哪个 variant 变了"）。
        """
        css_path = (
            REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "css" / "main.css"
        )
        self.assertTrue(css_path.exists(), "main.css 必须存在")
        raw = css_path.read_text(encoding="utf-8")
        stripped = guard.strip_css_comments(raw)

        import re as _re

        count_007aff = len(_re.findall(r"#007aff\b", stripped, _re.IGNORECASE))
        count_0a84ff = len(_re.findall(r"#0a84ff\b", stripped, _re.IGNORECASE))
        count_0056cc = len(_re.findall(r"#0056cc\b", stripped, _re.IGNORECASE))
        count_0045a0 = len(_re.findall(r"#0045a0\b", stripped, _re.IGNORECASE))

        self.assertEqual(
            count_007aff,
            6,
            f"R99/R109/R259h 锁定 ``#007aff`` 应为 6 处实际硬编码"
            f"（剥注释后；cycle-5 Track D R259h 把 ``.btn-primary`` 默认背景"
            f"从 ``#007aff`` 升级到 ``#0056cc`` 修 WCAG 1.4.3 AA-normal "
            f"FAIL，故计数 7→6），实际 {count_007aff}。"
            f"若变化，请同步 R109 docstring 的拆解数字。",
        )
        self.assertEqual(
            count_0045a0,
            1,
            f"R259h 锁定 ``#0045a0`` 应为 1 处（``.btn-primary:hover`` 新背景，"
            f"contrast 8.90:1 AAA-ish），实际 {count_0045a0}。",
        )
        self.assertEqual(
            count_0a84ff,
            1,
            f"R109 锁定 ``#0a84ff`` 应为 1 处（``.btn-primary-enabled`` 背景），实际 {count_0a84ff}。"
            f"若被重构掉了，请把 ``DEFAULT_HEX_BASELINE`` 从 9 降到 8。",
        )
        self.assertEqual(
            count_0056cc,
            1,
            f"R109 锁定 ``#0056cc`` 应为 1 处（``.btn-primary:hover`` 背景），实际 {count_0056cc}。"
            f"若被重构掉了，请把 ``DEFAULT_HEX_BASELINE`` 从 9 降到 8。",
        )
        self.assertEqual(
            count_007aff + count_0a84ff + count_0056cc + count_0045a0,
            guard.DEFAULT_HEX_BASELINE,
            f"四个 variant 总和必须 == DEFAULT_HEX_BASELINE "
            f"({guard.DEFAULT_HEX_BASELINE})；cycle-5 R259h 把 #0045a0 "
            f"加入 iOS 蓝家族 baseline，总数仍为 9 (6+1+1+1)。",
        )


class TestScanCssFilesReturnsBothFormsR99(unittest.TestCase):
    """R99：``scan_css_files`` 必须**同时**返回 rgba decimal 和 hex 两种
    形式的扫描结果。R99 之前函数签名是 ``(rgba_total, rgba_per_file)``，
    R99 改成 ``(rgba_total, rgba_per_file, hex_total, hex_per_file)``——
    若有人误改回 2-tuple 这个测试会立刻 fail。"""

    def test_returns_4_tuple(self) -> None:
        css_dir = REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "css"
        result = guard.scan_css_files(css_dir)
        self.assertEqual(
            len(result),
            4,
            "scan_css_files 必须返回 4-tuple "
            "(rgba_total, rgba_per_file, hex_total, hex_per_file)。R99 之前的 "
            "2-tuple 签名漏掉了 hex 形式 ``#007aff`` 的同色硬编码扫描结果。",
        )
        rgba_total, rgba_per_file, hex_total, hex_per_file = result
        self.assertIsInstance(rgba_total, int)
        self.assertIsInstance(rgba_per_file, dict)
        self.assertIsInstance(hex_total, int)
        self.assertIsInstance(hex_per_file, dict)

    def test_hex_form_is_actually_scanned(self) -> None:
        """端到端：构造内存 fixture 验证 ``#007aff`` 真的会被扫到。"""
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            css_path = Path(tmpdir) / "fixture.css"
            css_path.write_text(
                ".a { color: #007aff; }\n"
                ".b { background: rgba(0, 122, 255, 0.5); }\n"
                "/* doc 引用 #007aff 不计 */\n",
                encoding="utf-8",
            )
            rgba_total, _rgba_pf, hex_total, _hex_pf = guard.scan_css_files(
                Path(tmpdir)
            )
            self.assertEqual(rgba_total, 1, "rgba decimal 应当扫到 1 处")
            self.assertEqual(
                hex_total,
                1,
                "hex 形式应当扫到 1 处（注释里的 #007aff 已被剥）",
            )


class TestCliExitCodes(unittest.TestCase):
    """CLI ``main()`` 入口的退出码语义。"""

    def setUp(self) -> None:
        self.css_dir = REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "css"
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

    若有人改动 ``main.css`` 但忘了同步 ``DEFAULT_BASELINE`` /
    ``DEFAULT_HEX_BASELINE``：
    * 增加硬编码 → ``test_exit_0_at_baseline`` 仍然过（因为 baseline 也增了
      但脚本 fail）—— 不会被 catch；
    * 减少硬编码 → 脚本退化到 ``ℹ️`` 模式，不 fail，但 baseline 数字
      与现实脱节，下次再有人新增就感觉不到压力。
    本测试直接断言 ``baseline == 实际扫描数``，强迫两者必须一起改、一起
    commit。R99 加 hex 形式 ``#007aff`` 的并行断言（与 rgba decimal 形式
    各自独立 baseline）。
    """

    def test_default_baseline_matches_main_css_count(self) -> None:
        css_dir = REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "css"
        rgba_total, _rgba_per_file, hex_total, _hex_per_file = guard.scan_css_files(
            css_dir
        )
        self.assertEqual(
            rgba_total,
            guard.DEFAULT_BASELINE,
            f"DEFAULT_BASELINE ({guard.DEFAULT_BASELINE}) 与实际 rgba decimal "
            f"扫描数 ({rgba_total}) 不一致。请：\n"
            f"  - 若新增了 ``rgba(0, 122, 255, X)``：先重构成 var() 或 "
            f"Orange override；\n"
            f"  - 若重构去掉了：把 scripts/check_brand_color_consistency.py "
            f"的 DEFAULT_BASELINE 改成 {rgba_total} 锁定本次进度。",
        )

    def test_default_hex_baseline_matches_main_css_count(self) -> None:
        """R99：hex 形式 ``#007aff`` 的同款 baseline 锁定。"""
        css_dir = REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "css"
        _rgba_total, _rgba_per_file, hex_total, _hex_per_file = guard.scan_css_files(
            css_dir
        )
        self.assertEqual(
            hex_total,
            guard.DEFAULT_HEX_BASELINE,
            f"DEFAULT_HEX_BASELINE ({guard.DEFAULT_HEX_BASELINE}) 与实际 hex "
            f"扫描数 ({hex_total}) 不一致。请：\n"
            f"  - 若新增了 ``#007aff``：先重构成 var() 或 Orange override "
            f"（hex 形式与 rgba decimal 形式同色，对 light mode 视觉漂移"
            f"贡献相同）；\n"
            f"  - 若重构去掉了：把 scripts/check_brand_color_consistency.py "
            f"的 DEFAULT_HEX_BASELINE 改成 {hex_total} 锁定本次进度。",
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


class TestDefaultsPointAtRealLocations(unittest.TestCase):
    """R88 防回归：``DEFAULT_ROOT`` 与 hook ``files`` glob 必须指向
    实际存在的目录 / 至少能匹配到该目录下的真实 CSS 文件。

    历史教训：R76 把 ``static/`` 从仓库根挪进 ``src/ai_intervention_agent/``
    包内（PyPA src/ 布局），但 R66 留下的两个默认值都没跟着改：

    1. ``scripts/check_brand_color_consistency.py::DEFAULT_ROOT = "static/css"``
       —— 当 hook 真的被触发（无 ``--root``）时，脚本会以 exit 2 报
       "扫描根目录不存在 → static/css" 失败。
    2. ``.pre-commit-config.yaml`` 的 ``files: ^static/css/.*\\.css$``
       —— 在新布局下不 match 任何文件，hook 永远不会被 pre-commit
       触发（最坏的"silent skip"）。

    本测试三个断言保证这两个默认值与现实保持一致：
    """

    def test_default_root_directory_exists(self) -> None:
        """``DEFAULT_ROOT`` 解析后必须是真实存在的目录。"""
        root_path = REPO_ROOT / guard.DEFAULT_ROOT
        self.assertTrue(
            root_path.exists() and root_path.is_dir(),
            f"DEFAULT_ROOT={guard.DEFAULT_ROOT!r} 解析后指向不存在的目录 "
            f"{root_path}。这意味着 pre-commit hook 真的触发时会以 exit 2 "
            f"失败（参见 R88 修复）。如果有意改动 CSS 目录布局，请同步把 "
            f"``DEFAULT_ROOT`` 改成新位置（再把 .pre-commit-config.yaml "
            f"的 ``files`` glob 改成同步前缀）。",
        )

    def test_default_root_contains_at_least_one_css_file(self) -> None:
        """``DEFAULT_ROOT`` 必须至少能扫到一个 ``.css``，否则 baseline
        永远是 0、护栏失去意义。
        """
        root_path = REPO_ROOT / guard.DEFAULT_ROOT
        css_files = list(root_path.glob("*.css"))
        self.assertGreater(
            len(css_files),
            0,
            f"DEFAULT_ROOT={guard.DEFAULT_ROOT!r} 下找不到 .css 文件 "
            f"({root_path})；R66 baseline guard 实际上空跑。",
        )

    def test_pre_commit_files_glob_matches_default_root(self) -> None:
        """``.pre-commit-config.yaml`` 的 ``files`` glob 必须以
        ``DEFAULT_ROOT`` 作为前缀（normalise / 转义后比较），否则两条
        路径会再次漂移分裂（R88 的两个 silent broken 修复必须同步）。
        """
        config_text = (REPO_ROOT / ".pre-commit-config.yaml").read_text(
            encoding="utf-8"
        )
        expected_prefix = f"^{guard.DEFAULT_ROOT}/"
        self.assertIn(
            expected_prefix,
            config_text,
            f"找不到 ``files: {expected_prefix}...`` 风格的 hook 配置。"
            f" R88 修复后 ``.pre-commit-config.yaml`` 与脚本默认 "
            f"``DEFAULT_ROOT={guard.DEFAULT_ROOT!r}`` 必须一起以同一个前缀指向 "
            f"src/ 布局；任何一边改了，另一边必须同步改。",
        )


if __name__ == "__main__":
    # patch 避免 pre-commit 测试在 isolated 环境里找不到 sys.path 注入
    with patch.dict(sys.modules, {"check_brand_color_consistency": guard}):
        unittest.main()
