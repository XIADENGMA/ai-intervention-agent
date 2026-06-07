"""R291 invariant: dynamic i18n key 豁免清单 2 处必须同步 (R289 spillover lock)。

背景
----
cycle-27 R289 引入 ``_classifyFetchError(error)`` helper，5 个 ``status.*``
fetch-error key 通过 ``t(_classifyFetchError(error))`` 动态引用。``JS_T_CALL_RE``
正则只识别字面值 ``t('...')``，无法 trace dynamic key → 这 5 个 key 在
dead-key check 中被误报为 "未引用"，进而：

1. ``tests/test_runtime_behavior.py::TestI18nDeadKeys::_PRE_RESERVED_KEYS``
   未豁免 → ``test_web_locale_no_dead_keys`` 误报 5 个 dead key
2. ``scripts/check_i18n_orphan_keys.py::_WEB_RESERVED_DYNAMIC`` 未豁免 →
   ``test_i18n_orphan_keys::test_strict_exits_zero_when_no_orphans`` 误报
3. R287 添加 docs example mention 16 / 200 max-length 也触发
   ``test_mcp_tools_doc_consistency::test_no_other_4_or_5_digit_length_constants_lurking``
4. ``app.js:582`` (R285 cycle-25) catch 路径 ``button.innerHTML = errorIconSvg
   + t("status.copyFailed")`` 缺 ``AIIA-XSS-SAFE`` 注释（success 路径 line 561
   有，catch 路径漏写）

R291 修了这 4 处副作用 + 锁住关键 invariant：dynamic-key 豁免必须 2 处同步。

为什么必须 2 处同步
-------------------
两处独立 dead-key 检测器：

- **Python 测试** (``test_runtime_behavior.py``)：CI 阻塞 (red/green)
- **CLI 脚本** (``check_i18n_orphan_keys.py``)：开发者本地 ``python scripts/...
  --strict`` 手动 / pre-push hook 调用

如果只更新 1 处，会出现"CI 绿但脚本 fail" 或反之的诡异 drift —
下次开发者跑脚本就被误报阻塞，调试半天才发现只差豁免清单。R291 强制
2 处必须完全相同（同 sup 同 sub）。
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TEST_FILE = REPO_ROOT / "tests" / "test_runtime_behavior.py"
SCRIPT_FILE = REPO_ROOT / "scripts" / "check_i18n_orphan_keys.py"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _extract_test_reserved_keys() -> set[str]:
    """从 ``test_runtime_behavior.py::TestI18nDeadKeys._PRE_RESERVED_KEYS``
    dict 提取 key 集合 (regex 解析，避开 import 副作用)。"""
    src = _read(TEST_FILE)
    # match: "key": frozenset({"web"})  / "key": frozenset({"web", "vscode"})
    pattern = re.compile(r'^\s*"([a-zA-Z][\w.]*)"\s*:\s*frozenset\(', re.MULTILINE)
    # 限定在 _PRE_RESERVED_KEYS 块内（找第一个 PRE_RESERVED_KEYS 出现到下一个
    # 顶级 } 之间）
    start_idx = src.find("_PRE_RESERVED_KEYS: dict")
    if start_idx == -1:
        return set()
    block_end = src.find("\n    }\n", start_idx)
    if block_end == -1:
        return set()
    block = src[start_idx:block_end]
    return set(pattern.findall(block))


def _extract_script_reserved_keys() -> set[str]:
    """从 ``check_i18n_orphan_keys.py::_WEB_RESERVED_DYNAMIC`` set 提取
    key 集合。"""
    src = _read(SCRIPT_FILE)
    start_idx = src.find("_WEB_RESERVED_DYNAMIC: set[str] = {")
    if start_idx == -1:
        return set()
    block_end = src.find("\n    }\n", start_idx)
    if block_end == -1:
        return set()
    block = src[start_idx:block_end]
    # match: "key" 字面值（行内不带 frozenset 包装）
    pattern = re.compile(r'"([a-zA-Z][\w.]*)"')
    return set(pattern.findall(block))


class TestDynamicReservedSyncBetweenTestAndScript(unittest.TestCase):
    """test 和 script 的 dynamic-key 豁免清单必须严格相等（双向 subset）。"""

    def test_test_file_contains_reserved_keys(self) -> None:
        """sanity: test 文件能解析出至少 1 个 dynamic-key (cr40 customSound)。"""
        keys = _extract_test_reserved_keys()
        self.assertGreater(
            len(keys),
            0,
            "_PRE_RESERVED_KEYS regex 解析失败 — 检查 dict 块边界 (起始 / 结束 marker)",
        )

    def test_script_file_contains_reserved_keys(self) -> None:
        """sanity: script 文件能解析出至少 1 个 dynamic-key。"""
        keys = _extract_script_reserved_keys()
        self.assertGreater(
            len(keys),
            0,
            "_WEB_RESERVED_DYNAMIC regex 解析失败 — 检查 set 块边界",
        )

    def test_test_and_script_reserved_sets_identical(self) -> None:
        """两处豁免清单必须完全相等，否则 CI vs CLI 检测结果会 drift。"""
        test_keys = _extract_test_reserved_keys()
        script_keys = _extract_script_reserved_keys()
        only_in_test = test_keys - script_keys
        only_in_script = script_keys - test_keys
        msg_parts = []
        if only_in_test:
            msg_parts.append(
                f"仅在 test ({TEST_FILE.name}) 出现的 key (script 缺豁免，"
                f"CLI 会误报)：{sorted(only_in_test)}"
            )
        if only_in_script:
            msg_parts.append(
                f"仅在 script ({SCRIPT_FILE.name}) 出现的 key (test 缺豁免，"
                f"CI 会误报)：{sorted(only_in_script)}"
            )
        if msg_parts:
            self.fail(
                "test 与 script 的 dynamic i18n key 豁免清单 drift：\n  "
                + "\n  ".join(msg_parts)
                + "\n请同步更新 tests/test_runtime_behavior.py::TestI18nDeadKeys"
                + "._PRE_RESERVED_KEYS 与 scripts/check_i18n_orphan_keys.py"
                + "::_WEB_RESERVED_DYNAMIC。"
            )


class TestR289FetchErrorKeysExempted(unittest.TestCase):
    """R289 引入的 5 个 ``status.*`` fetch-error key 必须在两处豁免清单内。"""

    R289_KEYS = frozenset(
        {
            "status.networkError",
            "status.networkOffline",
            "status.requestTimeout",
            "status.serverResponseInvalid",
            "status.uiRenderingError",
        }
    )

    def test_all_5_keys_in_test_reserved(self) -> None:
        test_keys = _extract_test_reserved_keys()
        missing = self.R289_KEYS - test_keys
        self.assertFalse(
            missing,
            f"R289 fetch-error keys 缺失于 test 豁免清单：{sorted(missing)}",
        )

    def test_all_5_keys_in_script_reserved(self) -> None:
        script_keys = _extract_script_reserved_keys()
        missing = self.R289_KEYS - script_keys
        self.assertFalse(
            missing,
            f"R289 fetch-error keys 缺失于 script 豁免清单：{sorted(missing)}",
        )


class TestAppJsCopyFailedXssSafeComment(unittest.TestCase):
    """R285 catch 路径 ``button.innerHTML = errorIconSvg + t('status.copyFailed')``
    必须带 ``AIIA-XSS-SAFE`` 注释 (与 line 561 success 路径同源安全)。"""

    APP_JS = REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "js" / "app.js"

    def test_copy_failed_innerhtml_has_xss_safe_comment(self) -> None:
        src = _read(self.APP_JS)
        # 找 ``button.innerHTML = errorIconSvg + t("status.copyFailed")`` 这行
        target_line = re.search(
            r'button\.innerHTML\s*=\s*errorIconSvg\s*\+\s*t\(\s*["\']status\.copyFailed["\']\s*\)',
            src,
        )
        self.assertIsNotNone(
            target_line,
            "未在 app.js 找到 errorIconSvg + t('status.copyFailed') 调用",
        )
        assert target_line is not None
        # 向前找 200 字符内必须出现 AIIA-XSS-SAFE marker
        ctx_start = max(0, target_line.start() - 400)
        context = src[ctx_start : target_line.start()]
        self.assertIn(
            "AIIA-XSS-SAFE",
            context,
            "errorIconSvg + t('status.copyFailed') 上方 400 字符内缺 AIIA-XSS-SAFE 注释；"
            "应与 line 561 success 路径同样标注（详见 docs/i18n.md § Security）",
        )


class TestMcpToolsDocConstantWhitelistExtended(unittest.TestCase):
    """``test_mcp_tools_doc_consistency`` 的 ALLOWED 白名单必须 import
    ``HEADER_LABEL_MAX_LENGTH`` + ``PLACEHOLDER_MAX_LENGTH`` 而非 hardcode 16/200。"""

    DOC_TEST_FILE = REPO_ROOT / "tests" / "test_mcp_tools_doc_consistency.py"

    def test_imports_task_queue_constants(self) -> None:
        src = _read(self.DOC_TEST_FILE)
        self.assertIn(
            "HEADER_LABEL_MAX_LENGTH",
            src,
            "test_mcp_tools_doc_consistency 必须 import HEADER_LABEL_MAX_LENGTH "
            "(避免 16 hardcode drift)",
        )
        self.assertIn(
            "PLACEHOLDER_MAX_LENGTH",
            src,
            "test_mcp_tools_doc_consistency 必须 import PLACEHOLDER_MAX_LENGTH "
            "(避免 200 hardcode drift)",
        )

    def test_allowed_set_references_constants(self) -> None:
        """ALLOWED set 应通过 ``str(CONST)`` 引用而非 hardcode ``"16"`` / ``"200"``。"""
        src = _read(self.DOC_TEST_FILE)
        self.assertRegex(
            src,
            r"str\(HEADER_LABEL_MAX_LENGTH\)",
            "ALLOWED set 必须包含 str(HEADER_LABEL_MAX_LENGTH) 表达式",
        )
        self.assertRegex(
            src,
            r"str\(PLACEHOLDER_MAX_LENGTH\)",
            "ALLOWED set 必须包含 str(PLACEHOLDER_MAX_LENGTH) 表达式",
        )


if __name__ == "__main__":
    unittest.main()
