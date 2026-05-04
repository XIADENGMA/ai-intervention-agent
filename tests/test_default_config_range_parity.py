r"""防回归：``config.toml.default`` / ``config.jsonc.default`` 注释中的数值范围必须 = ``shared_types.SECTION_MODELS`` 实际允许范围。

历史背景
---------
v1.5.x 早期发现两条平行的范围漂移：

1. ``docs/configuration{,.zh-CN}.md`` 表格里的范围数字落后于 Pydantic
   ``_clamp_int`` 边界（已在 ``test_config_docs_range_parity.py`` 锁住）。
2. ``config.toml.default`` / ``config.jsonc.default`` 的 inline 注释也落后了
   同样的数字（例如 ``range [60, 3600]`` / ``范围 [30, 250]``）——这是用户**首
   次接触配置时看到的文档**，比 ``docs/configuration*.md`` 还要面向新人。
   修复后加这个回归位以防再次漂移。

设计原则
--------
- 复用 ``test_config_docs_range_parity._introspect_field_bounds`` introspection；
  避免硬编码 ``(10, 7200)`` 之类的常数。
- 解析策略：默认配置文件的注释都形如 ``range [lo, hi]`` 或 ``范围 [lo, hi]``，
  紧接其后是一行 ``key = val`` (TOML) 或 ``"key": val`` (JSONC)。我们扫描每行，
  捕获 range，再用滑动窗口在后续 5 行内找首个有效 key —— 5 行的窗口足以覆盖
  跨多行注释（例如「作用：限制...」）但不会跨越到下一个字段。
- 不要求 default 文件覆盖**所有** SECTION_MODELS 字段（注释里没写范围的字段
  跳过）；但凡是写了 ``range/范围 [..]`` 的字段，必须与 introspect 结果一致。
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shared_types import SECTION_MODELS
from tests.test_config_docs_range_parity import (
    _introspect_field_bounds,
)

DEFAULT_FILES = {
    "toml": REPO_ROOT / "config.toml.default",
    "jsonc": REPO_ROOT / "config.jsonc.default",
}

# 接受英文 ``range [lo, hi]`` 与中文 ``范围 [lo, hi]``，整数 / 简单浮点都兼容
RANGE_RE = re.compile(
    r"(?:range|范围)\s*[`'\"]?\[\s*([\d.]+)\s*,\s*([\d.]+)\s*\][`'\"]?",
    re.IGNORECASE,
)
# TOML 风格 ``key = val``，与 JSONC 风格 ``"key": val``（捕第一个匹配）
KEY_TOML_RE = re.compile(r"^\s*([a-z_][a-z0-9_]*)\s*=")
KEY_JSONC_RE = re.compile(r'^\s*"([a-z_][a-z0-9_]*)"\s*:')
# section header：TOML 是 ``[section]`` 或 ``[[section]]``；JSONC 是 ``"section": {``
SECTION_TOML_RE = re.compile(r"^\s*\[\[?([a-z_][a-z0-9_]*)\]\]?\s*$")
SECTION_JSONC_RE = re.compile(r'^\s*"([a-z_][a-z0-9_]*)"\s*:\s*\{')

# 单行最多向后看几行找紧邻的字段定义：覆盖跨多行注释，但不跨越到下一个字段
KEY_LOOKAHEAD_LINES = 6


def _parse_default_ranges(
    path: Path, fmt: str
) -> dict[str, dict[str, tuple[float, float]]]:
    r"""扫一份 default 文件，输出 ``{section: {key: (lo, hi)}}``，仅覆盖注释里写了范围的字段。"""
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    section_re = SECTION_TOML_RE if fmt == "toml" else SECTION_JSONC_RE
    key_re = KEY_TOML_RE if fmt == "toml" else KEY_JSONC_RE

    sections: dict[str, dict[str, tuple[float, float]]] = {}
    current_section: str | None = None

    for i, raw in enumerate(lines):
        sm = section_re.match(raw)
        if sm:
            current_section = sm.group(1)
            sections.setdefault(current_section, {})
            continue
        rm = RANGE_RE.search(raw)
        if rm and current_section is not None:
            lo_str, hi_str = rm.group(1), rm.group(2)
            lo: float = float(lo_str) if "." in lo_str else int(lo_str)
            hi: float = float(hi_str) if "." in hi_str else int(hi_str)
            for j in range(i + 1, min(i + 1 + KEY_LOOKAHEAD_LINES, len(lines))):
                km = key_re.match(lines[j])
                if km:
                    sections[current_section][km.group(1)] = (lo, hi)
                    break
    return sections


class TestDefaultConfigRangeParity(unittest.TestCase):
    """``config.{toml,jsonc}.default`` 注释里 ``range/范围 [..]`` 必须 = ``SECTION_MODELS`` 反推边界。"""

    def setUp(self) -> None:
        self.code_bounds = {
            section: _introspect_field_bounds(model)
            for section, model in SECTION_MODELS.items()
        }
        # Sanity check：introspect 至少要拿到一些字段，否则我们没有在测真实 invariant
        total_bounded = sum(len(b) for b in self.code_bounds.values())
        self.assertGreater(total_bounded, 0)

    def _assert_default_matches(self, fmt: str) -> None:
        path = DEFAULT_FILES[fmt]
        default_ranges = _parse_default_ranges(path, fmt)

        # Sanity check：至少要从 default 里抽到几条 range 注释，否则 _parse 算法可能错
        total_ranges = sum(len(v) for v in default_ranges.values())
        self.assertGreater(
            total_ranges,
            5,
            f"{path.name} 抽到的 range 注释数量异常少（{total_ranges}）—— "
            f"_parse_default_ranges 可能解析错了，请先检查正则",
        )

        for section, code_kvs in self.code_bounds.items():
            for key, (lo, hi) in code_kvs.items():
                default_kvs = default_ranges.get(section, {})
                if key not in default_kvs:
                    # default 注释里没写范围（比如 host、language）—— 静默跳过
                    continue
                default_lo, default_hi = default_kvs[key]
                with self.subTest(fmt=fmt, section=section, key=key):
                    self.assertEqual(
                        (default_lo, default_hi),
                        (lo, hi),
                        f"{path.name}::[{section}].{key}: default 注释 "
                        f"range/范围 [{default_lo}, {default_hi}] but "
                        f"shared_types.SECTION_MODELS::{section}.{key} clamps to "
                        f"[{lo}, {hi}]. Either update the default-config inline "
                        f"comment or update _clamp_int(...) bounds so they stay "
                        f"in lockstep.",
                    )

    def test_toml_default_matches_introspected_ranges(self) -> None:
        self._assert_default_matches("toml")

    def test_jsonc_default_matches_introspected_ranges(self) -> None:
        self._assert_default_matches("jsonc")


if __name__ == "__main__":
    unittest.main()
