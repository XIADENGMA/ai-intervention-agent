"""R301: `_classifyHttpResponse` 5xx 子分类 invariant 测试 (cycle-30 t30-1)。

cr59 §5 #A1 推荐 "_classifyHttpResponse 5xx 子分类 (502/503/504 区分) —
lifecycle pattern 第二应用"。R294 当前把所有 5xx 统一为
`status.serviceUnavailable`, 但 prod 部署 (nginx 反代) 下 502/503/504
是不同语义:
- **502 Bad Gateway**: 上游 crash / 启动中 → user 等几秒, 自动恢复
- **503 Service Unavailable**: 上游主动 unavailable (overload / maintenance)
  → user 看是否计划维护
- **504 Gateway Timeout**: 上游处理超时 (hang / slow query) → user 知道
  是上游慢, 不是网络断

R301 给 502/503/504 各加专属 i18n key + 调整 `_classifyHttpResponse`
分类逻辑, 500/501/505+ fallback 到通用 `serviceUnavailable`。

================================================================
| 维度                                                | tests |
|---------------------------------------------------|-------|
| 1. _classifyHttpResponse 必须有 502/503/504 各自分支 | 4    |
| 2. 5xx fallback 兜底 (500/501/505)                  | 2     |
| 3. 3 个新 i18n key 在 4 locale 全部存在            | 4     |
| 4. _PRE_RESERVED_KEYS 和 _WEB_RESERVED_DYNAMIC 同步 | 2     |
================================================================
| 合计                                                | 12    |
================================================================

**pattern lineage**: R294 (lifecycle-cleanup invariant 首次应用)
+ R301 (lifecycle pattern 第二应用) — 把 v3.6 pattern 从 "首次落地" 推到
"稳定期"。
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC = PROJECT_ROOT / "src" / "ai_intervention_agent"
APP_JS = SRC / "static" / "js" / "app.js"
LOCALES_DIR = SRC / "static" / "locales"
TEST_RUNTIME = PROJECT_ROOT / "tests" / "test_runtime_behavior.py"
ORPHAN_SCRIPT = PROJECT_ROOT / "scripts" / "check_i18n_orphan_keys.py"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _strip_js_comments(src: str) -> str:
    out = re.sub(r"/\*[\s\S]*?\*/", "", src)
    cleaned: list[str] = []
    for line in out.split("\n"):
        in_str: str | None = None
        i = 0
        n = len(line)
        cut = n
        while i < n:
            c = line[i]
            if in_str:
                if c == "\\" and i + 1 < n:
                    i += 2
                    continue
                if c == in_str:
                    in_str = None
            else:
                if c in ('"', "'", "`"):
                    in_str = c
                elif c == "/" and i + 1 < n and line[i + 1] == "/":
                    cut = i
                    break
            i += 1
        cleaned.append(line[:cut])
    return "\n".join(cleaned)


# ============================================================
# #1: _classifyHttpResponse 必须有 502/503/504 各自分支
# ============================================================
class TestClassify5xxSubclassPresent(unittest.TestCase):
    """app.js _classifyHttpResponse 必须区分 502/503/504 而非笼统归 serviceUnavailable"""

    def setUp(self) -> None:
        self.js = _strip_js_comments(_read(APP_JS))
        m = re.search(
            r"function _classifyHttpResponse\(response\)\s*\{[\s\S]+?^\}",
            self.js,
            re.MULTILINE,
        )
        self.assertIsNotNone(m, "未找到 _classifyHttpResponse 函数")
        assert m is not None
        self.body = m.group(0)

    def test_502_returns_badGateway(self) -> None:
        m = re.search(
            r"if\s*\(\s*status\s*===?\s*502\s*\)[\s\S]{0,200}?return\s+['\"]status\.badGateway['\"]",
            self.body,
        )
        self.assertIsNotNone(
            m,
            "R301: _classifyHttpResponse 必须 if (status === 502) return 'status.badGateway'",
        )

    def test_503_returns_serviceOverloaded(self) -> None:
        m = re.search(
            r"if\s*\(\s*status\s*===?\s*503\s*\)[\s\S]{0,200}?return\s+['\"]status\.serviceOverloaded['\"]",
            self.body,
        )
        self.assertIsNotNone(
            m,
            "R301: _classifyHttpResponse 必须 if (status === 503) return 'status.serviceOverloaded'",
        )

    def test_504_returns_gatewayTimeout(self) -> None:
        m = re.search(
            r"if\s*\(\s*status\s*===?\s*504\s*\)[\s\S]{0,200}?return\s+['\"]status\.gatewayTimeout['\"]",
            self.body,
        )
        self.assertIsNotNone(
            m,
            "R301: _classifyHttpResponse 必须 if (status === 504) return 'status.gatewayTimeout'",
        )

    def test_subclass_branches_before_5xx_fallback(self) -> None:
        """502/503/504 分支必须在 if (status >= 500 && status < 600) fallback 之前
        (否则 fallback 会先 return, 子分支 unreachable)。"""
        m_502 = self.body.find("status === 502")
        m_5xx = self.body.find("status >= 500")
        self.assertGreater(m_502, 0, "未找到 status === 502 分支")
        self.assertGreater(m_5xx, 0, "未找到 status >= 500 fallback")
        self.assertLess(
            m_502,
            m_5xx,
            "R301: 502/503/504 分支必须在 status >= 500 fallback 之前, "
            "否则 fallback 先 return 让子分类 unreachable",
        )


# ============================================================
# #2: 5xx fallback 兜底 (500/501/505)
# ============================================================
class TestClassify5xxFallback(unittest.TestCase):
    """500/501/505 等非 502/503/504 的 5xx 应 fallback 到通用 serviceUnavailable"""

    def setUp(self) -> None:
        self.js = _strip_js_comments(_read(APP_JS))

    def test_5xx_fallback_kept(self) -> None:
        """status >= 500 && status < 600 兜底必须保留, 返回 serviceUnavailable。"""
        m = re.search(
            r"if\s*\(\s*status\s*>=\s*500\s*&&\s*status\s*<\s*600\s*\)[\s\S]{0,200}?return\s+['\"]status\.serviceUnavailable['\"]",
            self.js,
        )
        self.assertIsNotNone(
            m,
            "R301: 必须保留 status >= 500 && < 600 fallback 返回 serviceUnavailable",
        )

    def test_401_403_unaffected(self) -> None:
        """401/403 → unauthorized 分类必须保持不变 (R294 行为)。"""
        m = re.search(
            r"if\s*\(\s*status\s*===?\s*401\s*\|\|\s*status\s*===?\s*403\s*\)[\s\S]{0,200}?return\s+['\"]status\.unauthorized['\"]",
            self.js,
        )
        self.assertIsNotNone(
            m,
            "R294 401/403 → unauthorized 分支必须保持不变",
        )


# ============================================================
# #3: 3 个新 i18n key 在 4 locale 全部存在
# ============================================================
class TestNewI18nKeysExistAllLocales(unittest.TestCase):
    """status.badGateway / serviceOverloaded / gatewayTimeout 必须在 4 locale 存在"""

    NEW_KEYS = ("badGateway", "serviceOverloaded", "gatewayTimeout")
    LOCALES = ("en.json", "zh-CN.json", "zh-TW.json", "_pseudo/pseudo.json")

    def test_en_has_all_3_keys(self) -> None:
        self._check_locale("en.json")

    def test_zh_cn_has_all_3_keys(self) -> None:
        self._check_locale("zh-CN.json")

    def test_zh_tw_has_all_3_keys(self) -> None:
        self._check_locale("zh-TW.json")

    def test_pseudo_has_all_3_keys(self) -> None:
        self._check_locale("_pseudo/pseudo.json")

    def _check_locale(self, fname: str) -> None:
        data = json.loads(_read(LOCALES_DIR / fname))
        status = data.get("status", {})
        for key in self.NEW_KEYS:
            self.assertIn(
                key,
                status,
                f"R301: locale {fname} 缺少 status.{key} 翻译",
            )
            self.assertIsInstance(
                status[key],
                str,
                f"R301: locale {fname} status.{key} 必须是 str, "
                f"got {type(status[key]).__name__}",
            )
            self.assertGreater(
                len(status[key]),
                0,
                f"R301: locale {fname} status.{key} 不能为空字符串",
            )


# ============================================================
# #4: _PRE_RESERVED_KEYS 和 _WEB_RESERVED_DYNAMIC 同步
# ============================================================
class TestDynamicKeyExemptionListsUpdated(unittest.TestCase):
    """3 个新 dynamic key 必须同时加到 _PRE_RESERVED_KEYS + _WEB_RESERVED_DYNAMIC"""

    NEW_KEYS = (
        "status.badGateway",
        "status.serviceOverloaded",
        "status.gatewayTimeout",
    )

    def test_pre_reserved_keys_updated(self) -> None:
        runtime = _read(TEST_RUNTIME)
        for key in self.NEW_KEYS:
            self.assertIn(
                key,
                runtime,
                f"R301: tests/test_runtime_behavior.py _PRE_RESERVED_KEYS 必须包含 {key!r}",
            )

    def test_web_reserved_dynamic_updated(self) -> None:
        orphan = _read(ORPHAN_SCRIPT)
        for key in self.NEW_KEYS:
            self.assertIn(
                key,
                orphan,
                f"R301: scripts/check_i18n_orphan_keys.py _WEB_RESERVED_DYNAMIC 必须包含 {key!r}",
            )


if __name__ == "__main__":
    unittest.main()
