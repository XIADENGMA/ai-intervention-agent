"""R103：``scripts/ci_gate.py`` 必须把 ``check_brand_color_consistency.py`` 接入 CI。

历史 silent breakage（R88 之后的下一层）：

* R66 设计 ``check_brand_color_consistency.py`` 时只挂在 ``.pre-commit-
  config.yaml`` 的 local hook 上（脚本 docstring「集成」一节明文如此）。
* R76 把 ``static/`` 挪进 ``src/`` 包内，hook ``files`` glob + 脚本
  ``DEFAULT_ROOT`` 同时漂移 → 整条 hook silently broken；R88 修复。
* R88 把 hook 修对了，但**没有解决另一层**：``test.yml`` /
  ``release.yml`` CI workflow 都只跑 ``ci_gate.py --ci``，没有
  ``pre-commit run --all-files`` 步骤；仓库也不强制 ``pre-commit
  install``。三个失败模式合起来：开发者本地不装 pre-commit 时，新增
  ``rgba(0, 122, 255, X)`` 或 ``#007aff`` 全部能 silently merge——
  R66 baseline 34 / R99 hex baseline 7 的锁定**完全失效**。

R103 修复：在 ``ci_gate.py`` 的 i18n 检查序列尾部追加
``check_brand_color_consistency.py --quiet``，让 CI 兜底执行这道防线。
本测试**锁住**这个集成点不允许再次漂移：

1. ``ci_gate.py`` 源码必须以 ``--quiet`` 形式调用脚本。
2. 调用必须在 ``check_i18n_locale_shape.py`` 之后（紧邻 i18n 序列尾部，
   语义分组合理）。
3. ``--quiet`` flag 不能漏 —— 否则 happy-path 会污染 CI 日志。
4. ``check_brand_color_consistency.py`` 自身仍然必须存在且可调用（防止
   未来重命名 / 删脚本 ci_gate 引用变 broken）。

反向注入：删掉 ci_gate 中的 ``_run([..., "scripts/check_brand_color_
consistency.py", ...])`` 调用 → 本测试 1/2/3 全 fail。
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CI_GATE_PATH = REPO_ROOT / "scripts" / "ci_gate.py"
BRAND_COLOR_SCRIPT = REPO_ROOT / "scripts" / "check_brand_color_consistency.py"


def _ci_gate_source() -> str:
    return CI_GATE_PATH.read_text(encoding="utf-8")


class TestBrandColorIntegrationR103(unittest.TestCase):
    """R103 集成点契约。"""

    def test_ci_gate_invokes_brand_color_script(self) -> None:
        """ci_gate.py 必须 ``_run`` 调用 ``scripts/check_brand_color_consistency.py``。

        匹配两种合理写法（参数顺序）：
            _run(["uv", "run", "python", "scripts/check_brand_color_consistency.py", "--quiet"])
            _run([..., "scripts/check_brand_color_consistency.py", "--quiet"])
        """
        src = _ci_gate_source()
        pattern = re.compile(
            r"_run\s*\(\s*\[[^\]]*scripts/check_brand_color_consistency\.py[^\]]*\]",
            re.DOTALL,
        )
        match = pattern.search(src)
        self.assertIsNotNone(
            match,
            msg=(
                "R103 contract violated: ci_gate.py 没有 _run(...) 调用 "
                "scripts/check_brand_color_consistency.py。\n"
                "  这意味着 R66/R88/R99 的 baseline 防线只在 pre-commit hook 上生效，\n"
                "  开发者本地不装 pre-commit 时 PR 改 CSS 完全没有 CI 兜底（参见 R103 RCA）。"
            ),
        )

    def test_brand_color_invocation_uses_quiet_flag(self) -> None:
        """``--quiet`` 必须出现在调用列表里。

        没有 ``--quiet`` 会让 happy-path（baseline 通过）污染 CI 日志输出
        ``✅ CSS 品牌色检查通过：...``，违反 ci_gate 整体 "通过时静默" 的契约。
        """
        src = _ci_gate_source()
        invocation = re.search(
            r"_run\s*\(\s*\[[^\]]*scripts/check_brand_color_consistency\.py[^\]]*\]",
            src,
            re.DOTALL,
        )
        if invocation is None:
            self.fail("前置条件失败：ci_gate.py 没接入 brand-color script")
        invocation_text = invocation.group(0)
        self.assertIn(
            '"--quiet"',
            invocation_text,
            msg=(
                "R103 contract violated: brand-color check 调用缺少 --quiet flag。\n"
                f"  实际调用片段: {invocation_text}\n"
                "  pre-commit hook 用了 --quiet，ci_gate 应保持一致语义。"
            ),
        )

    def test_brand_color_call_is_after_locale_shape_check(self) -> None:
        """位置必须在 ``check_i18n_locale_shape.py`` 调用之后（i18n 序列尾部）。

        语义合理性：brand-color check 与 i18n 一致性扫描器属于同类
        "PR drift detector"，放在 i18n 序列末尾 + minify_assets 之前
        = 失败时人类可读的 fail-fast 顺序（先跑 ~200ms 的 sanity，再跑
        慢的 minify / pytest）。也方便维护者快速 grep 找"漂移检测"集中地。
        """
        src = _ci_gate_source()
        shape_pos = src.find("scripts/check_i18n_locale_shape.py")
        brand_pos = src.find("scripts/check_brand_color_consistency.py")
        self.assertGreaterEqual(
            shape_pos,
            0,
            "前置条件失败：找不到 check_i18n_locale_shape.py 调用",
        )
        self.assertGreaterEqual(
            brand_pos,
            0,
            "前置条件失败：找不到 check_brand_color_consistency.py 调用",
        )
        self.assertGreater(
            brand_pos,
            shape_pos,
            msg=(
                "R103 contract violated: brand-color check 调用应在 "
                "check_i18n_locale_shape.py 之后（i18n 漂移检测序列尾部）。\n"
                f"  shape_pos={shape_pos}, brand_pos={brand_pos}"
            ),
        )

    def test_brand_color_script_exists_and_is_executable(self) -> None:
        """``check_brand_color_consistency.py`` 必须存在 + 有 main()。

        防止未来 PR 重命名 / 删脚本，ci_gate 静态引用还在但运行时
        FileNotFoundError——比 silent skip 更糟糕（会让 CI 红得没头没脑）。
        """
        self.assertTrue(
            BRAND_COLOR_SCRIPT.exists(),
            msg=(
                f"R103 前置条件失败：{BRAND_COLOR_SCRIPT.relative_to(REPO_ROOT)} 不存在。\n"
                "  ci_gate.py 的引用会变成运行时 FileNotFoundError。"
            ),
        )
        content = BRAND_COLOR_SCRIPT.read_text(encoding="utf-8")
        self.assertRegex(
            content,
            r"def\s+main\s*\(",
            msg="R103 前置条件失败：脚本里找不到 main() —— 调用时会 sys.exit(0)（no-op）",
        )


if __name__ == "__main__":
    unittest.main()
