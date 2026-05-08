"""T1 预置 token 回归测试（C10a / R104）。

本文件验证「三态面板」（Loading / Empty / Error）所需的共享 CSS token
``--aiia-state-*`` 在 Web UI 和 VSCode 插件 webview 两端**同名同值**。

目的：
- 防止未来改一端而忘改另一端（本质同 C8 的跨端 aiia.* 守护，只是针对 CSS）。
- C10b / C10c 落地三态面板时直接 ``var(--aiia-state-*)``，不用关心哪一端的
  数值定义——守护确保它们永远相等。

R104：替换原本的 ``self.skipTest("...不存在")`` 为 ``self.fail(...)``。
原实现把"核心 CSS 文件不存在"当成 silent skip = 0 覆盖（与 R76 重布局后
R88/R100/R101/R102 修过的同款 silent-broken 风险一致——核心资源被重命名
/移动时 CI 看似绿但 design-token 一致性其实没跑过）。``main.css`` 和
``webview.css`` 是 design-token 单一源；缺失即配置漂移，应 fail-loud。

运行：``uv run pytest tests/test_state_tokens.py -v``
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WEB_CSS = REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "css" / "main.css"
VSCODE_CSS = REPO_ROOT / "packages" / "vscode" / "webview.css"

TOKEN_RE = re.compile(
    r"--aiia-state-([a-z_-]+)\s*:\s*([^;]+);",
    flags=re.MULTILINE,
)

EXPECTED_TOKENS: frozenset[str] = frozenset(
    {
        "padding-y",
        "padding-x",
        "gap",
        "icon-size",
        "title-size",
        "message-size",
        "radius",
        "max-width",
        "transition",
    }
)


def _extract_tokens(path: Path) -> dict[str, str]:
    """从 CSS 文件里提取 ``--aiia-state-<name>: <value>;`` 映射。"""
    if not path.exists():
        return {}
    content = path.read_text(encoding="utf-8")
    return {name: value.strip() for name, value in TOKEN_RE.findall(content)}


def _fail_missing_css(test: unittest.TestCase, path: Path, label: str) -> None:
    """R104：核心 CSS 资源缺失 → fail-loud，不再 silent skip。

    与 R88/R100/R101/R102 同款修复：把"配置错"当"OK"的反模式从 layer-0 清出。
    设计 token 单一源被重命名 / 移动时，silent skip 模式让 CI 看似绿但
    cross-platform 一致性其实没跑过——R76 重布局把 ``static/`` 挪进 ``src/``
    包内时已经踩过一次同源问题（R88/R102）。

    ``path`` 可能不在 REPO_ROOT 下（reverse-injection 测试里会把常量替成
    ``/__definitely_not_existing__/missing.css``），此时退回打印绝对路径。
    """
    try:
        rel = path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        rel = str(path)
    test.fail(
        f"R104: {label} CSS 文件不存在: {rel}\n"
        f"  Resolved absolute path: {path}\n"
        f"  This is a configuration drift, not 'OK' — failing loud (R104;\n"
        f"  matches R88's brand-color, R100's HTML coverage, R101/R102's\n"
        f"  i18n scanner path-drift fixes).\n"
        f"  Either update the path constants at top of test_state_tokens.py\n"
        f"  (WEB_CSS / VSCODE_CSS) or restore the missing file."
    )


class TestAiiaStateTokens(unittest.TestCase):
    """C10a · 双端 ``--aiia-state-*`` token 完整性与一致性。"""

    def test_web_css_defines_all_expected_tokens(self):
        """Web UI main.css 里必须定义全部 9 个 ``--aiia-state-*`` token。"""
        if not WEB_CSS.exists():
            _fail_missing_css(self, WEB_CSS, "Web UI")
        tokens = _extract_tokens(WEB_CSS)
        missing = EXPECTED_TOKENS - set(tokens.keys())
        self.assertFalse(
            missing,
            f"Web UI CSS 缺少 --aiia-state-* token: {sorted(missing)}",
        )

    def test_vscode_css_defines_all_expected_tokens(self):
        """VSCode webview.css 里必须定义全部 9 个 ``--aiia-state-*`` token。"""
        if not VSCODE_CSS.exists():
            _fail_missing_css(self, VSCODE_CSS, "VSCode webview")
        tokens = _extract_tokens(VSCODE_CSS)
        missing = EXPECTED_TOKENS - set(tokens.keys())
        self.assertFalse(
            missing,
            f"VSCode webview CSS 缺少 --aiia-state-* token: {sorted(missing)}",
        )

    def test_cross_platform_token_values_equal(self):
        """每个 ``--aiia-state-*`` token 在 Web UI 和 VSCode 的数值必须完全一致。

        这是 T1 的硬性契约——三态面板的尺寸 / 间距 / 圆角 / 过渡时间必须
        在双端表现一样，否则用户在浏览器和 VSCode 侧边栏看到的"加载中"
        面板会长得不一样，形成体感割裂。
        """
        if not WEB_CSS.exists():
            _fail_missing_css(self, WEB_CSS, "Web UI")
        if not VSCODE_CSS.exists():
            _fail_missing_css(self, VSCODE_CSS, "VSCode webview")
        web = _extract_tokens(WEB_CSS)
        vs = _extract_tokens(VSCODE_CSS)
        mismatches: list[str] = []
        for key in sorted(EXPECTED_TOKENS):
            wv = web.get(key, "<missing>")
            vv = vs.get(key, "<missing>")
            if wv != vv:
                mismatches.append(
                    f"  --aiia-state-{key}: Web UI={wv!r} vs VSCode={vv!r}"
                )
        if mismatches:
            self.fail("双端 --aiia-state-* token 数值漂移：\n" + "\n".join(mismatches))

    def test_transition_token_is_proper_shorthand(self):
        """``--aiia-state-transition`` 必须是合法的 CSS transition 简写。

        不校验具体动画名/时长（允许以后微调），只要求**非空字符串**，
        且不包含明显漂移信号如 ``url(`` / ``!important``。

        R104：双端 ``continue if not path.exists()`` 改 fail-loud——核心 CSS
        缺失即配置漂移，与 ``test_web_css_defines_all_expected_tokens`` /
        ``test_vscode_css_defines_all_expected_tokens`` 行为对齐。
        """
        for label, path in (
            ("Web UI", WEB_CSS),
            ("VSCode webview", VSCODE_CSS),
        ):
            if not path.exists():
                _fail_missing_css(self, path, label)
            tokens = _extract_tokens(path)
            transition = tokens.get("transition", "")
            self.assertTrue(
                transition,
                f"{label} 的 --aiia-state-transition 为空",
            )
            self.assertNotIn(
                "url(",
                transition,
                f"{label} 的 --aiia-state-transition 不应包含 url()",
            )
            self.assertNotIn(
                "!important",
                transition,
                f"{label} 的 --aiia-state-transition 不应包含 !important",
            )


class TestPathDriftR104(unittest.TestCase):
    """R104：path-drift sanity check —— 让 reviewer 立刻看到核心 CSS 资源
    缺失 / 重命名时的修复路径。

    设计 token 测试本身的存在性 / 一致性已被 ``TestAiiaStateTokens`` 的 fail
    路径锁住；本 class 单独把"前置 sanity"也提到测试集合里：``WEB_CSS`` /
    ``VSCODE_CSS`` 路径常量和文件系统现状必须保持同步。两条测试构造一个
    诊断自检——CI 输出里能看到「path constant points at real file」是绿的，
    任何漂移会立刻在测试报告 line-1 就 fail。
    """

    def _format_path(self, path: Path) -> str:
        try:
            return path.relative_to(REPO_ROOT).as_posix()
        except ValueError:
            return str(path)

    def test_web_css_path_resolves_to_existing_file(self) -> None:
        """``WEB_CSS`` 路径常量必须指向实际存在的文件。"""
        self.assertTrue(
            WEB_CSS.exists(),
            msg=(
                f"R104 sanity: WEB_CSS path drift detected.\n"
                f"  Constant: WEB_CSS = {self._format_path(WEB_CSS)}\n"
                f"  Absolute: {WEB_CSS}\n"
                f"  File missing — update WEB_CSS in tests/test_state_tokens.py\n"
                f"  or restore the file."
            ),
        )

    def test_vscode_css_path_resolves_to_existing_file(self) -> None:
        """``VSCODE_CSS`` 路径常量必须指向实际存在的文件。"""
        self.assertTrue(
            VSCODE_CSS.exists(),
            msg=(
                f"R104 sanity: VSCODE_CSS path drift detected.\n"
                f"  Constant: VSCODE_CSS = {self._format_path(VSCODE_CSS)}\n"
                f"  Absolute: {VSCODE_CSS}\n"
                f"  File missing — update VSCODE_CSS in "
                f"tests/test_state_tokens.py or restore the file."
            ),
        )


if __name__ == "__main__":
    unittest.main()
