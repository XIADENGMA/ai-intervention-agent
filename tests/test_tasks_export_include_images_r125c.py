"""R125c · ``GET /api/tasks/export?include_images=...`` 参数化测试。

背景
----
R125 的 JSON 导出无条件携带 ``result.images[].data``（base64 编码）。
真实场景里：用户为一个 task 上传 3 张高清截图（每张 ~500 KB），
base64 化后约 670 KB / 张，3 task × 3 image ≈ 6 MB JSON。这对"轻量
备份 / 跨设备 sync / 只想看决策路径不需要图"的场景是巨大浪费。
Code Review #2 把这个膨胀风险列为 P1 follow-up。R125c 补 query
参数 ``?include_images=true|false``：

- 默认 ``true`` 与 R125 行为完全一致（向后兼容）；
- ``false`` 时仅保留 ``filename / size / content_type / mime_type``
  元数据，丢弃 base64 ``data``；
- 顶层 payload 加 ``include_images: true|false`` 字段标记，让消费方
  能一眼分辨这是不是"轻量快照"；
- 单 task 的 ``result`` 加 ``images_stripped: true`` 字段标记当条
  result 是不是被剥过的（避免和"用户本来就没传图"混淆）。

测试覆盖五个层面（共 12 cases / 5 invariant classes）：

1.  **`_parse_bool_query` helper 行为** — truthy / falsy / 未知值
    回退到 default 的语义锁定。
2.  **`_strip_images_from_result` helper 行为** — None / 非 dict /
    images 不是 list / images 内有非 dict 异常体的 graceful degrade。
3.  **HTTP 默认行为不变** — `?include_images` 缺省时仍带完整 base64
    （R125 兼容性回归保护）。
4.  **HTTP `include_images=false` 路径** — 响应顶层 `include_images`
    字段为 false、tasks[].result.images_stripped 为 true、images[]
    不含 data 字段。
5.  **HTTP query 解析鲁棒性** — `false / FALSE / 0 / no / off` 都
    被识别为 false；`true / 1 / yes` 都被识别为 true；拼错值
    （`?include_images=foobar`）回退到默认值。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


from ai_intervention_agent.web_ui_routes.task import (  # ty: ignore[unresolved-import]
    _parse_bool_query,
    _strip_images_from_result,
)

# ---------------------------------------------------------------------------
# 1. _parse_bool_query helper
# ---------------------------------------------------------------------------


class TestParseBoolQuery(unittest.TestCase):
    def test_none_returns_default(self) -> None:
        self.assertTrue(_parse_bool_query(None, default=True))
        self.assertFalse(_parse_bool_query(None, default=False))

    def test_truthy_values(self) -> None:
        for v in ("true", "TRUE", "True", "1", "yes", "YES", "on", " on "):
            self.assertTrue(
                _parse_bool_query(v, default=False),
                f"{v!r} 必须解析为 True",
            )

    def test_falsy_values(self) -> None:
        for v in ("false", "FALSE", "False", "0", "no", "NO", "off", " off "):
            self.assertFalse(
                _parse_bool_query(v, default=True),
                f"{v!r} 必须解析为 False",
            )

    def test_unknown_returns_default(self) -> None:
        # 拼错值不应触发异常或翻转语义；按 default 兜底
        for v in ("truee", "noooo", "bool", "", "  "):
            self.assertTrue(
                _parse_bool_query(v, default=True),
                f"{v!r} 应回退到 default=True",
            )
            self.assertFalse(
                _parse_bool_query(v, default=False),
                f"{v!r} 应回退到 default=False",
            )


# ---------------------------------------------------------------------------
# 2. _strip_images_from_result helper
# ---------------------------------------------------------------------------


class TestStripImagesHelper(unittest.TestCase):
    def test_include_images_true_returns_original(self) -> None:
        # 默认路径：原对象按引用返回，零拷贝
        original = {"images": [{"data": "xxx"}]}
        out = _strip_images_from_result(original, include_images=True)
        self.assertIs(out, original, "include_images=True 时应零拷贝直接返回原对象")

    def test_strip_removes_base64_data(self) -> None:
        original = {
            "user_input": "looks good",
            "images": [
                {
                    "data": "AAAA" * 1000,
                    "filename": "img.png",
                    "size": 12345,
                    "content_type": "image/png",
                    "mime_type": "image/png",
                }
            ],
        }
        out = _strip_images_from_result(original, include_images=False)
        assert isinstance(out, dict)
        # 顶层标记
        self.assertTrue(out.get("images_stripped"))
        # images 数组保留 metadata，不含 data
        imgs = out["images"]
        self.assertIsInstance(imgs, list)
        self.assertEqual(len(imgs), 1)
        self.assertNotIn(
            "data",
            imgs[0],
            "include_images=false 路径必须剥掉 base64 data 字段",
        )
        for k in ("filename", "size", "content_type", "mime_type"):
            self.assertEqual(imgs[0].get(k), original["images"][0][k])
        # 原对象不应被改写（浅拷贝原则）
        self.assertEqual(
            original["images"][0]["data"],
            "AAAA" * 1000,
            "原 result 必须保持不可变，避免缓存中的活对象被污染",
        )

    def test_none_result_passes_through(self) -> None:
        self.assertIsNone(_strip_images_from_result(None, include_images=False))

    def test_no_images_field_passes_through(self) -> None:
        original = {"user_input": "no images here"}
        out = _strip_images_from_result(original, include_images=False)
        # 没有 images 字段时应直接返回原对象（既不加 images_stripped 也不抛错）
        self.assertIs(out, original)

    def test_images_not_a_list_passes_through(self) -> None:
        # 异常 result：images 是字符串而非 list 时不应抛错
        original = {"images": "oops not a list"}
        out = _strip_images_from_result(original, include_images=False)
        self.assertIs(out, original)


# ---------------------------------------------------------------------------
# 3-5. HTTP-level integration（与 test_tasks_export_endpoint_r125 同 fixtures）
# ---------------------------------------------------------------------------


class _HttpExportBase(unittest.TestCase):
    """共享 fixtures：真实 WebFeedbackUI + Flask test client + 干净 TaskQueue。"""

    _port: int = 19511
    _ui: Any = None
    _client: Any = None

    @classmethod
    def setUpClass(cls) -> None:
        from ai_intervention_agent.web_ui import WebFeedbackUI

        cls._ui = WebFeedbackUI(
            prompt="r125c base", task_id="r125c-base", port=cls._port
        )
        cls._ui.app.config["TESTING"] = True
        cls._ui.limiter.enabled = False
        cls._client = cls._ui.app.test_client()

    def setUp(self) -> None:
        from ai_intervention_agent.task_queue_singleton import get_task_queue

        get_task_queue().clear_all_tasks()

    def _add_completed_task_with_image(self, task_id: str = "t1") -> None:
        # 走公开 API：add_task → complete_task(result)，与
        # ``test_tasks_export_endpoint_r125.py::_complete_task_with_result``
        # 同模式，但 result 内带一张 base64 图模拟真实 feedback。
        from ai_intervention_agent.task_queue_singleton import get_task_queue

        tq = get_task_queue()
        tq.add_task(task_id=task_id, prompt="please review", auto_resubmit_timeout=240)
        result = {
            "user_input": "looks good",
            "selected_options": [],
            "images": [
                {
                    "data": "AAAA" * 1000,
                    "filename": "x.png",
                    "size": 4000,
                    "content_type": "image/png",
                    "mime_type": "image/png",
                }
            ],
        }
        tq.complete_task(task_id, result)


class TestExportIncludeImagesHttp(_HttpExportBase):
    def test_default_keeps_base64_images(self) -> None:
        # R125 兼容性回归保护：默认（不带参数）仍带完整 base64
        self._add_completed_task_with_image()
        resp = self._client.get("/api/tasks/export?format=json")
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertTrue(body.get("include_images"))
        first_result = body["tasks"][0]["result"]
        self.assertIn("data", first_result["images"][0])
        self.assertNotIn("images_stripped", first_result)

    def test_include_images_false_strips_data(self) -> None:
        self._add_completed_task_with_image()
        resp = self._client.get("/api/tasks/export?format=json&include_images=false")
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertFalse(body.get("include_images"))
        result = body["tasks"][0]["result"]
        self.assertTrue(result.get("images_stripped"))
        self.assertNotIn(
            "data",
            result["images"][0],
            "include_images=false 时 base64 data 必须被剥掉",
        )
        self.assertEqual(result["images"][0]["filename"], "x.png")
        self.assertEqual(result["images"][0]["size"], 4000)


class TestExportIncludeImagesQueryParsing(_HttpExportBase):
    def test_falsy_aliases(self) -> None:
        for v in ("false", "FALSE", "0", "no", "off"):
            resp = self._client.get(f"/api/tasks/export?format=json&include_images={v}")
            self.assertEqual(resp.status_code, 200)
            body = resp.get_json()
            self.assertFalse(
                body.get("include_images"),
                f"include_images={v!r} 必须解析为 False",
            )

    def test_truthy_aliases(self) -> None:
        for v in ("true", "TRUE", "1", "yes", "on"):
            resp = self._client.get(f"/api/tasks/export?format=json&include_images={v}")
            self.assertEqual(resp.status_code, 200)
            body = resp.get_json()
            self.assertTrue(
                body.get("include_images"),
                f"include_images={v!r} 必须解析为 True",
            )

    def test_unknown_value_falls_back_to_default(self) -> None:
        # 拼错时不该 500，按默认 true 兜底
        resp = self._client.get("/api/tasks/export?format=json&include_images=truee")
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertTrue(body.get("include_images"))


if __name__ == "__main__":
    unittest.main()
