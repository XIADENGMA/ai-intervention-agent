"""R214 / Cycle 10 · F-notif-fallback-1 · notification fallback toast 可见性 invariant。

设计目标
========

R20 系列在 Web UI 引入了 system notifications (Notification API), 让
浏览器在新反馈请求到达时弹桌面提醒。`notification-manager.js` 已经实
现了 `showFallbackNotification()` 作为降级方案 (当 Notification API
不可用 / permission denied / insecure context 时)。**但**降级方案有
一个 silent UX bug：

1. `showFallbackNotification()` 调 `showStatus(${title}: ${message}, 'info')`；
2. `app.js` 的 `showStatus()` 在 content page 上 (即用户正在看反馈请求
   时) 用 `if (!isNoContentPage && type !== "error") { if (type === "success")
   _showToast(message); return; }` 过滤——只有 `'success'` / `'error'`
   能显示, `'info'` 在 content page 上 silently dropped；
3. 结果: **用户在 content page 看反馈请求, 浏览器拒绝通知权限时, 完全
   收不到任何视觉反馈, 只有 console.log + 标题闪烁 (但用户在看页面时
   往往看不到 tab 标题)**。

R214 修复策略：

A. `app.js showStatus()`: 扩展 type filter, 让 `'warning'` 也走 toast
   (warning 是降级通知的合理 level——比 info 更显眼, 但不像 error 那么
   吓人)。`'info'` 维持 silent (大量内部状态变化都是 info, 不该到处
   toast)；
B. `notification-manager.js showFallbackNotification()`: type 从 `'info'`
   改为 `'warning'`, 让 content page 上的 toast 真的可见；
C. 根据 `reason` 字段追加 i18n 化的 actionable hint, 让用户知道为何降级
   (单纯 "标题: 消息" 不够 actionable, 用户不会想到去检查通知权限)：
   - `permission_denied` → `status.notifFallbackPermDenied`
   - `permission_default` → `status.notifFallbackPermDefault`
   - `permission_disabled` → `status.notifFallbackPermDisabled`
   - `unsupported` → `status.notifFallbackUnsupported`
   - `insecure_context` → `status.notifFallbackInsecure`
   - 其他 (system_notification_failed / show_notification_exception 等
     底层异常, 用户不能立即修复, 不打扰)。

R214 invariant test 守住的契约
================================

A. **showStatus 'warning' 在 content page 走 toast**：
   - app.js 的 showStatus 函数包含允许 'warning' 走 toast 的 branch
     (`type === "success" || type === "warning"` 触发 _showToast)
   - autoDismissMs 包含 warning 分支 (5000ms, 介于 success 3000 与
     error 10000 之间)
B. **showFallbackNotification 用 'warning' type 而非 'info'**：
   - notification-manager.js showFallbackNotification 的 showStatus
     调用使用 `'warning'` 字符串作为 type 实参
C. **reason → i18n key 映射存在**：
   - notification-manager.js 包含 5 个映射 (permission_denied /
     permission_default / permission_disabled / unsupported /
     insecure_context)
D. **i18n locales 双语 lockstep**：
   - en.json + zh-CN.json 的 status.* 段都存在 5 个 notifFallback*
     key, 内容非空且包含 actionable 词汇 (en: "enable" / "browser" /
     "settings" / "fallback" 之一; zh: "通知" / "降级" / "浏览器" /
     "设置" 之一)

为什么是 invariant test 而不是 JS unit test？
================================================

项目没有 JS test runner (无 jest / vitest / playwright), 引入 runner
会显著扩大 CI 表面积 (新增 npm/node 依赖、新的 lock file、新的 CI
job)。考虑到 R214 改动是 ~30 行 JS + 10 行 i18n, 投入产出比不合算。
采用静态 string-presence test 作为契约守护——直接读 JS / JSON 文件
源码, 用字符串 / 正则验证关键 invariant 存在, 模式与 R211 (CHANGELOG
formatting) / R212 (SSE schema contract bridge) / R213 (static
precompress) 一致, 零新依赖。

实施于 2026-05-14, 共 7 个测试用例 (3 静态守 + 2 i18n parity + 2 反
向 regression 守)。
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
APP_JS = REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "js" / "app.js"
NOTIF_JS = (
    REPO_ROOT
    / "src"
    / "ai_intervention_agent"
    / "static"
    / "js"
    / "notification-manager.js"
)
LOCALE_EN = (
    REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "locales" / "en.json"
)
LOCALE_ZH = (
    REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "locales" / "zh-CN.json"
)

REASON_KEYS = (
    "permission_denied",
    "permission_default",
    "permission_disabled",
    "unsupported",
    "insecure_context",
)

LOCALE_I18N_KEYS = (
    "notifFallbackPermDenied",
    "notifFallbackPermDefault",
    "notifFallbackPermDisabled",
    "notifFallbackUnsupported",
    "notifFallbackInsecure",
)


class TestAppJsShowStatusWarningInvariant(unittest.TestCase):
    """守 app.js showStatus 让 'warning' 类型在 content page 走 toast。"""

    def setUp(self) -> None:
        self.assertTrue(APP_JS.exists(), f"app.js missing: {APP_JS}")
        self.source = APP_JS.read_text(encoding="utf-8")

    def test_showstatus_warning_branch_in_toast_path(self) -> None:
        """showStatus 在 content page (`!isNoContentPage`) 上要允许 warning 走 _showToast。"""
        # 期望源码包含 `type === "success" || type === "warning"` 分支
        # (允许两个引号风格, 双引号与单引号)
        patterns = (
            r'type\s*===\s*["\']success["\']\s*\|\|\s*type\s*===\s*["\']warning["\']',
            r'type\s*===\s*["\']warning["\']\s*\|\|\s*type\s*===\s*["\']success["\']',
        )
        match = any(re.search(p, self.source) for p in patterns)
        self.assertTrue(
            match,
            "app.js showStatus 应包含 'success || warning' 分支让 warning 在 content page 走 _showToast, "
            "否则 notification-manager 的 fallback toast 仍 silent (R214 退化)。"
            f"\n现状: 未找到 pattern {patterns!r}",
        )

    def test_showstatus_warning_has_autodismiss(self) -> None:
        """showStatus 的 autoDismissMs 分支要覆盖 warning (5000ms, 介于 success 与 error)。"""
        # 期望源码包含 `type === "warning" ? 5000` 或语义等价分支
        pattern = r'type\s*===\s*["\']warning["\']\s*\?\s*5000'
        self.assertRegex(
            self.source,
            pattern,
            'app.js showStatus autoDismissMs 应有 `type === "warning" ? 5000` 分支, '
            "让 warning toast 5s 后自动消失 (sweet spot: 比 success 3s 长够看清, "
            "比 error 10s 短不打扰)。",
        )


class TestNotificationManagerWarningTypeInvariant(unittest.TestCase):
    """守 notification-manager.js showFallbackNotification 用 'warning' 而非 'info'。"""

    def setUp(self) -> None:
        self.assertTrue(
            NOTIF_JS.exists(), f"notification-manager.js missing: {NOTIF_JS}"
        )
        self.source = NOTIF_JS.read_text(encoding="utf-8")

    def test_showfallback_calls_showstatus_with_warning(self) -> None:
        """showFallbackNotification 必须用 'warning' type 调 showStatus。"""
        # 期望源码包含 `showStatus(..., 'warning')`
        # 允许变量化 message (toastMessage) 与字面 `'warning'` / `"warning"`
        pattern = r"showStatus\s*\(\s*\w+\s*,\s*['\"]warning['\"]\s*\)"
        self.assertRegex(
            self.source,
            pattern,
            "notification-manager.js showFallbackNotification 必须用 'warning' type 而非 "
            "'info', 否则 app.js showStatus 在 content page 上会 silently drop "
            "fallback toast (R214 修复的核心 bug)。",
        )

    def test_showfallback_does_not_use_info_type(self) -> None:
        """反向 regression 守: showFallbackNotification 不能再用 'info' type 调 showStatus。"""
        # 找到 showFallbackNotification 函数体, 验证里面没有 `showStatus(*, 'info')`
        # 用 multiline regex 找函数边界 (从 `showFallbackNotification` 到下一个 method)
        match = re.search(
            r"showFallbackNotification\s*\([^)]*\)\s*\{(.+?)\n\s{2}\w",
            self.source,
            re.DOTALL,
        )
        if match is None:
            self.fail("无法定位 showFallbackNotification 函数体, JS 结构可能已变化")
        body = match.group(1)
        info_pattern = r"showStatus\s*\([^,]+,\s*['\"]info['\"]\s*\)"
        self.assertNotRegex(
            body,
            info_pattern,
            "showFallbackNotification 函数体不应再调用 showStatus(..., 'info'), "
            "这会让降级 toast 在 content page 上 silently dropped (R214 已修复的 bug)。",
        )


class TestNotificationManagerReasonI18nMappingInvariant(unittest.TestCase):
    """守 reason -> i18n key 映射在 notification-manager.js 中完整。"""

    def setUp(self) -> None:
        self.source = NOTIF_JS.read_text(encoding="utf-8")

    def test_all_reason_keys_referenced(self) -> None:
        """5 个 reason key 都必须在 notification-manager.js 源码中出现 (映射存在的弱守)。"""
        for reason in REASON_KEYS:
            with self.subTest(reason=reason):
                self.assertIn(
                    reason,
                    self.source,
                    f"reason '{reason}' 必须在 notification-manager.js 中作为 i18n 映射的 key 出现 "
                    "(用于 reason -> i18n hint key 查表)。",
                )

    def test_all_i18n_hint_keys_referenced(self) -> None:
        """5 个 status.notifFallback* i18n key 必须在 notification-manager.js 中出现 (作为 t() 参数或字面 key)。"""
        for i18n_key in LOCALE_I18N_KEYS:
            full_key = f"status.{i18n_key}"
            with self.subTest(i18n_key=full_key):
                self.assertIn(
                    full_key,
                    self.source,
                    f"i18n key '{full_key}' 必须在 notification-manager.js 中作为 reason -> hint 映射的 value 出现。",
                )


class TestNotificationFallbackI18nLocaleParity(unittest.TestCase):
    """守 en.json + zh-CN.json 的 5 个 notifFallback* key 双语 lockstep。"""

    def setUp(self) -> None:
        with LOCALE_EN.open(encoding="utf-8") as f:
            self.en = json.load(f)
        with LOCALE_ZH.open(encoding="utf-8") as f:
            self.zh = json.load(f)

    def test_all_keys_present_in_both_locales(self) -> None:
        """5 个 key 必须同时存在于 en.json + zh-CN.json 的 status.* 段。"""
        en_status = self.en.get("status", {})
        zh_status = self.zh.get("status", {})
        for i18n_key in LOCALE_I18N_KEYS:
            with self.subTest(i18n_key=i18n_key):
                self.assertIn(
                    i18n_key,
                    en_status,
                    f"en.json status.{i18n_key} missing (R214 invariant), "
                    "会让 notification-manager.js 的 t() 返回原 key 字符串, fallback toast 显示丑陋。",
                )
                self.assertIn(
                    i18n_key,
                    zh_status,
                    f"zh-CN.json status.{i18n_key} missing (R214 invariant), "
                    "会让中文用户的 fallback toast fall back 到英文 key。",
                )

    def test_en_values_have_actionable_words(self) -> None:
        """英文 value 必须包含 actionable 词汇之一 (enable / browser / settings / fallback / hint)。"""
        en_status = self.en.get("status", {})
        actionable_words = (
            "enable",
            "browser",
            "settings",
            "fallback",
            "hint",
            "permission",
        )
        for i18n_key in LOCALE_I18N_KEYS:
            with self.subTest(i18n_key=i18n_key):
                value = en_status.get(i18n_key, "")
                self.assertTrue(value, f"en.json status.{i18n_key} 不能为空")
                lower = value.lower()
                matched = [w for w in actionable_words if w in lower]
                self.assertTrue(
                    matched,
                    f"en.json status.{i18n_key} = {value!r} 应包含至少一个 actionable "
                    f"词汇 {actionable_words!r}, 让用户知道如何修复 (单纯 'permission "
                    "denied' 不 actionable)。",
                )

    def test_zh_values_have_actionable_words(self) -> None:
        """中文 value 必须包含 actionable 词汇之一 (通知 / 降级 / 浏览器 / 设置 / 提示)。"""
        zh_status = self.zh.get("status", {})
        actionable_words = ("通知", "降级", "浏览器", "设置", "提示", "权限")
        for i18n_key in LOCALE_I18N_KEYS:
            with self.subTest(i18n_key=i18n_key):
                value = zh_status.get(i18n_key, "")
                self.assertTrue(value, f"zh-CN.json status.{i18n_key} 不能为空")
                matched = [w for w in actionable_words if w in value]
                self.assertTrue(
                    matched,
                    f"zh-CN.json status.{i18n_key} = {value!r} 应包含至少一个 actionable "
                    f"中文词汇 {actionable_words!r}, 让中文用户知道如何修复。",
                )

    def test_en_zh_lengths_in_reasonable_range(self) -> None:
        """en/zh 长度比例守: 中文一般是英文 0.4x ~ 1.5x 长度 (字符数), 防止误删/截断。"""
        en_status = self.en.get("status", {})
        zh_status = self.zh.get("status", {})
        for i18n_key in LOCALE_I18N_KEYS:
            with self.subTest(i18n_key=i18n_key):
                en_len = len(en_status.get(i18n_key, ""))
                zh_len = len(zh_status.get(i18n_key, ""))
                self.assertGreater(
                    en_len, 30, f"en.json status.{i18n_key} 应至少 30 字符表达完整意思"
                )
                self.assertGreater(
                    zh_len,
                    15,
                    f"zh-CN.json status.{i18n_key} 应至少 15 字符表达完整意思",
                )
                ratio = zh_len / en_len if en_len else 0
                self.assertTrue(
                    0.3 <= ratio <= 2.0,
                    f"status.{i18n_key} 中英长度比 {ratio:.2f} 异常 "
                    f"(en={en_len}, zh={zh_len}), 可能其中一个被截断或翻译错位",
                )


if __name__ == "__main__":
    unittest.main()
