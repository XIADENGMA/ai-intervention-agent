"""可能的 BUG6 回归契约：插件 / web / 后端三端 prompt maxlength 必须一致。

用户报告："插件读取 Resubmit prompt 和 Feedback suffix，好像还是有字数
限制，没有和 web 统一。"

调查链
------
- 后端：``src/ai_intervention_agent/server_config.py``
  ``PROMPT_MAX_LENGTH = 100_000`` —— 真正持久化与传输的上限。
- Web UI：``src/ai_intervention_agent/templates/web_ui.html`` 两个 textarea
  ``#feedback-resubmit-prompt`` / ``#feedback-prompt-suffix`` 都用
  ``maxlength="100000"`` —— 与后端对齐。
- VSCode 插件：``packages/vscode/webview.ts`` 历史用 ``maxlength="500"``
  → **远低于后端**，用户在插件设置面板里输入超过 500 字符就被静默截断。
  后端接收的 resubmit_prompt 与配置文件持久化的内容长度也不一致。

修复
----
插件 webview.ts 两个 textarea 的 maxlength 提到 100000，与
``PROMPT_MAX_LENGTH`` + web UI 完全对齐。

本测试用静态扫描三端实际取值并断言相等。
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SERVER_CONFIG_PATH = REPO_ROOT / "src" / "ai_intervention_agent" / "server_config.py"
WEB_UI_HTML = REPO_ROOT / "src" / "ai_intervention_agent" / "templates" / "web_ui.html"
VSCODE_WEBVIEW_TS = REPO_ROOT / "packages" / "vscode" / "webview.ts"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


class TestThreeSurfacesAgreeOnPromptMaxLength(unittest.TestCase):
    """后端常量、Web UI textarea、VSCode 插件 textarea 三端 maxlength 必须相等。"""

    def setUp(self) -> None:
        self.backend_max = self._parse_backend_max()
        self.web_resubmit_max, self.web_suffix_max = self._parse_web_maxlengths()
        self.plugin_resubmit_max, self.plugin_suffix_max = (
            self._parse_plugin_maxlengths()
        )

    @staticmethod
    def _parse_backend_max() -> int:
        src = _read(SERVER_CONFIG_PATH)
        match = re.search(r"PROMPT_MAX_LENGTH\s*=\s*([\d_]+)", src)
        assert match is not None, "找不到 server_config.PROMPT_MAX_LENGTH"
        return int(match.group(1).replace("_", ""))

    @staticmethod
    def _parse_web_maxlengths() -> tuple[int, int]:
        html = _read(WEB_UI_HTML)
        # 找 #feedback-resubmit-prompt textarea 的 maxlength
        resubmit = re.search(
            r'id="feedback-resubmit-prompt"[^>]*maxlength="(\d+)"',
            html,
            re.DOTALL,
        )
        suffix = re.search(
            r'id="feedback-prompt-suffix"[^>]*maxlength="(\d+)"',
            html,
            re.DOTALL,
        )
        assert resubmit is not None, (
            "web_ui.html 中 #feedback-resubmit-prompt textarea 必须有 maxlength"
        )
        assert suffix is not None, (
            "web_ui.html 中 #feedback-prompt-suffix textarea 必须有 maxlength"
        )
        return int(resubmit.group(1)), int(suffix.group(1))

    @staticmethod
    def _parse_plugin_maxlengths() -> tuple[int, int]:
        src = _read(VSCODE_WEBVIEW_TS)
        # webview.ts 是 TS template literal，找 textarea 的 maxlength
        resubmit = re.search(
            r'id="feedbackResubmitPrompt"[^>]*maxlength="(\d+)"',
            src,
        )
        suffix = re.search(
            r'id="feedbackPromptSuffix"[^>]*maxlength="(\d+)"',
            src,
        )
        assert resubmit is not None, (
            "webview.ts 中 #feedbackResubmitPrompt textarea 必须有 maxlength"
        )
        assert suffix is not None, (
            "webview.ts 中 #feedbackPromptSuffix textarea 必须有 maxlength"
        )
        return int(resubmit.group(1)), int(suffix.group(1))

    def test_backend_max_is_100k(self) -> None:
        self.assertEqual(
            self.backend_max,
            100_000,
            "PROMPT_MAX_LENGTH 不再是 100_000，本测试断言需要同步更新",
        )

    def test_web_resubmit_matches_backend(self) -> None:
        self.assertEqual(
            self.web_resubmit_max,
            self.backend_max,
            f"Web UI #feedback-resubmit-prompt maxlength={self.web_resubmit_max} "
            f"必须与后端 PROMPT_MAX_LENGTH={self.backend_max} 一致",
        )

    def test_web_suffix_matches_backend(self) -> None:
        self.assertEqual(
            self.web_suffix_max,
            self.backend_max,
            f"Web UI #feedback-prompt-suffix maxlength={self.web_suffix_max} "
            f"必须与后端 PROMPT_MAX_LENGTH={self.backend_max} 一致",
        )

    def test_plugin_resubmit_matches_backend(self) -> None:
        self.assertEqual(
            self.plugin_resubmit_max,
            self.backend_max,
            f"VSCode 插件 #feedbackResubmitPrompt maxlength={self.plugin_resubmit_max} "
            f"必须与后端 PROMPT_MAX_LENGTH={self.backend_max} 一致（"
            "之前是 500，会让用户输入被静默截断）",
        )

    def test_plugin_suffix_matches_backend(self) -> None:
        self.assertEqual(
            self.plugin_suffix_max,
            self.backend_max,
            f"VSCode 插件 #feedbackPromptSuffix maxlength={self.plugin_suffix_max} "
            f"必须与后端 PROMPT_MAX_LENGTH={self.backend_max} 一致",
        )

    def test_plugin_no_legacy_500_anywhere(self) -> None:
        """插件 webview.ts 中不应再有 maxlength="500" 用在 prompt textarea 上。"""
        src = _read(VSCODE_WEBVIEW_TS)
        # 锁住 prompt textarea 不能再用 500
        legacy = re.search(
            r'(feedbackResubmitPrompt|feedbackPromptSuffix)[^>]*maxlength="500"',
            src,
        )
        self.assertIsNone(
            legacy,
            "webview.ts 中 prompt textarea 不应再用 maxlength=500（与后端 100k 不一致）",
        )


if __name__ == "__main__":
    unittest.main()
