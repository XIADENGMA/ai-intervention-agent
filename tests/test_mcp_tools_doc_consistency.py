r"""防回归：``docs/mcp_tools{,.zh-CN}.md`` 中的硬编码上限必须 = ``server_config`` 中的常量。

历史背景
---------
``docs/mcp_tools{,.zh-CN}.md`` 是 LLM-facing 工具文档，其中明确写出
``MAX_MESSAGE_LENGTH`` / ``MAX_OPTION_LENGTH`` 的具体数值（``10000`` /
``500``）作为开发者契约。这两个数字最初由 ``server_config.py`` 顶层
常量定义；早期版本其中一个曾被改过（``MAX_OPTION_LENGTH`` 250 → 500
的扩张），但 docs 没跟上。最终是一次 issue 反馈才发现"文档说 250、
代码允许 500，所以用户的合法选项被误以为超长"。本测试是同类漂移的
**直接防御**：

  - ``MAX_MESSAGE_LENGTH`` 改了 → 两份 mcp_tools docs 都必须出现新数字；
  - 同理 ``MAX_OPTION_LENGTH``。

设计原则
--------
- **数字级断言而非语义级**：测试不解析"**10000**"周围的 prose（中英文
  语法不同，太脆），而是直接断言 docs 中**子字符串**出现 ``**<N>**``
  形式（项目当前一致用 backtick + 加粗强调数字常量）。这样未来无论
  prose 怎么调，只要数字依然以加粗形式出现，测试都能通过；改了数字
  必须同时改 docs 才能合入。
- **失败 message 自带修复指引**：dump 当前期望值 + 文件路径，让 reviewer
  无需翻代码就能改 docs。
- 与 ``test_config_docs_range_parity.py``（lock 配置表的 ``Range \`[lo, hi]\```
  数字）+ ``test_config_docs_parity.py``（lock 配置 key 集合）形成三层
  防御，每层守住不同的 docs ↔ code 边界。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from server_config import MAX_MESSAGE_LENGTH, MAX_OPTION_LENGTH

DOC_PATHS = (
    REPO_ROOT / "docs" / "mcp_tools.md",
    REPO_ROOT / "docs" / "mcp_tools.zh-CN.md",
)


class TestMcpToolsDocLimitsMatchCode(unittest.TestCase):
    """``docs/mcp_tools*.md`` 必须出现当前的 MAX_* 数字（项目惯例：``**<N>**`` 加粗）。"""

    def test_docs_mention_max_message_length(self) -> None:
        token = f"**{MAX_MESSAGE_LENGTH}**"
        for path in DOC_PATHS:
            self.assertTrue(path.exists(), f"missing doc: {path}")
            text = path.read_text(encoding="utf-8")
            self.assertIn(
                token,
                text,
                f"{path.relative_to(REPO_ROOT)}: missing **{MAX_MESSAGE_LENGTH}** "
                f"reference (server_config.MAX_MESSAGE_LENGTH = "
                f"{MAX_MESSAGE_LENGTH}). Update doc or update the constant.",
            )

    def test_docs_mention_max_option_length(self) -> None:
        token = f"**{MAX_OPTION_LENGTH}**"
        for path in DOC_PATHS:
            self.assertTrue(path.exists(), f"missing doc: {path}")
            text = path.read_text(encoding="utf-8")
            self.assertIn(
                token,
                text,
                f"{path.relative_to(REPO_ROOT)}: missing **{MAX_OPTION_LENGTH}** "
                f"reference (server_config.MAX_OPTION_LENGTH = "
                f"{MAX_OPTION_LENGTH}). Update doc or update the constant.",
            )

    def test_no_other_4_or_5_digit_length_constants_lurking(self) -> None:
        r"""Sanity 守门：docs 里不应该出现非 MAX_MESSAGE_LENGTH 的 5 位长度数字。

        如果未来有人加 ``**12345**`` 这样的别的硬编码长度限制（误以为这是
        新约定），这个测试可以在 review 阶段暴露：列出所有形如 ``**N**``
        的 4-5 位整数 token，要求每一个都在 ``ALLOWED`` 白名单里（且
        白名单只列出确知合法的 server_config 常量）。
        """
        import re

        # 当前项目允许在 docs/mcp_tools 中加粗出现的"长度类"整数：
        #   10000 = MAX_MESSAGE_LENGTH
        #   500   = MAX_OPTION_LENGTH
        # 注：240 / 250 / 3600 / 7200 (秒级 timeout) 也是合法 token，但它们
        #   也都跟其他真实常量绑定（feedback.frontend_countdown / backend_max_wait
        #   范围），所以一并白名单化。
        allowed = {
            str(MAX_MESSAGE_LENGTH),  # 10000
            str(MAX_OPTION_LENGTH),  # 500
            "240",  # frontend_countdown 默认值
            "3600",  # frontend_countdown 上限
            "7200",  # backend_max_wait 上限
            "10",  # frontend / backend 下限
        }
        bold_int_re = re.compile(r"\*\*(\d{2,5})\*\*")
        for path in DOC_PATHS:
            text = path.read_text(encoding="utf-8")
            unexpected = [m for m in bold_int_re.findall(text) if m not in allowed]
            self.assertFalse(
                unexpected,
                f"{path.relative_to(REPO_ROOT)}: bold integer tokens not in the "
                f"sync'd-with-code whitelist: {sorted(set(unexpected))}. "
                f"Either add the constant to server_config / shared_types and "
                f"extend ALLOWED here, or remove the magic number from the doc.",
            )


if __name__ == "__main__":
    unittest.main()
