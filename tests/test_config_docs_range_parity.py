r"""防回归：``docs/configuration{,.zh-CN}.md`` 表格中的数值范围必须 = ``shared_types.SECTION_MODELS`` 实际允许范围。

历史背景
---------
``shared_types.py`` 在 commit ``cbe5b9a``（v1.5.x 早期 TypedDict → Pydantic
重构）给每个数值字段加上了 ``BeforeValidator(_clamp_int(min, max, default))``
钳位器；commit ``d0e60ea`` 后又把 ``[feedback]::backend_max_wait`` 的
上限从 3600 抬到 7200、``frontend_countdown`` 上限从 250 抬到 3600。
两份 ``docs/configuration*.md`` 表格里的"范围"列**没有**跟上，于是
v1.5.x 整条线上 5 处文档/代码不一致：

  - ``[web_ui]::http_request_timeout`` doc 写 ``[1, 300]``，实际 ``[1, 600]``
  - ``[web_ui]::http_max_retries`` doc 写 ``[0, 10]``，实际 ``[0, 20]``
  - ``[web_ui]::http_retry_delay`` doc 写 ``[0.1, 60.0]``，实际 ``[0, 60]``
  - ``[feedback]::backend_max_wait`` doc 写 ``[60, 3600]``，实际 ``[10, 7200]``
  - ``[feedback]::frontend_countdown`` doc 写 ``[30, 250]``，实际 ``[10, 3600]``

修复完后加这个回归位，把"配置文档范围 = SECTION_MODELS 钳位边界"的
契约锁住——以后任何 ``_clamp_int(...)`` / ``_clamp_float(...)`` 边界变更都
必须同时更新两份 ``docs/configuration*.md`` 才能合入。

设计原则
--------
- **Introspection 而非硬编码期望值**——用 ``__closure__`` 反查 closure
  cell 拿到 (min_val, max_val)。这样字段加减不需要改测试，只要
  ``shared_types`` 还在用 ``_clamp_int`` 系列工厂函数即可工作。
- **算法稳定性**：``_clamp_int(min_val, max_val, default)`` closure cell
  按 inner function 的引用顺序排列（Python 实现细节）。我们对 cell 的整
  数值 ``sorted()`` 后取头尾——``default`` 按 ``_clamp_int`` 的合约必须
  位于 ``[min_val, max_val]`` 之内，所以 ``min(sorted)`` 永远是 ``min_val``、
  ``max(sorted)`` 永远是 ``max_val``。
- **doc 解析双语共享一套正则**：英文 ``Range \`[lo, hi]\``` + 中文 ``范围
  \`[lo, hi]\``` 两个写法都接受；浮点（``0.1``、``1.0``）和整数都兼容。
- 与 ``test_config_docs_parity.py`` 形成互补：那份只锁 key 集合一致性，
  本份锁数值边界。两层加起来，一个新增字段必须 (a) 出现在 doc 表格、
  (b) doc 范围与 ``_clamp_int`` 边界一致——CI 才允许合入。
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

DOC_PATHS = {
    "en": REPO_ROOT / "docs" / "configuration.md",
    "zh-CN": REPO_ROOT / "docs" / "configuration.zh-CN.md",
}

# 英文 / 中文写法各一条；section 标题双语都形如 ``### `name``` 或 ``### `name`（CN）``。
SECTION_HEADING_RE = re.compile(
    r"^###\s+`([a-z_]+)`(?:\s*[（(].*?[）)])?\s*$", re.MULTILINE
)
RANGE_EN_RE = re.compile(
    r"^\|\s*`([a-z_][a-z0-9_]*)`.*?[Rr]ange\s*`\[\s*([\d.]+)\s*,\s*([\d.]+)\s*\]`",
    re.MULTILINE,
)
RANGE_ZH_RE = re.compile(
    r"^\|\s*`([a-z_][a-z0-9_]*)`.*?范围\s*`\[\s*([\d.]+)\s*,\s*([\d.]+)\s*\]`",
    re.MULTILINE,
)


def _introspect_field_bounds(model_cls):
    """从 Pydantic 模型字段的 ``BeforeValidator`` closure 中拿出 (min, max) 元组。

    返回 ``{field_name: (min, max)}``——只对 ``shared_types._clamp_int*`` /
    ``_clamp_float`` 生成的 validator 有效（其他 metadata 会被静默跳过）。
    """
    bounds: dict[str, tuple[float, float]] = {}
    for name, info in model_cls.model_fields.items():
        for meta in info.metadata:
            func = getattr(meta, "func", None)
            if func is None:
                continue
            closure = getattr(func, "__closure__", None)
            if closure is None:
                continue
            cell_values = [c.cell_contents for c in closure]
            ints = [
                v for v in cell_values if isinstance(v, int) and not isinstance(v, bool)
            ]
            floats = [
                v
                for v in cell_values
                if isinstance(v, float) and not isinstance(v, bool)
            ]
            nums = ints if len(ints) >= 2 else floats
            if len(nums) >= 2:
                nums_sorted = sorted(nums[:3] if len(nums) >= 3 else nums)
                bounds[name] = (nums_sorted[0], nums_sorted[-1])
                break
    return bounds


def _parse_doc_ranges(doc_path: Path) -> dict[str, dict[str, tuple[float, float]]]:
    r"""从一份配置 doc 里抽出所有 ``Range \`[lo, hi]\``` 形式的数值。

    返回 ``{section_name: {key: (lo, hi)}}``——只覆盖文档明确写了范围的字段；
    没有写范围的字段（比如 ``host``、``language``）静默跳过，不视为 missing。
    """
    text = doc_path.read_text(encoding="utf-8")
    sections: dict[str, dict[str, tuple[float, float]]] = {}
    headings = list(SECTION_HEADING_RE.finditer(text))
    for i, m in enumerate(headings):
        section = m.group(1)
        body_start = m.end()
        body_end = headings[i + 1].start() if i + 1 < len(headings) else len(text)
        body = text[body_start:body_end]
        sec_data = sections.setdefault(section, {})
        for rm in list(RANGE_EN_RE.finditer(body)) + list(RANGE_ZH_RE.finditer(body)):
            key = rm.group(1)
            lo_str, hi_str = rm.group(2), rm.group(3)
            lo: float = float(lo_str) if "." in lo_str else int(lo_str)
            hi: float = float(hi_str) if "." in hi_str else int(hi_str)
            sec_data[key] = (lo, hi)
    return sections


class TestConfigDocsRangeParity(unittest.TestCase):
    """``docs/configuration{,.zh-CN}.md`` 范围标注必须与 ``SECTION_MODELS`` 反推出的 (min, max) 一致。"""

    def setUp(self) -> None:
        self.code_bounds = {
            section: _introspect_field_bounds(model)
            for section, model in SECTION_MODELS.items()
        }
        # Sanity: 至少要 introspect 出一组边界，否则我们没有在测真实 invariant
        total_bounded_fields = sum(len(b) for b in self.code_bounds.values())
        self.assertGreater(
            total_bounded_fields,
            0,
            "introspect_field_bounds 没找到任何 closure-bounded 字段——说明 _clamp_int 实现细节变了，"
            "测试自身逻辑需要先随之更新",
        )

    def _assert_doc_matches(self, lang: str) -> None:
        doc_path = DOC_PATHS[lang]
        doc_ranges = _parse_doc_ranges(doc_path)

        for section, code_kvs in self.code_bounds.items():
            for key, (lo, hi) in code_kvs.items():
                doc_kvs = doc_ranges.get(section, {})
                if key not in doc_kvs:
                    # doc 没写范围（可能用其他自然语言描述，或是该字段不需要范围说明）
                    # 不视为错误——只要 doc 写了范围，就必须与代码一致
                    continue
                doc_lo, doc_hi = doc_kvs[key]
                with self.subTest(lang=lang, section=section, key=key):
                    # 用 == 而非 isclose：边界值都是有意选定的整数 / 简单浮点（如 0.1），
                    # 不会有浮点误差风险
                    self.assertEqual(
                        (doc_lo, doc_hi),
                        (lo, hi),
                        f"{doc_path.name}::[{section}].{key}: doc says [{doc_lo}, {doc_hi}] "
                        f"but shared_types.{section}.{key} clamps to [{lo}, {hi}]. "
                        f"Either update the doc to match _clamp_int(...) or "
                        f"update _clamp_int to match the documented range.",
                    )

    def test_english_doc_matches_introspected_ranges(self) -> None:
        self._assert_doc_matches("en")

    def test_chinese_doc_matches_introspected_ranges(self) -> None:
        self._assert_doc_matches("zh-CN")


class TestIntrospectionSelfCheck(unittest.TestCase):
    """守住 introspect 算法本身——重构 _clamp_int 时，未来的人不要悄悄让本测试变成 vacuous truth。"""

    def test_introspect_recovers_known_bounds(self) -> None:
        # 已知的几个 anchor：v1.5.22 时 shared_types.py 的硬数字
        anchors = {
            "notification": {
                "web_timeout": (1, 600000),
                "sound_volume": (0, 100),
                "bark_timeout": (1, 300),
            },
            "web_ui": {
                "port": (1, 65535),
                "http_max_retries": (0, 20),
            },
            "feedback": {
                "backend_max_wait": (10, 7200),
                "frontend_countdown": (10, 3600),
            },
        }
        for section, expected in anchors.items():
            actual = _introspect_field_bounds(SECTION_MODELS[section])
            for key, exp in expected.items():
                with self.subTest(section=section, key=key):
                    self.assertIn(
                        key, actual, f"introspect didn't pick up [{section}].{key}"
                    )
                    self.assertEqual(
                        actual[key],
                        exp,
                        f"introspect got the wrong bounds for [{section}].{key}",
                    )


if __name__ == "__main__":
    unittest.main()
