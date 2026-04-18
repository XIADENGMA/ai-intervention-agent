"""T1 预置 token 回归测试（C10a）。

本文件验证「三态面板」（Loading / Empty / Error）所需的共享 CSS token
``--aiia-state-*`` 在 Web UI 和 VSCode 插件 webview 两端**同名同值**。

目的：
- 防止未来改一端而忘改另一端（本质同 C8 的跨端 aiia.* 守护，只是针对 CSS）。
- C10b / C10c 落地三态面板时直接 ``var(--aiia-state-*)``，不用关心哪一端的
  数值定义——守护确保它们永远相等。

运行：``uv run pytest tests/test_state_tokens.py -v``
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WEB_CSS = REPO_ROOT / "static" / "css" / "main.css"
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


class TestAiiaStateTokens(unittest.TestCase):
    """C10a · 双端 ``--aiia-state-*`` token 完整性与一致性。"""

    def test_web_css_defines_all_expected_tokens(self):
        """Web UI main.css 里必须定义全部 9 个 ``--aiia-state-*`` token。"""
        if not WEB_CSS.exists():
            self.skipTest("static/css/main.css 不存在")
        tokens = _extract_tokens(WEB_CSS)
        missing = EXPECTED_TOKENS - set(tokens.keys())
        self.assertFalse(
            missing,
            f"Web UI CSS 缺少 --aiia-state-* token: {sorted(missing)}",
        )

    def test_vscode_css_defines_all_expected_tokens(self):
        """VSCode webview.css 里必须定义全部 9 个 ``--aiia-state-*`` token。"""
        if not VSCODE_CSS.exists():
            self.skipTest("packages/vscode/webview.css 不存在")
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
        if not WEB_CSS.exists() or not VSCODE_CSS.exists():
            self.skipTest("某一端 CSS 文件不存在")
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
        """
        for label, path in (
            ("Web UI", WEB_CSS),
            ("VSCode", VSCODE_CSS),
        ):
            if not path.exists():
                continue
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


if __name__ == "__main__":
    unittest.main()
