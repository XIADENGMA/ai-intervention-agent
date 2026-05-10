"""R139 — Feedback per-task 草稿持久化测试。

R139 把 ``mcp-feedback-enhanced`` v2.4.x 的 "Auto-save drafts" 体验
吸收到本项目 #feedback-text 主反馈输入框：项目内已存在
``window.taskTextareaContents`` 内存字典（``multi_task.js`` 维护，
切换 task 时保留 textarea 内容不丢），但**仅在内存里**——刷新 / 关
闭浏览器 / 进程崩溃后全部丢失。R139 在不侵入既有 ``multi_task.js``
的前提下把 ``taskTextareaContents`` 状态持久化到 localStorage：启动
时一次性 hydrate localStorage → 内存（不覆盖既存项），input 事件
debounce 500ms 写盘，周期性 30s reconcile 兜底程序赋值 / clear /
submit 后清空等非 input 路径。

约束 / 不变式（覆盖 6 类）：

1.  **JS 模块文件存在 + 体积合理** — 模块文件存在；约 200-300 行（实
    际实现 ≈ 270 行），防误删 / 意外膨胀。
2.  **常量值锁定** — STORAGE_KEY / SCHEMA_VERSION / TARGET_ID /
    TTL_MS / MAX_DRAFTS / INPUT_DEBOUNCE_MS / SYNC_INTERVAL_MS 字面
    值不漂移，确保模板 / web_ui.py / 测试三方对齐。
3.  **API 函数签名** — loadAllDrafts / getDraft / saveDraft /
    clearDraft / clearAllDrafts / hydrateMemoryCache /
    reconcileMemoryToStorage / init 全部可见；
    ``window.AIIA_FEEDBACK_DRAFTS`` 暴露完整 API。
4.  **graceful failure** — _isStorageAvailable / _readEnvelope /
    _writeEnvelope / clearAllDrafts 全 try/catch，localStorage 不可
    用 / 损坏 / quota 满时主路径不挂。
5.  **核心逻辑边界** — _normalizeDraft 处理非法 entry / saved_at
    缺失；_applyTtlAndLru 走 TTL 过滤 + LRU 截 50；hydrate 不覆盖
    既存 entry；reconcile 跳过空 text。
6.  **HTML / context 集成** — ``<script>`` 标签带 ``defer`` +
    ``nonce={{ csp_nonce }}`` + ``?v={{ feedback_drafts_version }}``；
    ``_get_template_context`` 用 ``_compute_file_version`` 计算
    ``feedback_drafts_version``。
"""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS_PATH = ROOT / "src/ai_intervention_agent/static/js/feedback_drafts.js"
HTML_PATH = ROOT / "src/ai_intervention_agent/templates/web_ui.html"
WEB_UI_PY = ROOT / "src/ai_intervention_agent/web_ui.py"


def _read_js() -> str:
    return JS_PATH.read_text(encoding="utf-8")


def _read_html() -> str:
    return HTML_PATH.read_text(encoding="utf-8")


# ----------------------------------------------------------------------
# Class 1: JS 模块文件存在 + 体积合理
# ----------------------------------------------------------------------


class TestJsFileExistsAndSize(unittest.TestCase):
    def test_js_file_exists(self) -> None:
        self.assertTrue(
            JS_PATH.exists(),
            f"R139 JS 模块文件必须存在: {JS_PATH}",
        )

    def test_js_file_line_count_in_envelope(self) -> None:
        line_count = len(_read_js().splitlines())
        # 200-330 行：当前 ≈ 270 行，envelope 防误删 / 意外膨胀
        self.assertGreaterEqual(line_count, 200, "R139 JS 模块过短，疑似空壳")
        self.assertLessEqual(line_count, 330, "R139 JS 模块超出预期，疑似膨胀")


# ----------------------------------------------------------------------
# Class 2: 常量值锁定
# ----------------------------------------------------------------------


class TestConstantsLocked(unittest.TestCase):
    def setUp(self) -> None:
        self.js = _read_js()

    def test_storage_key_constant(self) -> None:
        # 与 R130 quick_phrases / R137 textarea-height 同款 aiia.<feature>.v<schema> 命名
        self.assertIn('STORAGE_KEY = "aiia.feedbackDrafts.v1"', self.js)

    def test_schema_version_constant(self) -> None:
        self.assertIn("SCHEMA_VERSION = 1", self.js)

    def test_target_id_constant(self) -> None:
        self.assertIn('TARGET_ID = "feedback-text"', self.js)

    def test_ttl_ms_constant(self) -> None:
        # TTL = 7 天 = 7*24*60*60*1000ms
        self.assertIn(
            "TTL_MS = 7 * 24 * 60 * 60 * 1000",
            self.js,
            "TTL_MS 必须显式写成 7*24*60*60*1000 让 reviewer 一眼看到 7 天约束",
        )

    def test_max_drafts_constant(self) -> None:
        self.assertIn("MAX_DRAFTS = 50", self.js)

    def test_input_debounce_ms_constant(self) -> None:
        self.assertIn("INPUT_DEBOUNCE_MS = 500", self.js)

    def test_sync_interval_ms_constant(self) -> None:
        # 30s = 30*1000ms
        self.assertIn(
            "SYNC_INTERVAL_MS = 30 * 1000",
            self.js,
            "SYNC_INTERVAL_MS 必须显式写成 30*1000 让 reviewer 看到 30s 约束",
        )


# ----------------------------------------------------------------------
# Class 3: API 函数签名 + window.AIIA_FEEDBACK_DRAFTS 暴露
# ----------------------------------------------------------------------


class TestApiSurface(unittest.TestCase):
    def setUp(self) -> None:
        self.js = _read_js()

    def test_load_all_drafts_function_present(self) -> None:
        self.assertRegex(self.js, r"function\s+loadAllDrafts\s*\(\s*\)")

    def test_get_draft_function_present(self) -> None:
        self.assertRegex(self.js, r"function\s+getDraft\s*\(\s*taskId\s*\)")

    def test_save_draft_function_present(self) -> None:
        self.assertRegex(self.js, r"function\s+saveDraft\s*\(\s*taskId\s*,\s*text\s*\)")

    def test_clear_draft_function_present(self) -> None:
        self.assertRegex(self.js, r"function\s+clearDraft\s*\(\s*taskId\s*\)")

    def test_clear_all_drafts_function_present(self) -> None:
        self.assertRegex(self.js, r"function\s+clearAllDrafts\s*\(\s*\)")

    def test_hydrate_memory_cache_function_present(self) -> None:
        self.assertRegex(self.js, r"function\s+hydrateMemoryCache\s*\(\s*\)")

    def test_reconcile_memory_to_storage_function_present(self) -> None:
        self.assertRegex(self.js, r"function\s+reconcileMemoryToStorage\s*\(\s*\)")

    def test_init_function_present(self) -> None:
        self.assertRegex(self.js, r"function\s+init\s*\(\s*\)")

    def test_window_exposure(self) -> None:
        self.assertIn("window.AIIA_FEEDBACK_DRAFTS", self.js)
        for name in (
            "STORAGE_KEY",
            "SCHEMA_VERSION",
            "TARGET_ID",
            "TTL_MS",
            "MAX_DRAFTS",
            "INPUT_DEBOUNCE_MS",
            "SYNC_INTERVAL_MS",
            "loadAllDrafts",
            "getDraft",
            "saveDraft",
            "clearDraft",
            "clearAllDrafts",
            "hydrateMemoryCache",
            "reconcileMemoryToStorage",
            "init",
        ):
            self.assertIn(
                name + ":",
                self.js,
                f"window.AIIA_FEEDBACK_DRAFTS 必须 export {name}",
            )


# ----------------------------------------------------------------------
# Class 4: graceful failure / fallback 路径
# ----------------------------------------------------------------------


class TestGracefulFallback(unittest.TestCase):
    def setUp(self) -> None:
        self.js = _read_js()

    def test_storage_available_probe_pattern(self) -> None:
        # _isStorageAvailable 必须用 set/remove probe 检测 + try/catch
        self.assertRegex(
            self.js,
            r"_isStorageAvailable[\s\S]*?try[\s\S]*?localStorage\.setItem"
            r"[\s\S]*?localStorage\.removeItem[\s\S]*?catch",
        )

    def test_read_envelope_has_try_catch(self) -> None:
        # _readEnvelope 必须 try/catch JSON.parse + localStorage.getItem
        self.assertRegex(
            self.js,
            r"_readEnvelope[\s\S]*?try[\s\S]*?JSON\.parse[\s\S]*?catch",
        )

    def test_read_envelope_validates_schema_version(self) -> None:
        # schema_version 不匹配时返回 null（防止 v2 升级污染 v1 数据）
        self.assertRegex(
            self.js,
            r"_readEnvelope[\s\S]*?parsed\.schema_version\s*!==\s*SCHEMA_VERSION",
        )

    def test_write_envelope_has_try_catch(self) -> None:
        # _writeEnvelope 必须 try/catch 包 setItem（quota 满时 silent no-op）
        self.assertRegex(
            self.js,
            r"_writeEnvelope[\s\S]*?try[\s\S]*?localStorage\.setItem[\s\S]*?catch",
        )

    def test_clear_all_drafts_has_try_catch(self) -> None:
        # clearAllDrafts 必须 try/catch removeItem
        self.assertRegex(
            self.js,
            r"clearAllDrafts[\s\S]*?try[\s\S]*?localStorage\.removeItem[\s\S]*?catch",
        )

    def test_init_skips_when_storage_unavailable(self) -> None:
        # init 在 _isStorageAvailable() 失败时直接 return null
        self.assertRegex(
            self.js,
            r"function\s+init[\s\S]*?if\s*\(\s*!_isStorageAvailable\(\)\s*\)\s*return\s+null",
        )


# ----------------------------------------------------------------------
# Class 5: 核心逻辑边界
# ----------------------------------------------------------------------


class TestCoreLogic(unittest.TestCase):
    def setUp(self) -> None:
        self.js = _read_js()

    def test_normalize_draft_handles_non_object(self) -> None:
        # _normalizeDraft 必须先检查 entry 是 object
        self.assertRegex(
            self.js,
            r"_normalizeDraft[\s\S]*?if\s*\(\s*!entry\s*\|\|\s*typeof\s+entry\s*!==\s*[\"']object[\"']\s*\)\s*return\s+null",
        )

    def test_normalize_draft_validates_text_string(self) -> None:
        # text 必须是 string 类型
        self.assertRegex(
            self.js,
            r"_normalizeDraft[\s\S]*?typeof\s+text\s*!==\s*[\"']string[\"']\s*\)\s*return\s+null",
        )

    def test_normalize_draft_defaults_saved_at_to_zero(self) -> None:
        # saved_at 不是 finite number 时默认 0（让 TTL 过滤命中淘汰）
        self.assertRegex(
            self.js,
            r"_normalizeDraft[\s\S]*?Number\.isFinite\(entry\.saved_at\)"
            r"[\s\S]*?:\s*0",
        )

    def test_apply_ttl_and_lru_filters_by_cutoff(self) -> None:
        # TTL 过滤：saved_at < cutoff 跳过
        self.assertRegex(
            self.js,
            r"_applyTtlAndLru[\s\S]*?cutoff\s*=\s*_now\(\)\s*-\s*TTL_MS"
            r"[\s\S]*?if\s*\(\s*norm\.saved_at\s*<\s*cutoff\s*\)\s*continue",
        )

    def test_apply_ttl_and_lru_sorts_desc_and_slices(self) -> None:
        # LRU 截 MAX_DRAFTS：sort by saved_at desc → slice(0, MAX_DRAFTS)
        self.assertRegex(
            self.js,
            r"_applyTtlAndLru[\s\S]*?b\.draft\.saved_at\s*-\s*a\.draft\.saved_at"
            r"[\s\S]*?slice\(0,\s*MAX_DRAFTS\)",
        )

    def test_hydrate_does_not_overwrite_existing(self) -> None:
        # hydrate 必须 hasOwnProperty 检查，不覆盖既存 entry
        self.assertRegex(
            self.js,
            r"hydrateMemoryCache[\s\S]*?Object\.prototype\.hasOwnProperty\.call\("
            r"[\s\S]*?window\.taskTextareaContents,[\s\S]*?taskId"
            r"[\s\S]*?continue",
        )

    def test_save_draft_with_empty_text_deletes_entry(self) -> None:
        # text === "" 时从字典 delete（不写空 text 占用 storage）
        self.assertRegex(
            self.js,
            r"saveDraft[\s\S]*?if\s*\(\s*text\s*===\s*[\"']{2}\s*\)"
            r"[\s\S]*?delete\s+drafts\[taskId\]",
        )

    def test_reconcile_skips_empty_text(self) -> None:
        # reconcileMemoryToStorage 跳过 text 空字符串（只持久化非空 draft）
        self.assertRegex(
            self.js,
            r"reconcileMemoryToStorage[\s\S]*?text\s*===\s*[\"']{2}"
            r"[\s\S]*?continue",
        )

    def test_input_listener_uses_debounce(self) -> None:
        # setupInputListener 必须 setTimeout(..., INPUT_DEBOUNCE_MS) debounce
        self.assertRegex(
            self.js,
            r"setupInputListener[\s\S]*?setTimeout[\s\S]*?INPUT_DEBOUNCE_MS",
        )


# ----------------------------------------------------------------------
# Class 6: HTML / context 集成
# ----------------------------------------------------------------------


class TestHtmlIntegration(unittest.TestCase):
    def setUp(self) -> None:
        self.html = _read_html()
        self.web_ui_py = WEB_UI_PY.read_text(encoding="utf-8")

    def test_script_tag_with_defer_nonce_and_version(self) -> None:
        # <script defer src="...feedback_drafts.js?v={{...}}" nonce="{{ csp_nonce }}">
        self.assertRegex(
            self.html,
            (
                r"<script[\s\S]*?defer[\s\S]*?"
                r'src="/static/js/feedback_drafts\.js'
                r'\?v=\{\{\s*feedback_drafts_version\s*\}\}"[\s\S]*?'
                r'nonce="\{\{\s*csp_nonce\s*\}\}"'
            ),
        )

    def test_template_context_provides_version(self) -> None:
        # web_ui.py 必须给 template 注入 feedback_drafts_version
        self.assertRegex(
            self.web_ui_py,
            r'"feedback_drafts_version":\s*_compute_file_version\(',
        )


if __name__ == "__main__":
    unittest.main()
