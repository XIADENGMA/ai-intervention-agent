"""TOML 解析/保存引擎 Mixin。"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

import tomlkit
from tomlkit.container import OutOfOrderTableProxy
from tomlkit.exceptions import TOMLKitError
from tomlkit.items import Table

from ai_intervention_agent.enhanced_logging import EnhancedLogger

if TYPE_CHECKING:
    pass

logger = EnhancedLogger(__name__)

# 文档里的一段，tomlkit 给出的是 Table，或者 OutOfOrderTableProxy：同一段由几处拼成时（用点号键写
# ``notification.sound_volume = 80`` 又接着写 ``notification.enabled = true``，或者 ``[a]`` 被别的表隔开后
# 又出现 ``[a.b]``）。两者都能按键读写，写进去的地方也对；唯独整段替换会出错（R917）。
_TABLE_LIKE = (Table, OutOfOrderTableProxy)


def _same_toml_data(left: Any, right: Any) -> bool:
    """两份解析出来的 TOML 数据是否相同：表不看键的顺序，tuple 当作 list，NaN 等于 NaN，布尔值不等于整数。"""
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(
            _same_toml_data(value, right[key]) for key, value in left.items()
        )
    if isinstance(left, list | tuple) and isinstance(right, list | tuple):
        return len(left) == len(right) and all(
            _same_toml_data(a, b) for a, b in zip(left, right, strict=True)
        )
    if (
        isinstance(left, float)
        and isinstance(right, float)
        and math.isnan(left)
        and math.isnan(right)
    ):
        return True
    return isinstance(left, bool) == isinstance(right, bool) and left == right


def _contains_toml_data(whole: Any, part: Any) -> bool:
    """``whole`` 是否包含 ``part``：``part`` 是表就逐键包含（``whole`` 里多出来的键不管），其余要相同。"""
    if isinstance(part, dict):
        return isinstance(whole, dict) and all(
            key in whole and _contains_toml_data(whole[key], value)
            for key, value in part.items()
        )
    return _same_toml_data(whole, part)


def _merged_toml_data(original: Any, update: Any) -> Any:
    """把 ``update`` 叠到 ``original`` 上，规则同 ``_update_toml_table``：两边都是表就逐键合并，其余整个替换。"""
    if isinstance(original, dict) and isinstance(update, dict):
        merged = dict(original)
        for key, value in update.items():
            merged[key] = (
                _merged_toml_data(original[key], value) if key in original else value
            )
        return merged
    return update


class TomlEngineMixin:
    """TOML 格式配置文件的解析/保存方法集合。"""

    if TYPE_CHECKING:
        _original_content: str | None

        @staticmethod
        def _exclude_network_security(config: dict[str, Any]) -> dict[str, Any]: ...

    @staticmethod
    def _parse_toml(content: str) -> dict[str, Any]:
        """解析 TOML 内容为普通 dict（丢弃 tomlkit 元数据）"""
        doc = tomlkit.parse(content)
        return doc.unwrap()  # type: ignore[return-value]

    @staticmethod
    def _parse_toml_document(content: str) -> tomlkit.TOMLDocument:
        """解析 TOML 内容为 TOMLDocument（保留注释/格式元数据，用于写回）"""
        return tomlkit.parse(content)

    def _save_toml_with_comments(self, config: dict[str, Any]) -> str:
        """保存 TOML 配置并保留原有注释和格式，排除 network_security"""
        config_to_save = self._exclude_network_security(config.copy())
        if not self._original_content:
            return tomlkit.dumps(tomlkit.item(config_to_save))

        doc = self._parse_toml_document(self._original_content)
        for section_key, section_value in config_to_save.items():
            if section_key == "network_security":
                continue

            if isinstance(section_value, dict) and section_key in doc:
                existing_table = doc[section_key]
                if isinstance(existing_table, _TABLE_LIKE):
                    self._update_toml_table(existing_table, section_value)
                else:
                    doc[section_key] = section_value
            elif section_key not in doc:
                doc[section_key] = section_value
            else:
                doc[section_key] = section_value

        updates = {k: v for k, v in config_to_save.items() if k != "network_security"}
        return self._toml_as_intended(
            tomlkit.dumps(doc), self._original_content, updates
        )

    def _toml_as_intended(
        self, text: str, original: str, updates: dict[str, Any]
    ) -> str:
        """核对写出去的 TOML：读回来要包含这次的更改，原文件里没动的顶层键要原样还在（R917）。

        保留排版的写法是让 tomlkit 在原文件的排版上改，有的排版它会写出另一个意思的文件：内联表换成
        表头之后，后面的点号键归到了那张表底下；点号键拼成的表整段换成嵌套表……读回来对不上，就改用
        整份重新生成：注释和排版不再保留，设置不变。重新生成的也对不上（值写不成读得回来的 TOML）
        就放弃写入，宁可不写，也不写一个意思不对的文件。
        """
        before = self._parse_toml(original)
        try:
            after = self._parse_toml(text)
        except (ValueError, TOMLKitError) as e:
            problem = f"写出的内容解析失败: {e}"
        else:
            untouched = (k for k in before if k not in updates)
            if _contains_toml_data(after, updates) and all(
                k in after and _same_toml_data(after[k], before[k]) for k in untouched
            ):
                return text
            problem = "读回来的内容和要写的不一致"
        logger.warning(
            f"保留原有排版写回会改变配置的含义（{problem}），改为重新生成整个文件："
            "设置不变，注释和排版不再保留"
        )
        expected = _merged_toml_data(before, updates)
        rebuilt = tomlkit.dumps(tomlkit.item(expected))
        if not _same_toml_data(self._parse_toml(rebuilt), expected):
            raise ValueError("配置无法写成读回来一致的 TOML，已放弃写入")
        return rebuilt

    @staticmethod
    def _update_toml_table(
        table: Table | OutOfOrderTableProxy, values: dict[str, Any]
    ) -> None:
        """递归更新 tomlkit 的表（Table 或 OutOfOrderTableProxy），已有的键原地改，新键追加（保留格式/注释）。

        不能把一段拼成的表整段换成 dict：tomlkit 会沿用原来点号键的写法，输出 ``[notification]`` 后面
        接着 ``notification.sound_volume = 58``，文件读回来是表里套着自己，所有设置都丢了（R917）。
        """
        for key, value in values.items():
            if key in table:
                existing = table[key]
                if isinstance(value, dict) and isinstance(existing, _TABLE_LIKE):
                    TomlEngineMixin._update_toml_table(existing, value)
                else:
                    table[key] = value
            else:
                table[key] = value

    def _save_network_security_toml(self, ns_config: dict[str, Any]) -> str:
        """仅更新 TOML 文件中的 network_security 段并返回完整内容"""
        if not self._original_content:
            logger.warning("无原始内容，无法保留格式保存 network_security")
            return ""

        doc = self._parse_toml_document(self._original_content)
        if "network_security" in doc and isinstance(
            doc["network_security"], _TABLE_LIKE
        ):
            self._update_toml_table(doc["network_security"], ns_config)
        else:
            doc["network_security"] = ns_config

        return self._toml_as_intended(
            tomlkit.dumps(doc),
            self._original_content,
            {"network_security": ns_config},
        )
