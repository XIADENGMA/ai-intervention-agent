"""R277 / cycle-24 mining-15 (R272 spillover): settings-panel 缺 backdrop
click 关闭 handler — modal close UX 一致性 audit。

R272 教训
---------

R272 揭示了 ESC handler 应该 delegate to canonical close 函数 (而非
裸 ``classList.swap``)，避免漏掉焦点恢复 / inert 清理 / listener 解绑。
修复后引入了 cr53 §5 #3 mining-15: 全项目 modal close delegation audit。

R277 是 mining-15 的第一个真发现
-------------------------------

项目里 3 个 ``role="dialog"`` 元素：

| Dialog | ESC | Close 按钮 | Backdrop click |
|--------|-----|-----------|----------------|
| ``#settings-panel`` | hideSettings (R272) | hideSettings | **缺失** ❌ |
| ``#image-modal`` | closeImageModal (R272) | closeImageModal | closeImageModal ✓ |
| ``#code-paste-panel`` | closeCodePasteModal (self) | closeCodePasteModal | closeCodePasteModal ✓ |

3 个 dialog 中 1 个 (settings-panel) 缺 backdrop click 关闭。这是
inconsistent UX：

- 用户在 image-modal / code-paste 学到"点 backdrop 关闭"
- 切到 settings，点 backdrop 没反应 → 困惑/必须找 X 或按 ESC

settings 是 auto-save，无 dirty form 概念，点 backdrop 直接关是符合
Material Design dismissible dialog + iOS sheet swipe-down 等标准 UX。

R277 修复
---------

``settings-manager.js::init()`` 添加 backdrop click handler，pattern
与 image-modal/code-paste-panel 100% 对齐：

- ``e.target === settingsPanel`` 守卫：只有点 panel 本身（即 backdrop
  区域）才关；点 ``.settings-content`` 内部因为事件冒泡到 settings-content
  而不是 settings-panel，不会触发关
- 使用 ``dataset.aiiaBackdropWired`` guard (R265 pattern) 防止重复绑定
- delegate 到 canonical ``hideSettings()`` 而非裸 classList swap (R272 pattern)

Invariant
---------

1. ``settings-manager.js`` 必须含 ``addEventListener("click"`` 调用绑在
   ``settings-panel`` 上
2. backdrop click handler 必须有 ``e.target === settingsPanel`` 守卫
3. backdrop click handler 必须 delegate 到 ``this.hideSettings()``
4. 必须使用 ``dataset.aiiaBackdropWired`` guard 避免重复绑定 (R265 pattern)
5. R277 注释 anchor 必须在
"""

from __future__ import annotations

import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SETTINGS_JS = (
    REPO_ROOT
    / "src"
    / "ai_intervention_agent"
    / "static"
    / "js"
    / "settings-manager.js"
)


class TestSettingsBackdropClickHandler(unittest.TestCase):
    src = SETTINGS_JS.read_text(encoding="utf-8")

    def test_addeventlistener_click_on_settings_panel(self) -> None:
        """settings-manager 必须给 settings-panel 绑 click handler。"""
        self.assertRegex(
            self.src,
            r'settingsPanel\.addEventListener\(\s*"click"',
            "R277: settings-panel 必须有 addEventListener('click', ...) "
            "用于 backdrop click 关闭，与 image-modal/code-paste-panel 对齐",
        )

    def test_uses_target_equality_guard(self) -> None:
        """必须 ``e.target === settingsPanel`` 守卫，避免内层 click 误触关闭。"""
        self.assertRegex(
            self.src,
            r"e\.target\s*===\s*settingsPanel",
            "R277: backdrop click handler 必须有 ``e.target === settingsPanel`` "
            "守卫，否则点 settings-content 内部任何元素都会触发关闭",
        )

    def test_delegates_to_hide_settings(self) -> None:
        """backdrop click 必须 delegate 到 ``this.hideSettings()``，不能裸 classList swap。"""
        self.assertRegex(
            self.src,
            r"e\.target\s*===\s*settingsPanel[\s\S]{0,200}this\.hideSettings\(\)",
            "R277: backdrop click 必须 delegate 到 ``this.hideSettings()`` "
            "(R272 canonical close pattern)，不能裸 classList.remove",
        )

    def test_uses_dataset_guard(self) -> None:
        """``dataset.aiiaBackdropWired`` guard 防止重复绑定 (R265 N+1 leak pattern 复用)。"""
        self.assertRegex(
            self.src,
            r"dataset\.aiiaBackdropWired",
            "R277: 必须使用 ``dataset.aiiaBackdropWired`` guard 防止"
            "重复绑定，与 R265 ``aiiaWired`` 及 R263a ``aiiaInited`` 同模式",
        )

    def test_r277_annotation_present(self) -> None:
        """R277 注释 anchor 必须在源码中，方便未来维护者快速定位逻辑。"""
        self.assertIn(
            "R277",
            self.src,
            "R277: settings-manager.js 必须保留 R277 注释，标注 backdrop "
            "click delegate 设计选择 + mining-15 audit 关系",
        )


class TestModalCloseDelegationConsistency(unittest.TestCase):
    """R277 cross-modal sanity: 验证 3 个 dialog backdrop click delegation
    全部使用 canonical close 函数，不退回 bare classList swap。"""

    def setUp(self) -> None:
        self.settings_src = SETTINGS_JS.read_text(encoding="utf-8")
        self.image_src = (
            REPO_ROOT
            / "src"
            / "ai_intervention_agent"
            / "static"
            / "js"
            / "image-upload.js"
        ).read_text(encoding="utf-8")
        self.app_src = (
            REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "js" / "app.js"
        ).read_text(encoding="utf-8")

    def test_image_modal_backdrop_delegates_to_close(self) -> None:
        """sanity (R272 pre-existing): image-modal backdrop → closeImageModal()"""
        self.assertRegex(
            self.image_src,
            r"e\.target\s*===\s*modal[\s\S]{0,200}closeImageModal\(\)",
            "R277 sanity: image-modal backdrop 必须 delegate 到 "
            "closeImageModal()（R272 不能被回归破坏）",
        )

    def test_code_paste_panel_backdrop_delegates_to_close(self) -> None:
        """sanity (R272 pre-existing): code-paste-panel backdrop → closeCodePasteModal()"""
        self.assertRegex(
            self.app_src,
            r"e\.target\s*===\s*codePastePanel[\s\S]{0,200}closeCodePasteModal\(\)",
            "R277 sanity: code-paste-panel backdrop 必须 delegate 到 "
            "closeCodePasteModal()（R272 不能被回归破坏）",
        )

    def test_settings_panel_backdrop_delegates_to_close(self) -> None:
        """R277 new: settings-panel backdrop → hideSettings()"""
        self.assertRegex(
            self.settings_src,
            r"e\.target\s*===\s*settingsPanel[\s\S]{0,200}this\.hideSettings\(\)",
            "R277: settings-panel backdrop 必须 delegate 到 this.hideSettings()",
        )


if __name__ == "__main__":
    unittest.main()
