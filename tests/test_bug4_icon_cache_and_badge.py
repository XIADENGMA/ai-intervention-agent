"""BUG4 回归契约：图标缓存离线恢复 + 去除 Notification badge + 清理遗留 CSS。

背景：用户报告两个相邻问题：
1. 后台服务中断恢复后，Web UI 图标（favicon / PWA icon）不再显示，
   必须 ``Cmd+Shift+R`` 硬刷新才能恢复。
2. 浏览器通知带"角标"（Web Notification API 的 ``badge`` 字段），
   用户表示视觉噪声不想要。

修复策略：
1. ``notification-service-worker.js`` 的 ``handleCacheFirst`` 在 ``fetch``
   抛 NetworkError 时不再 reject promise，改为先回查 cache 拿 stale 副本，
   若没有则返回 503 ``X-AIIA-SW-Offline`` Response。这样浏览器知道"暂时
   不可用"但不会把资源标记为永久 broken，后端恢复后下次访问会重新拉取。
2. ``web_ui.html`` 中所有 ``/icons/...`` link 加 ``?v={{ version }}``
   cache-busting query，版本号变化时 SW cache key 自然失效。
3. ``notification-manager.js`` 默认不写 ``badge`` 字段到 notificationOptions；
   只有调用方显式传入非空字符串 ``options.badge`` 时才尊重。
4. 顺手清理 ``main.css`` 中遗留的 ``.task-count-badge`` + ``@keyframes
   pulse-badge``（对应 JS 与 DOM 早已移除，构成 dead code）。

本测试通过静态扫描锁住上述契约。
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
STATIC_JS = REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "js"
SW_JS = STATIC_JS / "notification-service-worker.js"
NOTIF_MGR_JS = STATIC_JS / "notification-manager.js"
TEMPLATE_HTML = (
    REPO_ROOT / "src" / "ai_intervention_agent" / "templates" / "web_ui.html"
)
MAIN_CSS = REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "css" / "main.css"
MULTI_TASK_JS = STATIC_JS / "multi_task.js"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _strip_js_comments(source: str) -> str:
    """剥除 JS 单行 ``// ...`` 与块 ``/* ... */`` 注释，保留代码主体。

    用最朴素的字符级状态机，避免引入额外依赖；不处理 regex literal / 模板
    字符串里的 ``//``，但本仓库源码不在 regex / template literal 里写
    ``badge: ...`` 反模式，所以足够安全。
    """
    out: list[str] = []
    i = 0
    n = len(source)
    in_string: str | None = None
    in_line_comment = False
    in_block_comment = False
    while i < n:
        ch = source[i]
        nxt = source[i + 1] if i + 1 < n else ""
        if in_line_comment:
            if ch == "\n":
                in_line_comment = False
                out.append(ch)
        elif in_block_comment:
            if ch == "*" and nxt == "/":
                in_block_comment = False
                i += 1
        elif in_string is not None:
            out.append(ch)
            if ch == "\\":
                if i + 1 < n:
                    out.append(source[i + 1])
                    i += 1
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
                out.append(ch)
            else:
                out.append(ch)
        i += 1
    return "".join(out)


class TestServiceWorkerOfflineResilient(unittest.TestCase):
    """``handleCacheFirst`` 必须在 ``fetch`` 抛错时降级到 503 兜底，
    而非 reject promise（后者会让浏览器标记资源 broken）。"""

    def setUp(self) -> None:
        self.source = _read(SW_JS)

    def test_handle_cache_first_wraps_fetch_in_try_catch(self) -> None:
        """``handleCacheFirst`` 内部的 ``fetch(request)`` 必须被 try/catch 包裹。"""
        # 锁住"网络拉取 + 异步写 cache"段落里有 try { networkResponse = await fetch
        match = re.search(
            r"function\s+handleCacheFirst\(\s*request\s*\)\s*\{(?P<body>.*?)\n\}\s*\n",
            self.source,
            re.DOTALL,
        )
        assert match is not None, "无法定位 handleCacheFirst 函数体；测试需要更新正则"
        body = match.group("body")
        # 锁住关键模式：try { networkResponse = await fetch(request) }
        self.assertRegex(
            body,
            r"try\s*\{[^}]*networkResponse\s*=\s*await\s+fetch\(request\)",
            "handleCacheFirst 中 fetch(request) 必须包裹在 try/catch 内，"
            "否则离线场景下 promise reject 会让浏览器把图标标记为永久失败",
        )

    def test_offline_fallback_returns_503_not_reject(self) -> None:
        """fetch 失败兜底必须用 ``makeOfflineResponse`` 返回 503，而非 throw。"""
        self.assertIn(
            "makeOfflineResponse(",
            self.source,
            "SW 必须暴露 makeOfflineResponse helper 用于离线兜底",
        )
        # makeOfflineResponse 必须返回 status 503
        match = re.search(
            r"function\s+makeOfflineResponse\([^)]*\)\s*\{(?P<body>.*?)\n\}\s*\n",
            self.source,
            re.DOTALL,
        )
        assert match is not None, "找不到 makeOfflineResponse 函数定义"
        body = match.group("body")
        self.assertIn(
            "status: 503",
            body,
            "makeOfflineResponse 必须返回 status: 503（Service Unavailable）"
            "而非 404，避免浏览器把资源标记为永久缺失",
        )

    def test_offline_response_carries_diagnostic_header(self) -> None:
        """503 Response 应带 ``X-AIIA-SW-Offline`` header，便于排查与监控。"""
        self.assertIn(
            "X-AIIA-SW-Offline",
            self.source,
            "离线兜底 Response 应带 X-AIIA-SW-Offline 诊断 header",
        )

    def test_documents_bug4(self) -> None:
        self.assertIn(
            "BUG4",
            self.source,
            "SW 中应有 BUG4 锚点注释，便于后续维护者追溯设计动机",
        )


class TestHtmlIconCacheBusting(unittest.TestCase):
    """所有 ``/icons/...`` link 必须带 ``?v={{ version }}`` query。"""

    def setUp(self) -> None:
        self.source = _read(TEMPLATE_HTML)

    def test_all_icon_links_have_cache_bust_query(self) -> None:
        # 匹配所有 href="/icons/..." 模式
        hrefs = re.findall(r'href="(/icons/[^"]+)"', self.source)
        self.assertGreater(
            len(hrefs),
            0,
            "web_ui.html 应至少声明一个 /icons/... link（favicon / apple-touch-icon 等）",
        )
        for href in hrefs:
            self.assertIn(
                "?v={{ version }}",
                href,
                f"图标 href {href!r} 必须带 ?v={{{{ version }}}} cache-busting query，"
                "否则 service worker cache-first 会永久卡住旧版本",
            )

    def test_manifest_link_no_cache_bust(self) -> None:
        """``manifest.webmanifest`` link 不需要 cache-busting（route 级 1h cache）。"""
        # 仅断言 manifest link 仍存在；不强制其有/无 ?v 查询
        self.assertRegex(
            self.source,
            r'<link\s+rel="manifest"\s+href="/manifest\.webmanifest"',
            "manifest link 应保留（与 PWA 安装相关）",
        )


class TestNotificationManagerNoDefaultBadge(unittest.TestCase):
    """``notification-manager.js`` 默认不写 badge 字段；调用方显式传非空字符串才写。"""

    def setUp(self) -> None:
        self.source = _read(NOTIF_MGR_JS)

    def test_no_unconditional_badge_assignment(self) -> None:
        """禁止 ``badge: badge || this.config.icon`` 这种无条件兜底赋值。

        匹配前先剥除注释，避免误命中"BUG4 修复说明"里引用的反模式字符串。
        """
        code = _strip_js_comments(self.source)
        self.assertNotRegex(
            code,
            r"badge:\s*badge\s*\|\|\s*this\.config\.icon",
            "禁止 ``badge: badge || this.config.icon`` 模式（BUG4 历史 bug 位置）；"
            "默认不应写 badge 字段，否则 Android Chrome 会显示用户不想要的角标",
        )

    def test_badge_assignment_is_conditional(self) -> None:
        """badge 写入必须走"调用方显式传入非空字符串"的条件分支。"""
        # 匹配模式：if (typeof badge === 'string' && badge) { notificationOptions.badge = badge }
        self.assertRegex(
            self.source,
            r"if\s*\(\s*typeof\s+badge\s*===\s*['\"]string['\"]\s*&&\s*badge\s*\)",
            "badge 应通过 ``if (typeof badge === 'string' && badge)`` 守卫"
            "条件写入，避免默认值污染",
        )

    def test_documents_bug4(self) -> None:
        self.assertIn(
            "BUG4",
            self.source,
            "notification-manager.js 应有 BUG4 注释锚点说明 badge 移除原因",
        )


class TestCssLegacyBadgePurged(unittest.TestCase):
    """``main.css`` 中遗留的 ``.task-count-badge`` + ``@keyframes pulse-badge`` 必须被清除。"""

    def setUp(self) -> None:
        self.source = _read(MAIN_CSS)

    def test_task_count_badge_selector_removed(self) -> None:
        self.assertNotRegex(
            self.source,
            r"\.task-count-badge\s*\{",
            "main.css 中 ``.task-count-badge`` 选择器应已被移除（dead code，"
            "对应 DOM/JS 早已删除）",
        )

    def test_pulse_badge_keyframes_removed(self) -> None:
        self.assertNotRegex(
            self.source,
            r"@keyframes\s+pulse-badge\s*\{",
            "main.css 中 ``@keyframes pulse-badge`` 应已被移除（对应"
            "``.task-count-badge`` 选择器已删，keyframes 失去意义）",
        )


class TestMultiTaskJsCleanedUp(unittest.TestCase):
    """``multi_task.js`` 中 ``updateTasksStats`` 内的"旧代码已注释"块应被清理。"""

    def setUp(self) -> None:
        self.source = _read(MULTI_TASK_JS)

    def test_no_commented_out_badge_block(self) -> None:
        # 锁住具体的注释块字符串
        self.assertNotIn(
            "旧代码已注释（徽章功能已移除）",
            self.source,
            "multi_task.js 中 updateTasksStats 的"
            '"旧代码已注释" 块应被清理（dead comment 增加阅读负担）',
        )

    def test_update_tasks_stats_still_exists_as_stub(self) -> None:
        """``updateTasksStats`` 函数本身应保留（兼容 stub），避免破坏现有调用。"""
        self.assertIn(
            "function updateTasksStats(",
            self.source,
            "updateTasksStats 函数应保留（fetchAndApplyTasks 等仍可能调用）",
        )


class TestFaviconDynamicBadgeRemoved(unittest.TestCase):
    """``multi_task.js`` 中 favicon 动态角标（``updateFaviconBadge`` /
    ``_faviconState`` / ``_loadOriginalFavicon``）必须被完整移除。

    背景：cycle-22 用户反馈「favicon 上的红色任务数角标我不喜欢，请去除」。
    旧实现用 Canvas 把任务计数画到 favicon 的右上角再 ``toDataURL`` 替换
    ``<link rel="icon">`` 的 href，视觉噪声大且与 SW 缓存策略冲突。

    锁住三条 invariant：
    1. 函数定义 ``updateFaviconBadge`` 不存在；
    2. 内部状态 ``_faviconState`` 不存在；
    3. 内部辅助 ``_loadOriginalFavicon`` 不存在；
    4. 也无 minified 调用残留（``multi_task.min.js``）。
    防止未来 rebase / cherry-pick 把 v1.7.10 之前的 badge 实现意外带回。
    """

    def setUp(self) -> None:
        self.source = _read(MULTI_TASK_JS)
        self.min_source = _read(STATIC_JS / "multi_task.min.js")

    def test_updateFaviconBadge_function_absent(self) -> None:
        self.assertNotIn(
            "updateFaviconBadge",
            self.source,
            "multi_task.js 不应再有 ``updateFaviconBadge`` 函数或调用 "
            "(BUG4 用户偏好：favicon 不要红色角标)",
        )

    def test_faviconState_object_absent(self) -> None:
        self.assertNotIn(
            "_faviconState",
            self.source,
            "multi_task.js 不应再有 ``_faviconState`` 状态对象 "
            "(配套于 updateFaviconBadge 一并清理)",
        )

    def test_loadOriginalFavicon_helper_absent(self) -> None:
        self.assertNotIn(
            "_loadOriginalFavicon",
            self.source,
            "multi_task.js 不应再有 ``_loadOriginalFavicon`` 辅助函数 "
            "(配套于 updateFaviconBadge 一并清理)",
        )

    def test_minified_also_clean(self) -> None:
        """``multi_task.min.js`` 也必须重 minify 干净，避免 stale 产物
        让浏览器继续加载老的角标逻辑。"""
        self.assertNotIn(
            "updateFaviconBadge",
            self.min_source,
            "multi_task.min.js 残留旧的 updateFaviconBadge —— "
            "需要重新跑 scripts/minify_assets.py",
        )
        self.assertNotIn(
            "_faviconState",
            self.min_source,
            "multi_task.min.js 残留旧的 _faviconState —— "
            "需要重新跑 scripts/minify_assets.py",
        )


if __name__ == "__main__":
    unittest.main()
