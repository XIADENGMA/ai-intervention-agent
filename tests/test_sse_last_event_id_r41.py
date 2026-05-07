"""R40-S2 / R41 Last-Event-ID resume 端到端契约锁。

R40-S2 的设计目标是在不增加 server-side 状态机复杂度的前提下，让客户端在
**短暂断网 / VSCode webview 切换 / iOS PWA 后台→前台** 等场景下能"无感"恢复
SSE 推流：

- 服务端 ``_SSEBus`` 维护一个 ``_HISTORY_MAXLEN`` 条的环形缓冲区，emit 时把
  ``(id, payload)`` 写进去，每条事件附带预序列化字符串 ``_serialized``；
- 客户端用 ``Last-Event-ID`` HTTP header（浏览器 EventSource 自动）或
  ``?last_event_id=N`` query（VSCode 插件 / PWA 手动重连路径，浏览器不允许在
  EventSource 上设 custom header）告诉服务端"我看到的最后一条是 N"；
- ``sse_events`` 路由把 token 转成 ``after_id`` 传给 ``_SSEBus.subscribe``，
  subscribe 在拿订阅锁的临界区里把 history 里 ``id > after_id`` 的事件 push
  到新建的 queue，客户端无感补齐；
- 如果 ``after_id`` 已经被 evict 出 buffer（断线时间超出 maxlen 容量），先塞
  一条 ``gap_warning`` 事件（id=-1），让客户端立刻 fetch 全量同步。

为什么单独锁这套行为：

- 涉及多端契约（Python `_SSEBus` + Flask 路由 + 浏览器 `webview-ui.js` +
  PWA `multi_task.js` + Node `extension.ts`），任何一端的"id 字段名 / query
  参数名 / header 名 / gap_warning 事件名"漂移都会让 resume 静默失效——
  客户端连得上 server，但接收不到 history 补发，UI 看起来像"刚断了一下
  现在又活了"，但中间被服务端 emit 出去的事件永久丢失。
- silent failure：失败模式不会立刻可见，要等到极端边界场景（比如笔记本
  合盖几分钟再打开）才会暴露丢事件，回归成本极高。

测试组织：

1. ``TestSSEBusSubscribeWithAfterId`` ─ ``_SSEBus.subscribe(after_id=...)``
   的 4 个边界（None / 落在 history / up-to-date / 太旧）。
2. ``TestSseEventsRouteResumeContract`` ─ 通过 AST + 文本扫描锁住路由层
   的 ``Last-Event-ID`` / ``last_event_id`` 双通道解析、generator 输出
   ``id:`` 行、gap_warning 不污染 ``_lastEventId`` 等不变量。
3. ``TestFrontendResumeLiterals`` ─ 用文本扫描锁住三端前端代码里的关键
   字面量（``_lastEventId`` 变量 / ``last_event_id=`` query / ``gap_warning``
   事件 listener 等），让纯前端 refactor 也无法静默打破契约。
"""

from __future__ import annotations

import itertools
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from web_ui_routes.task import _SSEBus


class TestSSEBusSubscribeWithAfterId(unittest.TestCase):
    """``_SSEBus.subscribe(after_id=...)`` 的 history-aware 补发分支。

    history 模型回顾：
    - emit id 单调递增，从 1 开始（``self._next_id`` 初值 0，emit 先 ``+= 1``）。
    - history 是 deque(maxlen=_HISTORY_MAXLEN)，evict 最早的。
    - subscribe(None) 不动 history；subscribe(after_id=N) 走 history scan。
    """

    def test_subscribe_with_none_does_not_replay(self) -> None:
        """``after_id=None`` 是默认行为，不应回放任何 history。"""
        bus = _SSEBus()
        bus.emit("task_changed", {"task_id": "t1"})
        bus.emit("task_changed", {"task_id": "t2"})

        q = bus.subscribe()  # after_id 默认 None

        # 没事件可消费，q 应是空的
        self.assertTrue(q.empty(), "subscribe(None) 不应补发 history")

    def test_subscribe_with_after_id_in_history_replays_newer_events(self) -> None:
        """``after_id`` 落在 history 范围 → 补发 ``id > after_id`` 的所有事件。"""
        bus = _SSEBus()
        bus.emit("task_changed", {"task_id": "t1"})  # id=1
        bus.emit("task_changed", {"task_id": "t2"})  # id=2
        bus.emit("task_changed", {"task_id": "t3"})  # id=3

        # 客户端说"我看到的最后一条是 1"，应补发 2 和 3
        q = bus.subscribe(after_id=1)

        replayed = []
        while not q.empty():
            replayed.append(q.get_nowait())

        self.assertEqual(
            len(replayed),
            2,
            f"after_id=1 应补发 id=2,3 共 2 条；实际拿到 {len(replayed)} 条",
        )
        self.assertEqual(replayed[0]["id"], 2)
        self.assertEqual(replayed[1]["id"], 3)
        # 补发的 payload 必须含预序列化字符串，零 dumps 给客户端
        self.assertIsNotNone(replayed[0].get("_serialized"))

    def test_subscribe_with_after_id_up_to_date_does_not_replay(self) -> None:
        """``after_id == latest_id`` 客户端是 up-to-date 的，不应补发。"""
        bus = _SSEBus()
        bus.emit("task_changed", {"task_id": "t1"})  # id=1
        bus.emit("task_changed", {"task_id": "t2"})  # id=2

        q = bus.subscribe(after_id=2)

        self.assertTrue(
            q.empty(),
            "after_id 等于 latest_id 时不应补发（客户端已经看过最新事件）",
        )

    def test_subscribe_with_after_id_evicted_emits_gap_warning(self) -> None:
        """``after_id`` 太旧（< oldest_id - 1） → 首条必须是 gap_warning。

        把 ``_HISTORY_MAXLEN`` 撑满 + 余量，让 oldest 被 evict，然后用一个
        比 evict 边界更老的 after_id 调 subscribe。

        关于"补发多少条"
        ---------------
        当 ``_HISTORY_MAXLEN > _QUEUE_MAXSIZE``（默认 128 vs 64），evict
        路径下的补发会因为 queue 满而被截断——这是**有意为之**的设计：
        客户端收到 gap_warning 后会立刻 ``fetch /api/tasks`` 拿全量，补发
        history 本来就是 best-effort 的"额外礼物"，不是 spec 保证。所以这里
        只锁两个不变量：
          1. 第一条必须是 gap_warning（id=-1）
          2. 后续如果有事件，必须是当前 history 的连续前缀（按 id 升序）
        而不强求"全部 history 都补到"。
        """
        bus = _SSEBus()
        # emit 比 history maxlen 多 5 条，强制 evict
        evict_count = bus._HISTORY_MAXLEN + 5
        for i in range(evict_count):
            bus.emit("task_changed", {"task_id": f"t{i}"})

        history = bus.history_snapshot()
        oldest_id = history[0][0]
        self.assertGreater(oldest_id, 1, "前置假设：history 应已 evict 过")

        q = bus.subscribe(after_id=1)

        items: list[dict] = []
        while not q.empty():
            items.append(q.get_nowait())

        self.assertGreater(len(items), 0, "evicted after_id 应至少发一条 gap_warning")
        first = items[0]
        self.assertEqual(
            first.get("type"),
            "gap_warning",
            f"evicted after_id 的首条补发必须是 gap_warning,实际是 {first.get('type')}",
        )
        self.assertEqual(
            first.get("id"),
            -1,
            "gap_warning 必须用哨兵 id=-1，避免被客户端当作 resume 锚点污染 lastEventId",
        )

        replayed_ids = [it["id"] for it in items[1:] if isinstance(it.get("id"), int)]
        if replayed_ids:
            # 必须是当前 history 的连续前缀：从 oldest_id 起，严格 +1 递增。
            self.assertEqual(
                replayed_ids[0],
                oldest_id,
                "补发起点必须是 history 的 oldest_id（不能漏第一条）",
            )
            for prev, curr in itertools.pairwise(replayed_ids):
                self.assertEqual(
                    curr,
                    prev + 1,
                    f"补发必须严格按序 +1（gap-free），断点：{prev} → {curr}",
                )

    def test_subscribe_with_after_id_when_history_empty_does_not_replay(
        self,
    ) -> None:
        """history 空 + 任意 after_id → 不补发也不发 gap_warning。

        这是边界场景：server 刚启动 / history 被清空，客户端拿着旧 token 重连。
        既然 server 没东西可补，就不该假装 evict（容易让客户端误以为丢了东西
        然后疯狂 fetch /api/tasks）。
        """
        bus = _SSEBus()
        # 不 emit 任何事件，history 是空

        q = bus.subscribe(after_id=42)

        self.assertTrue(q.empty(), "history 空时 subscribe(after_id) 应静默不补发")


class TestSseEventsRouteResumeContract(unittest.TestCase):
    """``sse_events`` 路由层契约：双通道解析 + ``id:`` 输出 + gap_warning 守卫。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.task_routes_src = (REPO_ROOT / "web_ui_routes" / "task.py").read_text(
            encoding="utf-8"
        )

    def _get_sse_events_body(self) -> str:
        """切出 ``def sse_events`` 起到下一个 ``def`` 之间的源码。

        切片大小够大（10000）覆盖整段函数 + 装饰器；上界用文件长度兜底。
        """
        idx = self.task_routes_src.find("def sse_events")
        self.assertGreaterEqual(idx, 0, "未找到 def sse_events，请同步本测试")
        # 找下一个同缩进的 def，作为本函数的右边界（兜底用 idx+10000）
        next_def_relative = self.task_routes_src[idx + 1 :].find(
            "\n        @self.app.route"
        )
        if next_def_relative > 0:
            return self.task_routes_src[idx : idx + 1 + next_def_relative]
        return self.task_routes_src[idx : idx + 10000]

    def test_route_reads_last_event_id_from_query(self) -> None:
        """路由必须解析 ``?last_event_id=`` query。"""
        body = self._get_sse_events_body()
        self.assertIn(
            'request.args.get("last_event_id")',
            body,
            "sse_events 必须从 query 读 last_event_id（PWA / 插件主动 reconnect "
            "走的是手动 new EventSource，不会自动注入 Last-Event-ID header）",
        )

    def test_route_reads_last_event_id_from_header(self) -> None:
        """路由必须同时支持 ``Last-Event-ID`` HTTP header。"""
        body = self._get_sse_events_body()
        self.assertIn(
            'request.headers.get("Last-Event-ID")',
            body,
            "sse_events 必须从 header 读 Last-Event-ID（浏览器 EventSource 内置 "
            "auto-retry 时按 HTML Living Standard 自动带这个头）",
        )

    def test_route_passes_after_id_to_subscribe(self) -> None:
        """路由必须把解析后的整数 ``after_id`` 传给 ``_sse_bus.subscribe``。"""
        body = self._get_sse_events_body()
        self.assertIn(
            "_sse_bus.subscribe(after_id=after_id)",
            body,
            "sse_events 必须把解析得到的 after_id 传给 _sse_bus.subscribe",
        )

    def test_generator_emits_id_line_for_positive_event_id(self) -> None:
        """generator 必须为正整数 id 输出 ``id: N`` 行（驱动浏览器 e.lastEventId）。"""
        body = self._get_sse_events_body()
        self.assertIn(
            'f"id: {event_id}\\n"',
            body,
            "generator 必须在事件帧前输出 ``id: N`` 行，否则浏览器 EventSource "
            "拿不到 lastEventId，重连无法 resume",
        )

    def test_generator_skips_id_line_for_non_positive(self) -> None:
        """generator 必须对 id ≤ 0 跳过 ``id:`` 行（gap_warning 用 id=-1）。"""
        body = self._get_sse_events_body()
        self.assertIn(
            "isinstance(event_id, int) and event_id > 0",
            body,
            "generator 必须用 ``event_id > 0`` 守卫保护 id 行输出，避免 "
            "gap_warning(id=-1) 污染客户端 lastEventId 形成死循环",
        )


class TestFrontendResumeLiterals(unittest.TestCase):
    """三端前端代码（webview-ui.js / multi_task.js / extension.ts）的字面量回归。

    这一层用 file-grep，不做任何运行时模拟：
    - 浏览器 EventSource / Node http SSE 的 reconnect 路径用 unit test 模拟
      成本高，且会引入 jsdom 等重型依赖；
    - 真正容易引入回归的是 refactor 时不小心改了 query 名 / 变量名 /
      事件类型名，这种"字面量级漂移"用文本断言 catch 最直接。
    - 任何更深的运行时验证应该叠加 integration test，而不是替换这一层。
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.webview_ui = (
            REPO_ROOT / "packages" / "vscode" / "webview-ui.js"
        ).read_text(encoding="utf-8")
        cls.multi_task = (REPO_ROOT / "static" / "js" / "multi_task.js").read_text(
            encoding="utf-8"
        )
        cls.extension_ts = (
            REPO_ROOT / "packages" / "vscode" / "extension.ts"
        ).read_text(encoding="utf-8")

    # webview-ui.js（VSCode 插件 webview 端）
    def test_webview_ui_tracks_last_event_id(self) -> None:
        self.assertIn("_lastEventId", self.webview_ui)
        self.assertIn("e.lastEventId", self.webview_ui)
        self.assertIn("last_event_id=", self.webview_ui)

    def test_webview_ui_handles_gap_warning(self) -> None:
        self.assertIn("gap_warning", self.webview_ui)
        self.assertIn("'gap_warning'", self.webview_ui)

    # multi_task.js（PWA 端）
    def test_multi_task_tracks_last_event_id(self) -> None:
        self.assertIn("_lastEventId", self.multi_task)
        self.assertIn("e.lastEventId", self.multi_task)
        self.assertIn("last_event_id=", self.multi_task)

    def test_multi_task_handles_gap_warning(self) -> None:
        self.assertIn("gap_warning", self.multi_task)
        self.assertIn("'gap_warning'", self.multi_task)

    # extension.ts（VSCode Node SSE 端）
    def test_extension_ts_tracks_last_event_id(self) -> None:
        self.assertIn("_lastEventId", self.extension_ts)
        self.assertIn("last_event_id=", self.extension_ts)
        # Node 端没有 EventSource 自动 e.lastEventId，必须手动解析 ``id:`` 行
        self.assertIn("'id:'", self.extension_ts)

    def test_extension_ts_sets_last_event_id_header_on_reconnect(self) -> None:
        # SSE 标准 header（HTML Living Standard 4.13.4）：浏览器自动带
        # 但 Node 客户端必须手动设置
        self.assertIn("Last-Event-ID", self.extension_ts)

    def test_extension_ts_handles_gap_warning(self) -> None:
        self.assertIn("gap_warning", self.extension_ts)


if __name__ == "__main__":
    unittest.main()
