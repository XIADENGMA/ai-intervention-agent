"""孤立代理项（lone surrogate）清洗：保证文本一定能编码成 UTF-8。

为什么需要（R845）
~~~~~~~~~~~~~~~~~~
Python 的 ``str`` 可以装下 U+D800–U+DFFF 区间里**没有配成一对**的码点，而这样的字符串没有任何
UTF-8 / JSON 编码：``"\\ud800".encode()`` 抛 ``UnicodeEncodeError``，pydantic-core 的 JSON 序列化抛
``PydanticSerializationError``。标准库 ``json.loads`` 却乐意造出它们：

* 文本里的转义 ``"\\ud800"``（不成对时）；
* ``bytes`` 体里的 ``ED A0 80``——``json.loads`` 对 ``bytes`` 用 ``surrogatepass`` 解码。

pydantic-core 自己的 JSON 解析器会拒绝这种输入（``unexpected end of hex escape``），所以 MCP 客户端
走 stdio 发来的请求里不会有；但 Web UI 读请求体、读表单里的 JSON 文本（``selected_options``）用的是标准库。
一个孤立代理项进了任务结果后：

* ``interactive_feedback`` 返回给客户端的内容序列化时抛错，MCP stdio 的 ``stdout_writer`` 任务组
  整体失败——**MCP 服务进程退出**，Web UI 子进程和队列里所有任务一起没了；
* ``tasks.json`` / ``config.toml`` 的写入每次都抛 ``UnicodeEncodeError``，直到进程重启（脏值一直在内存里）。

所以文本在**进入进程的边界**被修成合法 Unicode：每个孤立代理项换成一个 U+FFFD，跟浏览器、Werkzeug 对
非法 UTF-8 的处理（``errors="replace"``）一致。合法的代理项对（JSON 里的 ``"\\ud83d\\ude00"``）被
``json.loads`` 合并成一个码点，不受影响。
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

REPLACEMENT_CHARACTER = "\ufffd"

# 解析后的 str 里还剩下的代理项码点一定是孤立的（成对的已被 ``json.loads`` 合并成一个码点）。
_LONE_SURROGATE = re.compile("[\ud800-\udfff]")


def _clean(text: str) -> str:
    # ``str.isascii()`` 是 O(1)：绝大多数值（base64 图片、ASCII 提示词）不用扫描。
    # 没匹配时 ``re.sub`` 返回原对象，所以 ``clean is not text`` 就是"改过了"。
    return text if text.isascii() else _LONE_SURROGATE.sub(REPLACEMENT_CHARACTER, text)


def _entries(container: dict[Any, Any] | list[Any]) -> Iterable[tuple[Any, Any]]:
    """``(slot, item)``：字典的 (键, 值)、列表的 (下标, 元素)，``container[slot]`` 就是 ``item``。"""
    return container.items() if isinstance(container, dict) else enumerate(container)


def _clean_keys(mapping: dict[Any, Any]) -> None:
    """字典的键也是文本。保持顺序；清洗后撞名的键，后面的覆盖前面的（和重复键的 JSON 一样）。"""
    if any(isinstance(key, str) and _clean(key) is not key for key in mapping):
        items = [
            (_clean(key) if isinstance(key, str) else key, value)
            for key, value in mapping.items()
        ]
        mapping.clear()
        mapping.update(items)


def scrub_lone_surrogates(value: Any) -> Any:
    """把 ``value`` 里每个字符串的孤立代理项换成 U+FFFD，返回清洗后的值。

    ``str`` 返回新字符串；``dict`` / ``list`` **原地**修好并返回同一个对象——调用方拿的是刚解析出来
    的文档，复制它没有意义：一个 10 MB、330 万个 ``[]`` 的体复制一份要多占 200 MB，而 R828 就是
    为了不在这种体上多占内存才用显式栈检查嵌套深度。这里同样用显式栈（每层一个迭代器），内存只和
    深度成正比、不和宽度成正比，也不会因为嵌套过深而递归爆栈。其他类型（数字、``None``、…）原样返回。
    """
    if isinstance(value, str):
        return _clean(value)
    if not isinstance(value, dict | list):
        return value
    stack = [(value, iter(_entries(value)))]
    while stack:
        container, entries = stack[-1]
        for slot, item in entries:
            if isinstance(item, str):
                clean = _clean(item)
                if clean is not item:
                    container[slot] = clean
            elif isinstance(item, dict | list):
                stack.append((item, iter(_entries(item))))
                break
        else:
            stack.pop()
            if isinstance(container, dict):
                _clean_keys(container)
    return value
