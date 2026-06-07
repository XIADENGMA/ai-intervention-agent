"""R422 (cycle-48 #B1) — v3.10.3: OpenAPI error response schema parity (ratchet)

血脉关系 (Lineage):
- 14 大方法学维度之 v3.0 API contract (R230 → R232 → R236 → R242 → R248 →
  R268 → R288 → R398 → R404 → R412 → R422), 这是第 11 应用, 同时是
  v3.10 API consumer experience 系列第 3 sub-pattern (v3.10.1 endpoint
  summary R404; v3.10.2 property description R412/R418; v3.10.3 error
  response schema R422)。
- ratchet 模式 (R412 引入, R418 ratchet uplift) 第 3 应用 — 锁 baseline
  + 单调递增推动持续改进。

业务价值 (Business value):
- 当前状态: OpenAPI 4xx/5xx response 51 个, 仅 3 个 (5.88%) 有 schema 字段;
  其余只有 description, 客户端无法从 OpenAPI 静态获知错误响应的 body 结构,
  必须实际触发错误才能逆向工程响应结构 → 大量客户端 retry 逻辑 / 错误处理
  代码靠 try-catch 而非 schema 驱动, 严重削弱 OpenAPI 作为 API contract
  的价值。
- 客户端典型痛点:
  * 收到 500 不知道是 `{"status": "error", "message": "..."}` 还是 raw text
  * 收到 400 不知道有没有 `error_code` 字段可用于分类处理
  * 收到 429 不知道有没有 `Retry-After` header 或 body 字段
- R412 已经覆盖 200 OK 的 property description; R422 把 contract 完整性
  从 happy path 扩展到 error path, 形成 "all paths" API contract 覆盖。

设计 (Design):
- 静态扫描 `web_ui_routes/*.py` 所有 OpenAPI YAML docstring
- 识别所有 4xx/5xx response (status code 400-599)
- 统计有 `schema:` 字段的比例
- ratchet 锁 `MIN_ERROR_RESPONSE_SCHEMA_COVERAGE` ≥ 0.05 (当前 5.88% 取下)
- future cycle 可加 schema 推 coverage ≥ 0.10/0.20/0.50/..., ratchet 上调

负面验证 (Anti-pattern):
- 不锁具体哪些 endpoint 必须有 schema (false rigidity, 后端经常重构)
- 不强制 schema 内容 (例如必须有 `error` 字段) — 让前后端按需协商
- 只锁 *coverage* 单调递增, 不锁个体 endpoint, 避免 false positives
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

# R422 ratchet baseline. 当前实际 coverage = 42/51 ≈ 82.35%, 取下为 0.80。
# 节奏: R422 (cycle-48 #B1) 初始 0.05 (3/51 = 5.88%) → R428 (cycle-49 #A1)
# 推到 11/51 = 21.57%, ratchet 至 0.15 → R432 (cycle-49 #C1) 推到 19/51 =
# 37.25%, ratchet 至 0.30 → R436 (cycle-50 #A1) 推到 27/51 = 52.94%, ratchet
# 至 0.50 → R440 (cycle-51 #A1) 推到 36/51 = 70.59%, ratchet 至 0.70 →
# R446 (cycle-52 #A1) 增加 5 个 schema (notification.py reset 500 + bark-test
# 400/500 + system.py rotation 403/500/429) 推到 42/51 = 82.35%, ratchet 至
# 0.80 (production-quality threshold)。
# 推荐 ratchet 节奏 (每 1-2 cycle 上调一档):
#   0.05 → 0.15 → 0.30 → 0.50 → 0.70 → 0.80 → 0.90
# 终态目标 ≥ 0.90 (10% 容忍 special cases 例如 429 空 body / 502 网关)。
MIN_ERROR_RESPONSE_SCHEMA_COVERAGE = 0.80


def _project_root() -> Path:
    """Locate the project root by walking up from this file."""
    here = Path(__file__).resolve()
    for parent in [here, *here.parents]:
        if (parent / "pyproject.toml").exists():
            return parent
    raise RuntimeError("project root not found")


def _routes_dir() -> Path:
    return _project_root() / "src" / "ai_intervention_agent" / "web_ui_routes"


# 识别 OpenAPI response code: 形如 `              400:` (任意 8-20 空格缩进
# + 3 位数字 + `:` + 行尾)。
_RESPONSE_CODE_RE = re.compile(r"^(?P<indent>\s{8,20})(?P<code>\d{3}):\s*$")


def _scan_error_responses(py_path: Path) -> list[tuple[int, int, bool]]:
    """Scan one route file for 4xx/5xx responses and whether they have schema.

    Returns: list of (line_number, status_code, has_schema_field).
    """
    content = py_path.read_text(encoding="utf-8")
    lines = content.split("\n")
    results: list[tuple[int, int, bool]] = []

    for i, line in enumerate(lines):
        m = _RESPONSE_CODE_RE.match(line)
        if not m:
            continue
        code = int(m.group("code"))
        if not (400 <= code < 600):
            continue

        indent_len = len(m.group("indent"))
        has_schema = False

        # 向下扫描直到遇到同级或更浅缩进 (下一个 response code 或 responses 关闭)
        for j in range(i + 1, min(i + 20, len(lines))):
            nxt = lines[j]
            if not nxt.strip():
                continue
            # 检查是否回到同级 sibling response 或更浅
            sibling_m = _RESPONSE_CODE_RE.match(nxt)
            if sibling_m and len(sibling_m.group("indent")) == indent_len:
                break
            # 检查是否走出 responses 块 (更浅缩进非空行)
            stripped = nxt.lstrip()
            current_indent = len(nxt) - len(stripped)
            if current_indent <= indent_len and stripped:
                break
            if "schema:" in nxt:
                has_schema = True
                break

        results.append((i + 1, code, has_schema))

    return results


def _collect_all_error_responses() -> list[tuple[str, int, int, bool]]:
    """Collect (file_name, line, code, has_schema) across all route files."""
    out: list[tuple[str, int, int, bool]] = []
    for py in sorted(_routes_dir().glob("*.py")):
        if py.name == "__init__.py":
            continue
        for line_no, code, has_schema in _scan_error_responses(py):
            out.append((py.name, line_no, code, has_schema))
    return out


class TestR422ErrorResponseSchemaCoverage(unittest.TestCase):
    """v3.10.3 — ratchet-locked error response schema coverage."""

    def setUp(self) -> None:
        self.all_responses = _collect_all_error_responses()

    def test_has_error_responses(self) -> None:
        """Sanity: 项目应该有 error response 可统计。"""
        self.assertGreater(
            len(self.all_responses),
            10,
            "Sanity check fails: expect >10 error responses across web_ui_routes/. "
            "If this fails, _scan_error_responses regex may be broken.",
        )

    def test_error_response_schema_coverage_ratchet(self) -> None:
        """v3.10.3 ratchet: 错误响应 schema 覆盖率 ≥ MIN_ERROR_RESPONSE_SCHEMA_COVERAGE."""
        total = len(self.all_responses)
        with_schema = sum(1 for _, _, _, hs in self.all_responses if hs)
        coverage = with_schema / max(total, 1)
        self.assertGreaterEqual(
            coverage,
            MIN_ERROR_RESPONSE_SCHEMA_COVERAGE,
            f"OpenAPI 4xx/5xx response schema coverage = "
            f"{with_schema}/{total} ({coverage:.2%}) < ratchet "
            f"{MIN_ERROR_RESPONSE_SCHEMA_COVERAGE:.2%}. 修复: 在 "
            f"`web_ui_routes/*.py` 的 OpenAPI docstring 4xx/5xx response "
            f"下添加 schema 字段, 帮助客户端静态消费错误响应结构。",
        )

    def test_4xx_responses_present(self) -> None:
        """v3.10.3 sanity: 4xx response 应该存在 (业务正常的话)。"""
        codes_4xx = [r for r in self.all_responses if 400 <= r[2] < 500]
        self.assertGreater(
            len(codes_4xx),
            5,
            "Sanity: 期望项目有 > 5 个 4xx response (常见 400/404/429)。",
        )

    def test_5xx_responses_present(self) -> None:
        """v3.10.3 sanity: 5xx response 应该存在 (业务防御性 500)。"""
        codes_5xx = [r for r in self.all_responses if 500 <= r[2] < 600]
        self.assertGreater(
            len(codes_5xx),
            5,
            "Sanity: 期望项目有 > 5 个 5xx response (常见 500 internal error)。",
        )


class TestR422RatchetMetadata(unittest.TestCase):
    """Ratchet 元数据: 防止 baseline 被误下调。"""

    def test_ratchet_baseline_not_below_minimum(self) -> None:
        """防呆: MIN_ERROR_RESPONSE_SCHEMA_COVERAGE 不能 < 0.05 (项目原始基线)。"""
        self.assertGreaterEqual(
            MIN_ERROR_RESPONSE_SCHEMA_COVERAGE,
            0.05,
            "ratchet 设计约束: baseline 0.05 (=3/51) 是项目原始 floor, "
            "不允许下调; future cycle 加 schema 后只能向上调。",
        )

    def test_ratchet_baseline_not_above_one(self) -> None:
        """防呆: MIN_ERROR_RESPONSE_SCHEMA_COVERAGE ≤ 1.0 (物理上限)。"""
        self.assertLessEqual(MIN_ERROR_RESPONSE_SCHEMA_COVERAGE, 1.0)


if __name__ == "__main__":
    unittest.main()
