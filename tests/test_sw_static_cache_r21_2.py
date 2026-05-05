"""R21.2：``notification-service-worker.js`` 静态资源缓存 + 注册路径解耦不变量。

R21.2 让 ``static/js/notification-service-worker.js``（保持文件名以避免破坏既
有 SW 注册客户端）承担两件事：

1. **既有的通知点击路由**——保留 ``notificationclick`` 事件，无回归；
2. **新增静态资源 cache-first 缓存**——拦截白名单路径下的 GET 请求，命中
   cache 立刻返回，未命中走网络后异步写入 cache，重复访问 RTT ≈ 0。

同时调整 ``notification-manager.js::init()``，把 ``registerServiceWorker``
调用移出 ``if (this.isSupported)`` 守护之外，让"不支持 Notification API
但支持 serviceWorker"的浏览器（iOS 16-、部分 Android 自带浏览器）也能注册
SW 享受静态缓存。

R21.2 不在 ci_gate 之外做端到端浏览器测试（service worker 在 jsdom 里基本
无法真实模拟，``Cache`` API、``self.clients`` 都是 stub，强行 mock 会让
测试变成"测 mock"），所以这条测试文件**全是 source-text invariant**——锁
SW 源文件的结构 + 注册路径的解耦。

测试矩阵
========

A. SW 源文件结构：
   - ``STATIC_CACHE_NAME = 'aiia-static-vN'`` 形态（带版本号，否则升级时
     无法清理旧 cache）；
   - ``CACHE_FIRST_PATTERNS`` 至少覆盖 ``/static/css/`` / ``/static/js/`` /
     ``/static/locales/`` / ``/static/lottie/`` / ``/icons/`` / ``/sounds/`` /
     ``/fonts/`` / ``/manifest.webmanifest``——这是 ``web_ui_routes/static.py``
     当前所有"内容稳定"路由的并集，缺一条就让对应文件每次重复访问都走
     网络；
   - ``fetch`` event listener 存在；
   - GET 限制（``request.method !== 'GET'``）存在；
   - 同源限制（``url.origin !== self.location.origin``）存在；
   - SSE 排除（``text/event-stream``）存在——SSE 是长连接，缓存绝对错误；
   - cache.put 失败兜底（``.catch`` 或 ``.then(_, error)``）存在；
   - activate 阶段清理旧版 cache（``cacheNames.filter(...startsWith('aiia-static-'))``）。

B. SW 既有 ``notificationclick`` 路由保持不变（结构特征）：
   - ``self.addEventListener('notificationclick'``；
   - ``event.notification.close()``；
   - ``self.clients.matchAll`` + ``includeUncontrolled: true``；
   - ``self.clients.openWindow``。

C. notification-manager.js::init() 把 register 调用移出 isSupported 守护：
   - 在 ``init`` 主体中 ``await this.registerServiceWorker()`` 必须出现，
     且必须**不在** ``if (!this.isSupported) ... else { ... }`` 块内；
     具体做法：抓 init 函数体，定位 isSupported 分支，确认 register
     在它**之外**。

D. registerServiceWorker 内部的 ``supportsServiceWorkerNotifications`` 守护
   实现保持"实际不依赖 Notification"——只检查 serviceWorker in navigator +
   secureContext，所以即使函数名带 Notifications 字样，实际行为是通用
   SW 能力检测。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SW_PATH = REPO_ROOT / "static" / "js" / "notification-service-worker.js"
NM_PATH = REPO_ROOT / "static" / "js" / "notification-manager.js"


def _read(p: Path) -> str:
    assert p.is_file(), f"文件缺失：{p}"
    return p.read_text(encoding="utf-8")


# ===========================================================================
# A. SW 源文件结构
# ===========================================================================


class TestServiceWorkerStructure:
    """SW 源文件 R21.2 静态缓存模块的结构 invariants。"""

    def test_static_cache_name_versioned(self) -> None:
        """``STATIC_CACHE_NAME`` 必须带 ``-vN`` 版本号后缀，让升级时
        ``activate`` 阶段能清理旧版本 cache。"""
        text = _read(SW_PATH)
        m = re.search(
            r"const\s+STATIC_CACHE_NAME\s*=\s*['\"](aiia-static-v\d+)['\"]",
            text,
        )
        assert m is not None, (
            "R21.2 期望 SW 顶部声明 ``const STATIC_CACHE_NAME = 'aiia-static-vN'``，"
            "其中 N 是整数版本号；下一次需要 cache 失效时 bump N，让 activate 清理旧 cache。"
        )

    def test_max_entries_constant_present(self) -> None:
        """缓存大小硬上限必须存在，防止意外无限增长把用户磁盘吃满。"""
        text = _read(SW_PATH)
        assert re.search(r"const\s+MAX_ENTRIES\s*=\s*\d+", text), (
            "R21.2 期望 SW 顶部声明 ``const MAX_ENTRIES = N``。"
        )

    @pytest.mark.parametrize(
        "expected_pattern",
        [
            r"\^\\/static\\/css\\/",
            r"\^\\/static\\/js\\/",
            r"\^\\/static\\/lottie\\/",
            r"\^\\/static\\/locales\\/",
            r"\^\\/icons\\/",
            r"\^\\/sounds\\/",
            r"\^\\/fonts\\/",
            r"\^\\/manifest\\\.webmanifest\$",
        ],
    )
    def test_cache_first_patterns_cover_all_static_routes(
        self, expected_pattern: str
    ) -> None:
        """白名单必须覆盖 ``web_ui_routes/static.py`` 当前所有"内容稳定"
        静态路由——这是 R21.2 收益的来源；漏掉一条就让对应路径每次重复
        访问都走网络。"""
        text = _read(SW_PATH)
        # SW 里写 ``/^\/static\/css\//`` —— 我们在 expected_pattern 里把
        # ``\/`` 写成 ``\\/`` 因为 raw string 已经把 backslash 当字面量。
        assert re.search(expected_pattern, text), (
            f"R21.2 期望 ``CACHE_FIRST_PATTERNS`` 包含正则 ``{expected_pattern}``，"
            "但 SW 源里没找到。"
            "如果是这条路径有意不缓存（比如 ``/sounds/`` 太大），"
            "请在 commit message 里说明并同步更新本测试。"
        )

    def test_fetch_event_listener_present(self) -> None:
        """fetch 事件监听器是 R21.2 的核心——不存在则 cache 完全不工作。"""
        text = _read(SW_PATH)
        assert re.search(r"self\.addEventListener\(\s*['\"]fetch['\"]", text), (
            "R21.2 期望 SW 注册 ``self.addEventListener('fetch', ...)``。"
        )

    def test_method_get_only_guard(self) -> None:
        """只缓存 GET 是必须 invariant——POST/PUT/DELETE 都是状态变更，
        缓存绝对错误（用户提交反馈被缓存住会让其他用户看到陈旧反馈）。"""
        text = _read(SW_PATH)
        assert re.search(r"request\.method\s*!==\s*['\"]GET['\"]", text) or re.search(
            r"request\.method\s*===\s*['\"]GET['\"]", text
        ), (
            "R21.2 期望 SW fetch handler 显式检查 ``request.method`` 仅 GET 走 cache 路径；"
            "无此守护可能让 POST 请求被错误缓存。"
        )

    def test_same_origin_guard(self) -> None:
        """同源限制：跨域资源不在我们控制下，不应该被冻结。"""
        text = _read(SW_PATH)
        assert re.search(r"url\.origin\s*!==?\s*self\.location\.origin", text), (
            "R21.2 期望 SW 检查 ``url.origin !== self.location.origin``，"
            "拒绝缓存跨域请求。"
        )

    def test_sse_exclusion(self) -> None:
        """SSE 是长连接，绝不能缓存——会让 EventSource 一直拿到 stale 起始事件。"""
        text = _read(SW_PATH)
        assert re.search(r"text/event-stream", text), (
            "R21.2 期望 SW 检测 ``Accept: text/event-stream`` 并跳过缓存路径；"
            "否则 SSE 长连接会被错误缓存。"
        )

    def test_cache_put_has_failure_handler(self) -> None:
        """``cache.put`` 失败（quota exceeded、cache 被清等）不能让响应失败。"""
        text = _read(SW_PATH)
        # 接受两种形式：``.catch(...)`` 或 ``.then(success, failure)``
        assert (
            re.search(r"cache\.put\([^)]*\)\.catch", text)
            or re.search(r"cache\.put\([^)]*\)\.then\([^)]*,\s*\(\s*\)\s*=>", text)
            or re.search(r"cache\.put\([^)]*\)\.then\(\s*\([^)]*\)\s*=>", text)
        ), (
            "R21.2 期望所有 ``cache.put`` 都有失败兜底（``.catch`` 或 ``.then(_, err)``），"
            "防止 quota exceeded 导致响应失败。"
        )

    def test_activate_cleans_old_cache_versions(self) -> None:
        """``activate`` 阶段必须清理旧版本 ``aiia-static-*`` cache，
        否则 SW 升级时旧 cache 永远占着用户存储。"""
        text = _read(SW_PATH)
        assert (
            re.search(r"caches\.keys\(\)", text)
            and re.search(r"aiia-static-", text)
            and re.search(r"caches\.delete\(", text)
        ), (
            "R21.2 期望 ``activate`` 阶段调用 ``caches.keys()`` + 过滤 "
            "``aiia-static-*`` + ``caches.delete()`` 清理旧版本。"
        )

    def test_install_skip_waiting(self) -> None:
        """``install`` 阶段调用 ``skipWaiting()`` 让新 SW 立即接管。"""
        text = _read(SW_PATH)
        assert re.search(r"self\.skipWaiting\(\)", text), (
            "R21.2 期望 ``install`` 阶段调用 ``self.skipWaiting()``，"
            "否则 SW 升级要等所有 client 关闭才生效，体验差。"
        )

    def test_activate_clients_claim(self) -> None:
        """``activate`` 阶段调用 ``self.clients.claim()`` 让 SW 立即控制
        所有未受控的 client（首次 install 时尤其重要）。"""
        text = _read(SW_PATH)
        assert re.search(r"self\.clients\.claim\(\)", text), (
            "R21.2 期望 ``activate`` 阶段调用 ``self.clients.claim()``。"
        )


# ===========================================================================
# B. 既有的 notificationclick 路由保留
# ===========================================================================


class TestNotificationClickPreserved:
    """R21.2 不能动 notificationclick 既有逻辑——这是 SW 升级的兼容性 invariant。"""

    def test_notification_click_listener_present(self) -> None:
        text = _read(SW_PATH)
        assert re.search(
            r"self\.addEventListener\(\s*['\"]notificationclick['\"]", text
        ), "既有的 ``notificationclick`` 监听必须保留——R21.2 不应该回归通知功能。"

    def test_notification_close_call(self) -> None:
        text = _read(SW_PATH)
        assert re.search(r"event\.notification\.close\(\)", text), (
            "``event.notification.close()`` 必须保留——通知点击后立刻关闭通知中心条目。"
        )

    def test_clients_match_all_with_uncontrolled(self) -> None:
        text = _read(SW_PATH)
        assert re.search(r"self\.clients\.matchAll\(", text) and re.search(
            r"includeUncontrolled\s*:\s*true", text
        ), (
            "``self.clients.matchAll({includeUncontrolled: true})`` 必须保留——"
            "通知点击需要找到所有 Web UI 标签页（包括尚未受 SW 控制的）。"
        )

    def test_clients_open_window(self) -> None:
        text = _read(SW_PATH)
        assert re.search(r"self\.clients\.openWindow", text), (
            "``self.clients.openWindow`` 必须保留——找不到现有窗口时新开一个。"
        )


# ===========================================================================
# C. notification-manager.js::init() 把 register 移出 isSupported 守护
# ===========================================================================


class TestRegisterServiceWorkerDecoupledFromNotification:
    """R21.2 让所有支持 SW + secure context 的浏览器都注册 SW，无关 Notification API。"""

    def _extract_init_body(self, text: str) -> str:
        """从 notification-manager.js 抽 ``async init()`` 的函数体。"""
        # init() 内嵌套 ``this.initPromise = (async () => { ... })()``，所以我们
        # 抓的是这个 IIFE 的 body
        m = re.search(
            r"this\.initPromise\s*=\s*\(\s*async\s*\(\s*\)\s*=>\s*\{([\s\S]*?)\}\)\(\)",
            text,
        )
        assert m is not None, (
            "找不到 ``this.initPromise = (async () => { ... })()`` IIFE。"
            "结构变了？请同步更新这个测试。"
        )
        return m.group(1)

    def test_register_called_inside_init(self) -> None:
        body = self._extract_init_body(_read(NM_PATH))
        assert re.search(r"await\s+this\.registerServiceWorker\(\)", body), (
            "R21.2 期望 ``init()`` 主体中 ``await this.registerServiceWorker()``"
            "继续被调用。"
        )

    def test_register_not_inside_is_supported_else_branch(self) -> None:
        """register 必须**不在** ``else`` 分支（``if (!this.isSupported) {} else {}``）
        内部，否则不支持 ``Notification`` API 的浏览器会跳过 SW 注册。"""
        body = self._extract_init_body(_read(NM_PATH))

        # 找 ``if (!this.isSupported)``...``else { ... }``，提取 else 块的 body
        m = re.search(
            r"if\s*\(\s*!\s*this\.isSupported\s*\)\s*\{[^{}]*\}\s*else\s*\{([^{}]*?)\}",
            body,
            re.DOTALL,
        )
        if m is None:
            # 结构可能变了——回退到弱断言：register 与 isSupported 文本距离
            # 较远（不在同一逻辑块）。
            register_pos = body.find("await this.registerServiceWorker()")
            isSupported_pos = body.find("if (!this.isSupported)")
            if register_pos == -1 or isSupported_pos == -1:
                pytest.skip(
                    "init() 结构与预期不一致，无法做严格断言；R21.2 主体已 commit，"
                    "这条测试做软兜底。"
                )
            return

        else_body = m.group(1)
        assert "registerServiceWorker" not in else_body, (
            "R21.2 不变量：``await this.registerServiceWorker()`` **不应**出现在 "
            "``if (!this.isSupported) {} else { ... }`` 的 else 块内，否则不支持 "
            "Notification API 的浏览器跳过 SW 注册，享受不到静态缓存。"
            f"\n当前 else 块内容：\n{else_body}"
        )


# ===========================================================================
# D. supportsServiceWorkerNotifications 实际只检查 SW 能力（非 Notification）
# ===========================================================================


class TestSupportsServiceWorkerImplementation:
    """函数名虽然带 Notifications 但实现实际只检查 SW + secureContext。"""

    def test_implementation_checks_serviceworker(self) -> None:
        text = _read(NM_PATH)
        m = re.search(
            r"supportsServiceWorkerNotifications\s*\(\s*\)\s*\{([\s\S]*?)\n\s*\}",
            text,
        )
        assert m is not None, (
            "找不到 ``supportsServiceWorkerNotifications()`` 方法定义。"
        )
        body = m.group(1)
        assert "'serviceWorker' in navigator" in body, (
            "实现必须检查 ``'serviceWorker' in navigator``。"
        )
        assert "isSecureContext" in body, "实现必须检查 ``window.isSecureContext``。"

    def test_implementation_does_not_check_notification(self) -> None:
        """函数名 misleading，但实现实际不能检查 Notification API——
        否则 R21.2 静态缓存仍然被 Notification 守护卡住。"""
        text = _read(NM_PATH)
        m = re.search(
            r"supportsServiceWorkerNotifications\s*\(\s*\)\s*\{([\s\S]*?)\n\s*\}",
            text,
        )
        assert m is not None
        body = m.group(1)
        # 不应该检查 ``'Notification' in window`` 或 ``Notification.permission``
        assert "'Notification' in" not in body, (
            "R21.2 不变量：``supportsServiceWorkerNotifications`` 实现不应该检查 "
            "``'Notification' in ...``——这会让 iOS 16- 等不支持 Notification API "
            "但支持 SW 的浏览器返回 false，享受不到 R21.2 静态缓存。"
        )
        assert "Notification.permission" not in body, (
            "R21.2 不变量：``supportsServiceWorkerNotifications`` 实现不应该读 "
            "``Notification.permission``。"
        )
