"""cr35 §8 #1 fix — task tab tooltip 提示 "Shift+双击" modifier 的回归测试。

modifier (Shift) 的发现性问题：实现 mining-2 §3.2 时，把"复制深链"
绑到 ``Shift+dblclick`` 而非新建 UI 元素，是为了避免挤占 task tab 的
布局空间。但 modifier 完全 invisible 给键盘小白用户。cr35 §8 #1 的
fix 是把提示直接挂到 native ``title`` tooltip。
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MULTI_TASK_JS = (
    REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "js" / "multi_task.js"
)
EN_JSON = REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "locales" / "en.json"
ZH_CN_JSON = (
    REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "locales" / "zh-CN.json"
)


class TestTooltipWiredToTextSpan(unittest.TestCase):
    src = MULTI_TASK_JS.read_text(encoding="utf-8")

    def test_title_includes_task_id_and_hint_suffix(self) -> None:
        """``textSpan.title`` 必须是 ``${task_id}\\n${tooltipSuffix}``，
        既保留原 "悬停看完整 ID" 行为，又追加 modifier 提示。
        """
        self.assertRegex(
            self.src,
            r"textSpan\.title\s*=\s*`\$\{task\.task_id\}\\n\$\{tooltipSuffix\}`",
            "textSpan.title 必须是 `${task.task_id}\\n${tooltipSuffix}` 形式",
        )

    def test_tooltip_suffix_reads_from_i18n_with_fallback(self) -> None:
        """tooltipSuffix 必须走 ``window.AIIA_I18N.t('page.taskTabCopyHint')``
        并提供英文 fallback —— 任何 i18n 加载失败都不能让 tooltip 变空。
        """
        # 1) i18n key 必须是 page.taskTabCopyHint
        self.assertIn(
            'window.AIIA_I18N.t("page.taskTabCopyHint")',
            self.src,
            "tooltipSuffix 必须从 page.taskTabCopyHint 取值",
        )
        # 2) 必须有英文 fallback 字面值
        self.assertIn(
            "Double-click to copy ID · Shift+double-click to copy link",
            self.src,
            "tooltipSuffix 必须有英文 fallback 字面值",
        )

    def test_data_attribute_persisted_for_a11y_introspection(self) -> None:
        """把 suffix 也写到 ``data-copy-hint-suffix`` —— 让自动化测试 /
        屏幕阅读器辅助层可以独立读取提示，而不必依赖 ``title``。
        """
        self.assertIn(
            'setAttribute("data-copy-hint-suffix", tooltipSuffix)',
            self.src,
        )


class TestI18nKeys(unittest.TestCase):
    def test_en_has_copy_hint_key(self) -> None:
        data = json.loads(EN_JSON.read_text(encoding="utf-8"))
        page = data.get("page") or {}
        self.assertIn("taskTabCopyHint", page)
        s = page["taskTabCopyHint"]
        # 英文 hint 必须同时提到 "Double-click" 和 "Shift"
        self.assertIn("Double-click", s)
        self.assertIn("Shift", s)

    def test_zh_cn_has_copy_hint_key(self) -> None:
        data = json.loads(ZH_CN_JSON.read_text(encoding="utf-8"))
        page = data.get("page") or {}
        self.assertIn("taskTabCopyHint", page)
        s = page["taskTabCopyHint"]
        # 中文必须同时提到"双击"和 "Shift"
        self.assertIn("双击", s)
        self.assertIn("Shift", s)

    def test_zh_distinct_from_en(self) -> None:
        en = json.loads(EN_JSON.read_text(encoding="utf-8"))
        zh = json.loads(ZH_CN_JSON.read_text(encoding="utf-8"))
        self.assertNotEqual(
            en["page"]["taskTabCopyHint"],
            zh["page"]["taskTabCopyHint"],
            "zh-CN copy hint 不能与 en 相同（说明没翻译）",
        )


class TestNoRegressionOfOriginalTitleBehavior(unittest.TestCase):
    """anti-regression：不能因为加 tooltip suffix 就丢失"悬停看完整 task_id"
    的原行为。新 title 格式仍以 task_id 开头。
    """

    def test_title_starts_with_task_id_template(self) -> None:
        src = MULTI_TASK_JS.read_text(encoding="utf-8")
        # 确保只有 ${task.task_id}\n${tooltipSuffix} 这种格式，
        # 不是 ${tooltipSuffix}\n${task.task_id} 颠倒
        # （后者会让用户复制时多按一次 hover 才看到 ID）
        m = re.search(r"textSpan\.title\s*=\s*`([^`]+)`", src)
        self.assertIsNotNone(m)
        assert m is not None
        tmpl = m.group(1)
        # 第一段必须是 ${task.task_id}
        self.assertTrue(
            tmpl.startswith("${task.task_id}"),
            f"title 模板必须以 ${{task.task_id}} 开头，实际：{tmpl!r}",
        )


if __name__ == "__main__":
    unittest.main()
