"""R210 / Cycle 10 · F-205-1 · `AIIA_SSE_SCHEMA_VALIDATE` env-var docs tests。

设计目标
========

R205 (cycle 9) 引入 ``AIIA_SSE_SCHEMA_VALIDATE`` env var toggle 但
docs/configuration.md 没有同步 — fresh contributor / 运维 grep ``AIIA_``
环境变量找不到说明。R210 在 docs/configuration.{md,zh-CN.md} §"运维 /
调试 env vars" 章节加完整说明（off/warn/strict 三 mode + sticky 读
取 + 计数器暴露路径 + 失败 fall-back 等）。

本测试守护**结构性契约**:

1. 双语 lockstep — 中英都含 ``AIIA_SSE_SCHEMA_VALIDATE``;
2. 三 mode 名都出现 (off / warn / strict) - 关键 contract;
3. 提及 R205 / R207 / sticky / Twelve-Factor / omit-when-off 等关
   键设计取舍 keyword (让 ops grep 能定位完整背景);
4. 提及计数器暴露的两个路径 (stats JSON + Prom metric)。

沿用 R185 / R206 / R209 同款静态字符串匹配 + 双语 lockstep 模式。

测试覆盖 (6 cases / 2 invariant class)
=======================================

1. **TestEnglishDocsHasEnvVarSection** (3): docs/configuration.md
   含 env var 名 + 3 mode + R205 + R207 + sticky + omit-when-off
2. **TestChineseDocsHasEnvVarSection** (3): 同上 zh-CN 镜像

总计 6 cases。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


_DOC_EN = REPO_ROOT / "docs" / "configuration.md"
_DOC_ZH = REPO_ROOT / "docs" / "configuration.zh-CN.md"


class TestEnglishDocsHasEnvVarSection(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = _DOC_EN.read_text(encoding="utf-8")

    def test_env_var_name_present(self) -> None:
        self.assertIn(
            "AIIA_SSE_SCHEMA_VALIDATE",
            self.text,
            "docs/configuration.md 必须含 AIIA_SSE_SCHEMA_VALIDATE 名称",
        )

    def test_all_three_modes_documented(self) -> None:
        """三 mode 名 (off / warn / strict) 必须都出现在 docs — 这是
        R205 的核心 contract，缺一个 mode 用户就不知道有该选项。"""
        for mode in ("off", "warn", "strict"):
            self.assertIn(
                f"`{mode}`",
                self.text,
                f"docs/configuration.md 必须 backtick 标记 mode {mode!r}",
            )

    def test_key_design_keywords_present(self) -> None:
        """关键设计取舍 keyword 必须出现在 docs — 让 fresh contributor /
        ops grep 能定位完整背景 (R205 / R207 / sticky / omit-when-off)。"""
        for needle in (
            "R205",  # 起源 cycle
            "R207",  # Prom metric (相关 surface)
            "F-204-1",  # follow-up ID
            "Twelve-Factor",  # sticky 读取 rationale
            "omit-when-off",  # Prom metric contract
            "fire-and-forget",  # emit contract
        ):
            self.assertIn(
                needle,
                self.text,
                f"docs/configuration.md 必须提到 {needle!r} 关键词",
            )


class TestChineseDocsHasEnvVarSection(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = _DOC_ZH.read_text(encoding="utf-8")

    def test_env_var_name_present(self) -> None:
        self.assertIn("AIIA_SSE_SCHEMA_VALIDATE", self.text)

    def test_all_three_modes_documented(self) -> None:
        for mode in ("off", "warn", "strict"):
            self.assertIn(f"`{mode}`", self.text)

    def test_key_design_keywords_present(self) -> None:
        for needle in (
            "R205",
            "R207",
            "F-204-1",
            "Twelve-Factor",
            "omit-when-off",
            "fire-and-forget",
        ):
            self.assertIn(
                needle,
                self.text,
                f"docs/configuration.zh-CN.md 必须提到 {needle!r} 关键词",
            )


if __name__ == "__main__":
    unittest.main()
