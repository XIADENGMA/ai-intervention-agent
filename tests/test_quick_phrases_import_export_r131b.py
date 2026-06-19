"""R131b · Quick Phrases JSON 导入 / 导出契约。

背景
----
R130 把 Quick Phrases 持久化到 ``localStorage``——这是「单设备 / 单
浏览器」语义。R131 补齐编辑能力。Code Review #2 把「跨设备 / 跨浏览
器迁移」列为 P1 follow-up：用户在 A 机器整理好 20 条常用回复，到 B
机器又得手敲一遍。竞品 ``mcp-feedback-enhanced`` 的 Prompt
Management 一开始就支持 JSON Import / Export（v1.2.23 直接以 JSON
文件格式分发用户 prompt 集），是基础生产力门槛。

R131b 在 Quick Phrases 面板加：

1. **Export** 按钮：把当前 phrases 序列化成带签名的 envelope JSON，
   触发浏览器下载（``Blob`` + 临时 ``<a download>``，老 IE 兜底
   ``data:`` URL）；文件名含 ISO8601 时间戳避免覆盖。
2. **Import** 按钮：弹出 file picker，``FileReader`` 读文本，校验
   ``signature`` + ``schema_version`` + ``phrases`` 数组；默认 merge
   语义（按 ``(label, text)`` 元组去重，新条目分配新 ``id``）；merge
   后全部重复时弹 ``confirm`` 提示是否 ``replace``（替换全部，不可
   撤销）。
3. 错误路径：JSON 解析失败 / schema 不匹配 / 过滤后为空——分别走
   不同 i18n 错误文案，用 ``alert`` 提示后中止。

设计原则承袭 R130：纯前端 + ``localStorage``，零后端 API、零跨进程
同步、零隐私边界扩张。

测试覆盖六个层面（共 16 cases / 6 invariant classes）：

1.  **JS API 扩展** — ``buildExportEnvelope`` / ``exportPhrasesAsJson``
    / ``downloadPhrasesAsFile`` / ``parseImportPayload`` /
    ``importPhrasesFromJson`` / ``triggerImportFilePicker`` 六个函数
    存在并暴露在 ``window.AIIA_QUICK_PHRASES``。
2.  **导出 envelope schema** — 含 ``signature`` / ``schema_version``
    / ``exported_at`` / ``phrases`` 四个顶层字段；签名字符串与
    ``EXPORT_SIGNATURE`` 常量同源；下载文件名以
    ``ai-intervention-agent-quick-phrases-`` 为前缀含 ISO8601 戳。
3.  **HTML 结构** — Quick Phrases header 含 ``#quick-phrases-export-btn``
    / ``#quick-phrases-import-btn`` 两个按钮 + ``#quick-phrases-import-file``
    隐藏 file input；按钮带 ``data-i18n`` / ``data-i18n-aria-label``
    属性。
4.  **导入校验枝** — ``parseImportPayload`` 实现里有：
    - JSON 解析失败 → ``importErrorInvalidJson``
    - 签名 / schema 缺失 → ``importErrorSchema``
    - 过滤后为空 → ``importErrorEmpty``
5.  **i18n 完备性** — 三份 locale（zh-CN / en / _pseudo）都包含 9 条
    新增 key（``exportBtn`` / ``exportBtnAriaLabel`` / ``importBtn``
    / ``importBtnAriaLabel`` / ``importErrorInvalidJson`` /
    ``importErrorSchema`` / ``importErrorEmpty`` /
    ``importConfirmReplace`` / ``importSuccessMerge`` /
    ``importSuccessReplace``）。
6.  **CSS 样式** — Export / Import 按钮共用 ``.quick-phrases-add-btn``
    的 base style（合并到同一 selector group），保证视觉一致。
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC = REPO_ROOT / "src" / "ai_intervention_agent"
JS_QP = SRC / "static" / "js" / "quick_phrases.js"
HTML_TEMPLATE = SRC / "templates" / "web_ui.html"
LOCALE_EN = SRC / "static" / "locales" / "en.json"
LOCALE_ZH = SRC / "static" / "locales" / "zh-CN.json"
LOCALE_PSEUDO = SRC / "static" / "locales" / "_pseudo" / "pseudo.json"
CSS = SRC / "static" / "css" / "main.css"


EXPECTED_NEW_QP_KEYS: tuple[str, ...] = (
    "exportBtn",
    "exportBtnAriaLabel",
    "importBtn",
    "importBtnAriaLabel",
    "importErrorInvalidJson",
    "importErrorReadFailed",
    "importErrorSchema",
    "importErrorEmpty",
    "importConfirmReplace",
    "importSuccessMerge",
    "importSuccessReplace",
)


def _read(p: Path) -> str:
    assert p.is_file(), f"缺失文件: {p}"
    return p.read_text(encoding="utf-8")


def _read_locale(p: Path) -> dict:
    return json.loads(_read(p))


def _extract_function_body(src: str, signature_regex: str) -> str:
    """从 ``src`` 抽取签名匹配的函数体（含嵌套 ``{}``）。

    R131b 的 ``parseImportPayload`` / ``importPhrasesFromJson`` /
    ``buildExportEnvelope`` 等函数体内含多层嵌套（try/forEach/object
    literal），用 ``.*?\\}`` 非贪婪正则会停在第一个内层闭合 ``}``。
    手写 brace counter 是最稳的办法，且开销可忽略（quick_phrases.js
    只有 ~900 行）。
    """
    m = re.search(signature_regex, src)
    if not m:
        raise AssertionError(f"找不到签名: {signature_regex}")
    open_brace = src.find("{", m.end())
    if open_brace == -1:
        raise AssertionError(f"签名 {signature_regex} 之后找不到 ``{{``")
    depth = 0
    in_str: str | None = None
    in_block_comment = False
    in_line_comment = False
    i = open_brace
    while i < len(src):
        ch = src[i]
        nxt = src[i + 1] if i + 1 < len(src) else ""
        if in_line_comment:
            if ch == "\n":
                in_line_comment = False
        elif in_block_comment:
            if ch == "*" and nxt == "/":
                in_block_comment = False
                i += 1
        elif in_str is not None:
            if ch == "\\":
                i += 1  # 跳过转义字符
            elif ch == in_str:
                in_str = None
        else:
            if ch == "/" and nxt == "/":
                in_line_comment = True
                i += 1
            elif ch == "/" and nxt == "*":
                in_block_comment = True
                i += 1
            elif ch in ("'", '"', "`"):
                in_str = ch
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return src[open_brace + 1 : i]
        i += 1
    raise AssertionError(f"签名 {signature_regex} 函数体未闭合")


# ---------------------------------------------------------------------------
# 1. JS API 扩展
# ---------------------------------------------------------------------------


class TestImportExportJsApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _read(JS_QP)

    def test_build_export_envelope_function_present(self) -> None:
        self.assertRegex(
            self.js,
            r"function\s+buildExportEnvelope\s*\(\s*\)",
            "必须存在 buildExportEnvelope() 函数",
        )

    def test_export_phrases_as_json_function_present(self) -> None:
        self.assertRegex(
            self.js,
            r"function\s+exportPhrasesAsJson\s*\(\s*\)",
            "必须存在 exportPhrasesAsJson() 函数",
        )

    def test_download_phrases_as_file_function_present(self) -> None:
        self.assertRegex(
            self.js,
            r"function\s+downloadPhrasesAsFile\s*\(\s*\)",
            "必须存在 downloadPhrasesAsFile() 函数",
        )

    def test_parse_import_payload_function_present(self) -> None:
        self.assertRegex(
            self.js,
            r"function\s+parseImportPayload\s*\(\s*rawText\s*\)",
            "必须存在 parseImportPayload(rawText) 函数",
        )

    def test_import_phrases_from_json_function_present(self) -> None:
        self.assertRegex(
            self.js,
            r"function\s+importPhrasesFromJson\s*\(\s*rawText\s*,\s*mode\s*\)",
            "必须存在 importPhrasesFromJson(rawText, mode) 函数",
        )

    def test_trigger_import_file_picker_function_present(self) -> None:
        self.assertRegex(
            self.js,
            r"function\s+triggerImportFilePicker\s*\(\s*\)",
            "必须存在 triggerImportFilePicker() 函数",
        )

    def test_public_api_exposes_six_new_handles(self) -> None:
        for sym in (
            "buildExportEnvelope",
            "exportPhrasesAsJson",
            "downloadPhrasesAsFile",
            "parseImportPayload",
            "importPhrasesFromJson",
            "triggerImportFilePicker",
        ):
            self.assertRegex(
                self.js,
                rf"{sym}\s*:\s*{sym}",
                f"AIIA_QUICK_PHRASES 必须暴露 {sym}",
            )


# ---------------------------------------------------------------------------
# 2. 导出 envelope schema
# ---------------------------------------------------------------------------


class TestExportEnvelopeSchema(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _read(JS_QP)

    def test_export_signature_constant_present(self) -> None:
        self.assertRegex(
            self.js,
            r'EXPORT_SIGNATURE\s*=\s*"ai-intervention-agent\.quick-phrases"',
            "EXPORT_SIGNATURE 必须是稳定的 'ai-intervention-agent.quick-phrases'",
        )

    def test_export_schema_version_constant_present(self) -> None:
        self.assertRegex(
            self.js,
            r"EXPORT_SCHEMA_VERSION\s*=\s*1",
            "EXPORT_SCHEMA_VERSION 当前应当固定为 1",
        )

    def test_envelope_contains_required_top_level_fields(self) -> None:
        body = _extract_function_body(
            self.js, r"function\s+buildExportEnvelope\s*\([^)]*\)"
        )
        for field in ("signature", "schema_version", "exported_at", "phrases"):
            self.assertIn(
                field,
                body,
                f"buildExportEnvelope 必须填充 {field} 字段",
            )

    def test_download_filename_has_iso_timestamp_prefix(self) -> None:
        # 文件名形如 ai-intervention-agent-quick-phrases-<ISO8601>.json，
        # 让用户机器多次导出按时间排序、不互相覆盖
        self.assertRegex(
            self.js,
            r'"ai-intervention-agent-quick-phrases-"',
            "downloadPhrasesAsFile 文件名前缀必须为 'ai-intervention-agent-quick-phrases-'",
        )
        self.assertRegex(
            self.js,
            r"new Date\(\)\.toISOString\(\)",
            "文件名时间戳应来自 new Date().toISOString()",
        )


# ---------------------------------------------------------------------------
# 3. HTML 结构
# ---------------------------------------------------------------------------


class TestImportExportHtmlStructure(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.html = _read(HTML_TEMPLATE)

    def test_export_button_exists_in_template(self) -> None:
        self.assertRegex(
            self.html,
            r'id="quick-phrases-export-btn"',
            "模板必须含 #quick-phrases-export-btn",
        )
        self.assertRegex(
            self.html,
            r'data-i18n="quickPhrases\.exportBtn"',
            "Export 按钮必须带 data-i18n=quickPhrases.exportBtn",
        )

    def test_import_button_exists_in_template(self) -> None:
        self.assertRegex(
            self.html,
            r'id="quick-phrases-import-btn"',
            "模板必须含 #quick-phrases-import-btn",
        )
        self.assertRegex(
            self.html,
            r'data-i18n="quickPhrases\.importBtn"',
            "Import 按钮必须带 data-i18n=quickPhrases.importBtn",
        )

    def test_import_file_input_hidden_with_correct_accept(self) -> None:
        self.assertRegex(
            self.html,
            r'id="quick-phrases-import-file"',
            "模板必须含 #quick-phrases-import-file 文件输入元素",
        )
        # 限制 accept 为 JSON：避免用户错选其它类型；仅是 UX 提示，
        # 校验仍以 JS 解析为准
        self.assertRegex(
            self.html,
            r'accept="application/json,\.json"',
            "import file input 必须带 accept='application/json,.json'",
        )

    def test_export_and_import_buttons_above_quick_phrases_list(self) -> None:
        # 两个按钮应当出现在 .quick-phrases-list 之前（即 header 区域）
        list_pos = self.html.find('id="quick-phrases-list"')
        export_pos = self.html.find('id="quick-phrases-export-btn"')
        import_pos = self.html.find('id="quick-phrases-import-btn"')
        self.assertGreater(list_pos, 0, "找不到 quick-phrases-list 锚点")
        self.assertGreater(export_pos, 0, "找不到 export 按钮锚点")
        self.assertGreater(import_pos, 0, "找不到 import 按钮锚点")
        self.assertLess(export_pos, list_pos, "export 按钮应当在 list 之上")
        self.assertLess(import_pos, list_pos, "import 按钮应当在 list 之上")


# ---------------------------------------------------------------------------
# 4. 导入校验枝
# ---------------------------------------------------------------------------


class TestImportValidationBranches(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _read(JS_QP)

    def _extract_parse_import_body(self) -> str:
        return _extract_function_body(
            self.js, r"function\s+parseImportPayload\s*\([^)]*\)"
        )

    def test_invalid_json_returns_import_error_invalid_json(self) -> None:
        body = self._extract_parse_import_body()
        self.assertIn(
            "importErrorInvalidJson",
            body,
            "JSON 解析失败枝必须返回 importErrorInvalidJson 文案",
        )

    def test_schema_mismatch_returns_import_error_schema(self) -> None:
        body = self._extract_parse_import_body()
        self.assertIn(
            "importErrorSchema",
            body,
            "schema 不匹配枝必须返回 importErrorSchema 文案",
        )

    def test_empty_after_filter_returns_import_error_empty(self) -> None:
        body = self._extract_parse_import_body()
        self.assertIn(
            "importErrorEmpty",
            body,
            "过滤后为空枝必须返回 importErrorEmpty 文案",
        )

    def test_signature_check_blocks_foreign_files(self) -> None:
        body = self._extract_parse_import_body()
        self.assertRegex(
            body,
            r"signature\s*&&\s*parsed\.signature\s*!==\s*EXPORT_SIGNATURE",
            "parseImportPayload 必须在 signature 字段存在但不匹配时拒绝（防误导入）",
        )

    def test_import_phrases_supports_replace_mode(self) -> None:
        # importPhrasesFromJson 必须能接 mode 参数并在 "replace" 时
        # 直接覆盖；merge 模式下走 (label,text) 去重路径
        body = _extract_function_body(
            self.js, r"function\s+importPhrasesFromJson\s*\([^)]*\)"
        )
        self.assertRegex(
            body,
            r'mode\s*===\s*"replace"',
            "importPhrasesFromJson 应当显式判定 mode === 'replace'",
        )
        self.assertIn(
            "MAX_PHRASES",
            body,
            "import 路径必须遵守 MAX_PHRASES 容量上限",
        )


# ---------------------------------------------------------------------------
# 5. i18n 完备性（3 份 locale）
# ---------------------------------------------------------------------------


def _assert_qp_keys_complete(test: unittest.TestCase, locale_path: Path) -> None:
    data = _read_locale(locale_path)
    qp = data.get("quickPhrases")
    test.assertIsNotNone(qp, f"{locale_path.name} 缺 quickPhrases 命名空间")
    assert isinstance(qp, dict)
    for key in EXPECTED_NEW_QP_KEYS:
        test.assertIn(
            key,
            qp,
            f"{locale_path.name} 缺 quickPhrases.{key}",
        )
        v = qp[key]
        test.assertIsInstance(v, str)
        assert isinstance(v, str)
        test.assertNotEqual(
            v.strip(), "", f"{locale_path.name} quickPhrases.{key} 不能是空字符串"
        )


class TestImportExportI18nCoverage(unittest.TestCase):
    def test_zh_cn_locale_complete(self) -> None:
        _assert_qp_keys_complete(self, LOCALE_ZH)

    def test_en_locale_complete(self) -> None:
        _assert_qp_keys_complete(self, LOCALE_EN)

    def test_pseudo_locale_complete(self) -> None:
        _assert_qp_keys_complete(self, LOCALE_PSEUDO)

    def test_confirm_replace_uses_mustache_params(self) -> None:
        for path in (LOCALE_EN, LOCALE_ZH):
            data = _read_locale(path)
            qp = data["quickPhrases"]
            self.assertIn(
                "{{current}}",
                qp["importConfirmReplace"],
                f"{path.name} importConfirmReplace 必须含 {{{{current}}}} 占位符",
            )
            self.assertIn(
                "{{count}}",
                qp["importConfirmReplace"],
                f"{path.name} importConfirmReplace 必须含 {{{{count}}}} 占位符",
            )

    def test_success_merge_uses_mustache_params(self) -> None:
        for path in (LOCALE_EN, LOCALE_ZH):
            data = _read_locale(path)
            qp = data["quickPhrases"]
            self.assertIn(
                "{{added}}",
                qp["importSuccessMerge"],
                f"{path.name} importSuccessMerge 必须含 {{{{added}}}} 占位符",
            )
            self.assertIn(
                "{{skipped}}",
                qp["importSuccessMerge"],
                f"{path.name} importSuccessMerge 必须含 {{{{skipped}}}} 占位符",
            )


# ---------------------------------------------------------------------------
# 6. CSS 样式合并
# ---------------------------------------------------------------------------


class TestImportExportCssCohesion(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.css = _read(CSS)

    def test_export_import_share_add_btn_base_style(self) -> None:
        # 三个按钮 selector 必须出现在同一规则块的 selector list 里
        self.assertRegex(
            self.css,
            (
                r"\.quick-phrases-add-btn,\s*\n"
                r"\.quick-phrases-export-btn,\s*\n"
                r"\.quick-phrases-import-btn\s*\{"
            ),
            "Export / Import 按钮必须与 Add 按钮共享 base style（同一 selector group）",
        )


if __name__ == "__main__":
    unittest.main()
