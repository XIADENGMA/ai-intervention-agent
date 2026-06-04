"""BUG2 回归契约：SSE ``config_changed`` toast 必须走前端 i18n 而非硬编码英文。

背景：``_emit_config_changed_to_sse_bus``（``web_ui_config_sync.py``）在 SSE
event detail 里硬编码英文 hint："Configuration file changed. Reload the page
to see the latest values."。i18n 上下文是 per-client 的，后端无法替每个
浏览器选语言；因此前端必须自己用本地化字典渲染该 toast。

修复策略：
- 在 ``static/locales/{zh-CN,en,_pseudo/pseudo}.json`` 新增 ``status.configChangedReload``；
- ``multi_task.js`` 的 SSE ``config_changed`` handler 优先用 ``_t("status.configChangedReload")``，
  缺失时回退 ``detail.hint``，再缺失时回退英文硬编码（多层兜底）。

本测试通过静态扫描锁住：
1. 三个 locale 文件都有 ``status.configChangedReload`` key 且 value 非空；
2. zh-CN 必须真正是中文（不能复制英文文案过来）；
3. ``multi_task.js`` 的 SSE handler 优先调用 ``_t("status.configChangedReload")``；
4. 多层兜底链路存在（i18n → detail.hint → 英文硬编码）。
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LOCALES_DIR = REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "locales"
MULTI_TASK_JS = (
    REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "js" / "multi_task.js"
)

I18N_KEY = "configChangedReload"
I18N_FULL_PATH = f"status.{I18N_KEY}"


def _load_locale(name: str) -> dict:
    path = LOCALES_DIR / name
    return json.loads(path.read_text(encoding="utf-8"))


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class TestLocaleKeysPresent(unittest.TestCase):
    """三个 locale 文件都必须有 ``status.configChangedReload`` 且非空。"""

    def _assert_key_present(self, locale_path: str) -> str:
        data = _load_locale(locale_path)
        status = data.get("status")
        self.assertIsInstance(status, dict, f"{locale_path} 应该有 status section")
        value = status.get(I18N_KEY)
        self.assertIsInstance(
            value,
            str,
            f"{locale_path} 必须有 status.{I18N_KEY} 键，类型为 str",
        )
        self.assertTrue(
            value.strip(),
            f"{locale_path} 的 status.{I18N_KEY} 不能为空",
        )
        return value

    def test_zh_cn_locale_has_key(self) -> None:
        self._assert_key_present("zh-CN.json")

    def test_en_locale_has_key(self) -> None:
        self._assert_key_present("en.json")

    def test_pseudo_locale_has_key(self) -> None:
        self._assert_key_present("_pseudo/pseudo.json")


class TestChineseLocaleActuallyChinese(unittest.TestCase):
    """``zh-CN.json`` 的文案必须真正是中文（包含 CJK 字符）。

    防御：避免维护者复制 ``en.json`` 字符串过来后忘记翻译，让"中文页面
    弹英文 toast"的回归再次发生。
    """

    def test_zh_value_contains_chinese(self) -> None:
        value = _load_locale("zh-CN.json")["status"][I18N_KEY]
        cjk_chars = [c for c in value if "\u4e00" <= c <= "\u9fff"]
        self.assertGreaterEqual(
            len(cjk_chars),
            4,
            f"zh-CN status.{I18N_KEY} 应至少包含 4 个 CJK 字符；当前 value={value!r}",
        )

    def test_zh_value_not_equal_to_en(self) -> None:
        zh = _load_locale("zh-CN.json")["status"][I18N_KEY]
        en = _load_locale("en.json")["status"][I18N_KEY]
        self.assertNotEqual(
            zh,
            en,
            f"zh-CN status.{I18N_KEY} 不能与 en 完全相同；提示文案需翻译",
        )


class TestMultiTaskUsesI18nForHint(unittest.TestCase):
    """``multi_task.js`` 必须优先用本地化文案，而不是直接照搬 detail.hint。"""

    def setUp(self) -> None:
        self.source = _read(MULTI_TASK_JS)

    def _extract_config_changed_handler(self) -> str:
        """提取 config_changed handler 的完整代码块（含 try/catch 嵌套）。

        手写括号配对，避免 ``re.search`` 的 ``.*?`` 在第一个 ``}`` 处提前
        终止 —— SSE handler 内部有 try/catch + if/else 嵌套大括号。
        """
        start_marker = 'addEventListener("config_changed"'
        start = self.source.find(start_marker)
        self.assertGreaterEqual(start, 0, "无法定位 config_changed SSE handler")
        # 找到 function (e) { 的开括号
        open_brace_idx = self.source.find("{", start)
        self.assertGreaterEqual(open_brace_idx, 0, "无法定位 handler 的 { 开始位置")
        # 平衡大括号扫描到匹配的关闭位置（忽略字符串字面量/注释里的大括号）
        depth = 1
        i = open_brace_idx + 1
        in_string: str | None = None
        in_line_comment = False
        in_block_comment = False
        while i < len(self.source) and depth > 0:
            ch = self.source[i]
            nxt = self.source[i + 1] if i + 1 < len(self.source) else ""
            if in_line_comment:
                if ch == "\n":
                    in_line_comment = False
            elif in_block_comment:
                if ch == "*" and nxt == "/":
                    in_block_comment = False
                    i += 1
            elif in_string is not None:
                if ch == "\\":
                    i += 1  # skip next char
                elif ch == in_string:
                    in_string = None
            else:
                if ch == "/" and nxt == "/":
                    in_line_comment = True
                    i += 1
                elif ch == "/" and nxt == "*":
                    in_block_comment = True
                    i += 1
                elif ch in ('"', "'", "`"):
                    in_string = ch
                elif ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        return self.source[open_brace_idx + 1 : i]
            i += 1
        self.fail("config_changed handler 大括号未平衡")
        return ""  # unreachable, pleases type-checker

    def test_handler_calls_i18n_helper(self) -> None:
        body = self._extract_config_changed_handler()
        # 同时接受单/双引号字面量。
        self.assertRegex(
            body,
            r"_t\(['\"]status\.configChangedReload['\"]\)",
            "config_changed SSE handler 必须调用 _t('status.configChangedReload') "
            "获取本地化文案",
        )

    def test_i18n_lookup_is_before_detail_hint(self) -> None:
        """i18n 查找必须在 detail.hint 兜底之前，否则等于先用英文。

        关键代码层面定位：用 ``typeof detail.hint === "string"`` 作为
        detail.hint 兜底的 anchor，避免被注释中提到 detail.hint 的位置干扰。
        """
        body = self._extract_config_changed_handler()
        i18n_match = re.search(r"_t\(['\"]status\.configChangedReload['\"]\)", body)
        # 匹配真正的兜底代码（不是注释里的提示）。同时接受单/双引号字面量。
        hint_match = re.search(r"typeof\s+detail\.hint\s*===\s*['\"]string['\"]", body)
        self.assertIsNotNone(i18n_match, "缺少 _t('status.configChangedReload')")
        self.assertIsNotNone(
            hint_match,
            "缺少 typeof detail.hint === 'string' 的兜底（多层 fallback 才稳）",
        )
        self.assertLess(
            i18n_match.start(),
            hint_match.start(),
            "i18n 查找必须出现在 detail.hint 兜底之前（否则英文 hint 会覆盖中文）",
        )

    def test_fallback_chain_documented(self) -> None:
        """注释中必须提到 BUG2 锚点，便于后续维护者追溯。"""
        # 整个文件级别有 BUG2 注释即可（避免限制注释具体位置）。
        self.assertIn(
            "BUG2",
            self.source,
            "multi_task.js 应在 config_changed handler 附近注释中标注 'BUG2' 锚点",
        )

    def test_english_fallback_string_still_present(self) -> None:
        """硬编码英文 fallback 必须保留，覆盖 i18n / detail.hint 都缺失的极端情况。"""
        body = self._extract_config_changed_handler()
        self.assertIn(
            "Configuration file changed. Reload the page to see the latest values.",
            body,
            "英文兜底 fallback 必须保留：i18n 字典 + backend detail.hint 都缺失时仍能显示提示",
        )


if __name__ == "__main__":
    unittest.main()
