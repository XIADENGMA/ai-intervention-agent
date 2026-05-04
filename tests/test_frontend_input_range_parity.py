r"""防回归：前端 frontend_countdown 输入控件的边界 / fallback 默认值必须 = ``server_config`` 常量。

历史背景
---------
``shared_types.SECTION_MODELS::feedback.frontend_countdown`` 与
``server_config.AUTO_RESUBMIT_TIMEOUT_MIN/MAX/DEFAULT`` 在 v1.5.x
后期被对齐到 ``[10, 3600]`` / default ``240``。但**前端**层 —— Web UI
模板、Web UI 设置 JS、VS Code 扩展 webview HTML、VS Code 扩展设置
JS —— 仍然写着旧的 ``max="250"`` / ``v <= 250`` 限制；同样的，
``static/js/multi_task.js`` 里 5 处 ``?? 250`` / ``|| 250`` fallback
原本是 ``290``，2025 年改为 ``250`` 后就再也没更新过。结果：

  - 用户在浏览器 input 里**根本无法输入大于 250 的值**（``max`` 属性
    会让浏览器 reject）；即使绕过 HTML，``settings-manager.js`` 也
    会在 change 回调里 ``v <= 250`` 早返回，``debounceSaveFeedback``
    根本不会被触发。
  - VS Code 扩展同样的故事。

修这一波时同步把前端边界与 fallback 默认值都改对，并加这个回归位
锁住四个文件 + 五个 fallback 数字与 server_config 常量的等价性。

设计原则
--------
- 通过文件文本 + 正则提取数值，与从 ``server_config`` 直接 import
  的常量 ``AUTO_RESUBMIT_TIMEOUT_MAX/MIN/DEFAULT`` 比较。
- 每个文件里的"魔数 location"以 (file, regex, expected_const) 元组
  形式声明在测试 setUp 里，这样未来移动文件 / 改变正则只需要更新
  这张表。
- 4 处 input ``max`` 边界 + 4 处 JS 比较运算 (``<= max``) + 5 处
  fallback 默认值（``?? 240`` / ``|| 240``）—— 共 13 个 magic-number
  断言。
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from server_config import (
    AUTO_RESUBMIT_TIMEOUT_DEFAULT,
    AUTO_RESUBMIT_TIMEOUT_MAX,
)


def _read(path: Path) -> str:
    """读文件并断言非空，避免静默 false-positive。"""
    text = path.read_text(encoding="utf-8")
    assert text.strip(), f"{path} 是空文件，测试无法运行"
    return text


class TestFrontendInputMaxParity(unittest.TestCase):
    """前端 4 处 frontend_countdown 输入控件的 ``max`` / 比较运算 = ``AUTO_RESUBMIT_TIMEOUT_MAX``。"""

    def setUp(self) -> None:
        self.expected = AUTO_RESUBMIT_TIMEOUT_MAX  # 当前 = 3600

    def test_web_ui_html_input_max(self) -> None:
        """``templates/web_ui.html``: ``<input id="feedback-countdown" ... max="N">`` 的 N。"""
        text = _read(REPO_ROOT / "templates" / "web_ui.html")
        # 多行匹配 input 块，捕获 max="..." 中的数字
        m = re.search(r'id="feedback-countdown"[^>]*max="(\d+)"', text, flags=re.DOTALL)
        self.assertIsNotNone(
            m,
            'templates/web_ui.html 找不到 id="feedback-countdown" 的 max=... '
            "属性——HTML 结构变了，测试需要更新正则",
        )
        assert m is not None
        self.assertEqual(
            int(m.group(1)),
            self.expected,
            f"templates/web_ui.html: input max={m.group(1)} but "
            f"AUTO_RESUBMIT_TIMEOUT_MAX={self.expected}",
        )

    def test_settings_manager_js_max_check(self) -> None:
        """``static/js/settings-manager.js``: ``val <= N`` 的 N。"""
        text = _read(REPO_ROOT / "static" / "js" / "settings-manager.js")
        m = re.search(r"val\s*<=\s*(\d+)", text)
        self.assertIsNotNone(m)
        assert m is not None
        self.assertEqual(
            int(m.group(1)),
            self.expected,
            f"static/js/settings-manager.js: val <= {m.group(1)} but "
            f"AUTO_RESUBMIT_TIMEOUT_MAX={self.expected}",
        )

    def test_vscode_webview_ts_input_max(self) -> None:
        """``packages/vscode/webview.ts``: ``<input id="feedbackCountdown" ... max="N">``。"""
        text = _read(REPO_ROOT / "packages" / "vscode" / "webview.ts")
        m = re.search(r'id="feedbackCountdown"[^>]*max="(\d+)"', text, flags=re.DOTALL)
        self.assertIsNotNone(m)
        assert m is not None
        self.assertEqual(
            int(m.group(1)),
            self.expected,
            f"packages/vscode/webview.ts: input max={m.group(1)} but "
            f"AUTO_RESUBMIT_TIMEOUT_MAX={self.expected}",
        )

    def test_vscode_settings_ui_js_max_check(self) -> None:
        """``packages/vscode/webview-settings-ui.js``: ``v <= N``。"""
        text = _read(REPO_ROOT / "packages" / "vscode" / "webview-settings-ui.js")
        m = re.search(r"v\s*<=\s*(\d+)", text)
        self.assertIsNotNone(m)
        assert m is not None
        self.assertEqual(
            int(m.group(1)),
            self.expected,
            f"packages/vscode/webview-settings-ui.js: v <= {m.group(1)} but "
            f"AUTO_RESUBMIT_TIMEOUT_MAX={self.expected}",
        )


class TestFrontendCountdownFallbackDefault(unittest.TestCase):
    """``static/js/multi_task.js`` 里 5 处 ``?? N`` / ``|| N`` fallback = ``AUTO_RESUBMIT_TIMEOUT_DEFAULT``。

    历史漂移：2025 年代码注释 ``【优化】默认从290改为250`` 暴露了原始
    意图——这些 fallback 在 ``task.auto_resubmit_timeout`` 缺失时给一个
    "合理默认"，正确语义是 server-side ``AUTO_RESUBMIT_TIMEOUT_DEFAULT``
    (240)，不是历史 MAX (250 / 290)。本测试锁住"fallback = DEFAULT"。
    """

    def setUp(self) -> None:
        self.expected = AUTO_RESUBMIT_TIMEOUT_DEFAULT  # 当前 = 240
        self.text = _read(REPO_ROOT / "static" / "js" / "multi_task.js")

    def test_fallback_count_and_value(self) -> None:
        """所有 ``?? <int>`` 与 ``|| <int>`` 的非零 fallback 都必须 = DEFAULT。"""
        # 捕获两种 JS fallback 操作符后紧跟的整数字面量；严格要求是十进制整数，不允许变量名
        # 之所以用 ``\b\d{2,4}\b`` 是为了排除 ``|| 0`` / ``?? 0``（disabled 语义）
        # 与 ``|| -1`` 等无关 fallback；前端 countdown fallback 的合理范围是
        # 100 ~ 9999，足够把噪声都 filter 掉。
        pattern = re.compile(
            r"(\?\?|\|\|)\s*(\d{2,4})\b(?!\s*[%*/])",
        )
        # 只检测 multi_task.js 中与 auto_resubmit_timeout / countdown 相关的
        # 行（行内出现 "auto_resubmit_timeout" 或 "timeout" 或 "remaining"
        # 之一）。这样不会把别的 fallback（比如 retry_count ?? 3）误抓到。
        relevant_lines = [
            (i, line)
            for i, line in enumerate(self.text.splitlines(), start=1)
            if any(
                kw in line
                for kw in (
                    "auto_resubmit_timeout",
                    "remaining_time",
                    "taskCountdowns[task",
                    "taskCountdowns[taskId",
                )
            )
        ]
        found: list[tuple[int, str, int]] = []
        for line_no, line in relevant_lines:
            for m in pattern.finditer(line):
                found.append((line_no, m.group(1), int(m.group(2))))

        # 至少应找到 5 处 fallback；否则正则失效或代码大改
        self.assertGreaterEqual(
            len(found),
            5,
            "multi_task.js 里检测到的 fallback 数字少于 5 处——可能正则失效，"
            f"实际抓到：{found}",
        )

        # 每一处 fallback 都必须 = DEFAULT
        wrong = [
            (line_no, op, val) for line_no, op, val in found if val != self.expected
        ]
        self.assertEqual(
            wrong,
            [],
            f"multi_task.js: 以下 fallback 不等于 AUTO_RESUBMIT_TIMEOUT_DEFAULT "
            f"({self.expected}): {wrong}",
        )


class TestSettingsManagerFallbackDefault(unittest.TestCase):
    """``static/js/settings-manager.js`` 中 ``updateFeedbackUI`` 的 ``?? N`` fallback = ``AUTO_RESUBMIT_TIMEOUT_DEFAULT``。

    设置面板首次打开（``feedbackConfig`` 还没从 ``/api/feedback-config``
    fetch 回来时）会用这个 fallback 显示输入框默认值。如果 fallback 与
    server-side ``AUTO_RESUBMIT_TIMEOUT_DEFAULT`` 漂移，用户看到的"默认
    值"和服务器实际默认值就不一致——属于和 ``multi_task.js`` 同类型的
    fragile 硬编码。

    与 ``multi_task.js`` 的 5 处 fallback 测试是兄弟 gate，共同覆盖整个
    Web UI frontend 的 ``frontend_countdown`` fallback 表面。
    """

    def setUp(self) -> None:
        self.expected = AUTO_RESUBMIT_TIMEOUT_DEFAULT  # 当前 = 240
        self.text = _read(REPO_ROOT / "static" / "js" / "settings-manager.js")

    def test_update_feedback_ui_countdown_fallback(self) -> None:
        """``fc.frontend_countdown ?? N`` 中的 ``N`` 必须 = ``DEFAULT``。"""
        # 在 updateFeedbackUI 函数体内寻找 frontend_countdown 的 fallback
        m = re.search(
            r"frontend_countdown\s*\?\?\s*(\d+)",
            self.text,
        )
        self.assertIsNotNone(
            m,
            "static/js/settings-manager.js: 找不到 `frontend_countdown ?? <int>` "
            "fallback——可能函数被重构（比如改成 `?.frontend_countdown ?? `），"
            "本测试需要更新正则",
        )
        assert m is not None
        self.assertEqual(
            int(m.group(1)),
            self.expected,
            f"static/js/settings-manager.js: frontend_countdown ?? {m.group(1)} "
            f"but AUTO_RESUBMIT_TIMEOUT_DEFAULT={self.expected}. "
            f"Update settings-manager.js fallback to match the server-side default.",
        )


if __name__ == "__main__":
    unittest.main()
