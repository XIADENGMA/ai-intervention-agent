"""防回归：``docs/api{,.zh-CN}/index.md`` 的 Quick navigation 必须覆盖每一个 ``MODULES_TO_DOCUMENT``。

历史背景
---------
v1.5.x 早期 ``scripts/generate_docs.py::MODULES_TO_DOCUMENT`` 列了 14 个
模块（config_manager / config_utils / exceptions / i18n / protocol /
state_machine / server_config / shared_types / notification_manager /
notification_models / **notification_providers** / task_queue /
file_validator / enhanced_logging），双语 API index 的 ``## Modules``
也忠实列了 14 项；但 ``### Core modules`` + ``### Utility modules``
分组只覆盖 13 项 —— **``notification_providers`` 在 Quick navigation
里失踪了**。它的描述在 ``generate_index`` 函数里被忘记加，导致用户
在 README 跳到 API index 想了解通知后端时，分组导航把它"藏"在底下
``## Modules`` 平铺列表里。

修复 + 引入分组常量 ``QUICK_NAV_CORE`` / ``QUICK_NAV_UTILITY`` +
``_assert_quick_nav_covers_all_modules`` fail-fast 校验。本测试再加一
道**外部**回归位：

  - 锁住 ``MODULES_TO_DOCUMENT`` 的模块名集合 == Quick navigation 分组
    并集（防止未来加 ``audio.py`` / ``ssml.py`` 时只动 MODULES_TO_DOCUMENT
    不动分组常量）；
  - 锁住实际生成的 ``docs/api/index.md`` / ``docs/api.zh-CN/index.md``
    都把 14 个模块完整渲染到 Quick navigation 中（端到端断言文件本身，
    不仅仅断言生成器内部状态）；
  - 锁住分组成员名拼写（``notification_providers`` 不写成
    ``notification_provider`` 之类的拼写漂移）。

设计原则
--------
- 文件解析用最简正则（``- **<name>**: ...``）+ ``### Core/Utility`` 段落
  锚定，不引入 markdown AST 依赖；
- 双语并行——单纯把 ``Core modules`` ↔ ``核心模块`` 两个标题列表别名化
  即可；
- 与 ``test_generate_docs_*`` 现有测试互补，那些测试关心 generator 输出
  的格式细节（行尾、围栏、emphasis），本测试关心 *清单完整性*。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.generate_docs import (
    MODULES_TO_DOCUMENT,
    QUICK_NAV_CORE,
    QUICK_NAV_UTILITY,
    _assert_quick_nav_covers_all_modules,
)

DOC_PATHS = {
    "en": REPO_ROOT / "docs" / "api" / "index.md",
    "zh-CN": REPO_ROOT / "docs" / "api.zh-CN" / "index.md",
}

# Section heading 起始锚点：英文 `### Core modules` / `### Utility modules`
# 中文 `### 核心模块` / `### 工具模块`。
SECTION_TITLES = {
    "en": {"core": "### Core modules", "utility": "### Utility modules"},
    "zh-CN": {"core": "### 核心模块", "utility": "### 工具模块"},
}


def _parse_quick_nav_modules(doc_path: Path, lang: str) -> tuple[set[str], set[str]]:
    """从一份 API index 抽出 Quick navigation 双段中的 module 名。

    返回 ``(core_set, utility_set)``。
    """
    text = doc_path.read_text(encoding="utf-8")
    titles = SECTION_TITLES[lang]

    def _between(start_title: str, end_title: str | None) -> str:
        start = text.find(start_title)
        if start < 0:
            return ""
        start_body = start + len(start_title)
        if end_title is None:
            end = len(text)
        else:
            end = text.find(end_title, start_body)
            if end < 0:
                end = len(text)
        return text[start_body:end]

    core_body = _between(titles["core"], titles["utility"])
    util_body = _between(titles["utility"], "---")

    def _module_names(body: str) -> set[str]:
        names = set()
        for line in body.splitlines():
            stripped = line.strip()
            if not stripped.startswith("- **"):
                continue
            try:
                name = stripped.split("- **", 1)[1].split("**", 1)[0]
            except IndexError:
                continue
            if name:
                names.add(name)
        return names

    return _module_names(core_body), _module_names(util_body)


class TestGeneratorInvariant(unittest.TestCase):
    """守 ``generate_docs.py`` 内部不变量 —— Quick nav 分组并集 == MODULES_TO_DOCUMENT。"""

    def test_quick_nav_groups_cover_all_documented_modules(self) -> None:
        declared = {Path(m).stem for m in MODULES_TO_DOCUMENT}
        in_nav = set(QUICK_NAV_CORE) | set(QUICK_NAV_UTILITY)
        self.assertEqual(
            declared,
            in_nav,
            f"MODULES_TO_DOCUMENT vs Quick nav drift:\n"
            f"  in MODULES_TO_DOCUMENT but not in nav: "
            f"{sorted(declared - in_nav)}\n"
            f"  in nav but not in MODULES_TO_DOCUMENT: "
            f"{sorted(in_nav - declared)}",
        )

    def test_no_overlap_between_core_and_utility(self) -> None:
        # Core 与 Utility 互斥：一个模块只能在一个分类里出现一次。
        overlap = set(QUICK_NAV_CORE) & set(QUICK_NAV_UTILITY)
        self.assertFalse(
            overlap,
            f"these modules are listed in BOTH QUICK_NAV_CORE and "
            f"QUICK_NAV_UTILITY (split-decision; pick one): {sorted(overlap)}",
        )

    def test_assert_helper_passes_on_actual_module_list(self) -> None:
        # 直接调用 fail-fast helper，确认实际模块清单本身就是合法的；
        # 这一行其实就是 generate_index 入口跑的检查。
        _assert_quick_nav_covers_all_modules(MODULES_TO_DOCUMENT)

    def test_assert_helper_raises_on_missing_module(self) -> None:
        # 注入一个 generate_index **不**会渲染、但被声明为 documented 的模块，
        # helper 必须 SystemExit。
        bogus = [*MODULES_TO_DOCUMENT, "nonexistent_future_module.py"]
        with self.assertRaises(SystemExit) as ctx:
            _assert_quick_nav_covers_all_modules(bogus)
        self.assertIn("nonexistent_future_module", str(ctx.exception))

    def test_assert_helper_raises_on_extra_in_nav(self) -> None:
        # 同样，分组里出现了一个 MODULES_TO_DOCUMENT 没有的模块也要触发。
        # 由于 QUICK_NAV_CORE / QUICK_NAV_UTILITY 是模块全局常量，构造 reduced
        # MODULES_TO_DOCUMENT（把 notification_providers 拿掉）来模拟这种漂移。
        reduced = [
            m for m in MODULES_TO_DOCUMENT if Path(m).stem != "notification_providers"
        ]
        with self.assertRaises(SystemExit) as ctx:
            _assert_quick_nav_covers_all_modules(reduced)
        self.assertIn("notification_providers", str(ctx.exception))


class TestRenderedIndexCoverage(unittest.TestCase):
    """守住 *渲染后* 文件的覆盖完整性 —— 端到端兜底。"""

    def setUp(self) -> None:
        self.declared = {Path(m).stem for m in MODULES_TO_DOCUMENT}

    def _check(self, lang: str) -> None:
        doc_path = DOC_PATHS[lang]
        self.assertTrue(doc_path.exists(), f"missing API index: {doc_path}")

        core, utility = _parse_quick_nav_modules(doc_path, lang)
        nav_total = core | utility

        missing = self.declared - nav_total
        extra = nav_total - self.declared
        self.assertFalse(
            missing,
            f"{doc_path.relative_to(REPO_ROOT)}: Quick navigation does NOT mention "
            f"these modules (regenerate via `make docs`): {sorted(missing)}",
        )
        self.assertFalse(
            extra,
            f"{doc_path.relative_to(REPO_ROOT)}: Quick navigation lists modules "
            f"that are no longer in MODULES_TO_DOCUMENT (stale entries; "
            f"regenerate via `make docs`): {sorted(extra)}",
        )

        # 且 core/utility 各自至少非空（防止 generate_index 不小心把所有模块都
        # 推进 Utility 一类、Core 段空白这种"兜底但伤可读性"的 bug）
        self.assertTrue(core, f"{doc_path.name}: Core modules section is empty")
        self.assertTrue(utility, f"{doc_path.name}: Utility modules section is empty")

    def test_english_index_covers_all_modules(self) -> None:
        self._check("en")

    def test_chinese_index_covers_all_modules(self) -> None:
        self._check("zh-CN")


class TestParserSelfChecks(unittest.TestCase):
    """守住 _parse_quick_nav_modules 自身的契约 —— 重构 helper 时不让本测试变弱。"""

    def test_parser_recovers_known_anchors_en(self) -> None:
        core, utility = _parse_quick_nav_modules(DOC_PATHS["en"], "en")
        # 几个 anchor，未来无论怎么调整描述文案，这些模块名必须仍然出现
        self.assertIn("config_manager", core)
        self.assertIn("notification_manager", core)
        self.assertIn("notification_providers", utility)
        self.assertIn("enhanced_logging", utility)

    def test_parser_recovers_known_anchors_zh(self) -> None:
        core, utility = _parse_quick_nav_modules(DOC_PATHS["zh-CN"], "zh-CN")
        self.assertIn("config_manager", core)
        self.assertIn("notification_manager", core)
        self.assertIn("notification_providers", utility)
        self.assertIn("enhanced_logging", utility)


if __name__ == "__main__":
    unittest.main()
