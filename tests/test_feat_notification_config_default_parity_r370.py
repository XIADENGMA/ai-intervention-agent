"""R370 · NotificationConfig (runtime) ↔ NotificationSectionConfig
(TOML) 默认值漂移防护 invariant (cycle-42 #B2, **新维度: 配置默认值
漂移防护**)。

背景
----

项目内有两个 Pydantic 模型描述通知配置:

- ``NotificationConfig`` (``notification_manager.py``): 运行时模型, 字
  段名按 Python 习惯命名 (``web_permission_auto_request``)
- ``NotificationSectionConfig`` (``shared_types.py``): TOML 配置 schema,
  字段名按 user-facing 习惯命名 (``auto_request_permission``)

两个模型间有 bridge code (``notification_manager.py:290`` 等) 做 TOML
→ runtime 翻译。但**默认值**这条 invariant 之前没有自动锁定:

- 用户在 TOML 内不设 ``sound_enabled`` → TOML schema 默认 ``True``
- runtime 实际读到 ``True`` (走 ``cfg.get("sound_enabled", True)`` 兜
  底)

如果 TOML schema 默认 ``True`` 但运行时 ``cfg.get("sound_enabled",
False)`` (typo), 用户的"默认体验"就和"显式 ``sound_enabled=true``"
不一致 — 这是 silent 行为漂移。

R370 audit 目标
---------------

锁定两个模型中**同名字段**的默认值等价:

- 对于同名字段 (e.g., ``sound_enabled``, ``retry_count``,
  ``bark_url``), 必须默认值相同;
- 对于 ``sound_volume`` (TOML int 0-100, runtime float 0-1), 按比例
  normalization 后必须等价 (e.g., 80 / 100 == 0.8);
- 对于翻译字段 (e.g., ``web_permission_auto_request`` ↔
  ``auto_request_permission``), R370 不强制 (有 bridge code 处理),
  但放入 TRANSLATED_FIELDS 白名单备查。

R370 invariant (3 层)
---------------------

1. **Layer 1 (Anchor)**: 两个模型都可加载, ``model_fields`` 非空
2. **Layer 2 (Default parity for shared-name fields)**: 共享字段名的
   默认值必须等价 (int/float normalization 后)
3. **Layer 3 (Translated field whitelist)**: 翻译字段白名单必须含至少
   ``web_permission_auto_request`` ↔ ``auto_request_permission`` 这对
   (证明翻译机制在用), 且每个白名单字段在对应模型上真的存在

methodology lineage
-------------------

R370 与 ``test_server_config_defaults_parity.py`` (feedback section)
同源, 但扩展到 notification section, 是 **"配置默认值漂移防护"** 维度
的第 2 应用 (第 1 应用是 feedback section parity, 已存在多个 cycle)。
"""

from __future__ import annotations

from pathlib import Path

# 翻译字段: TOML 名 ↔ runtime 名 (bridge code 处理, R370 不强制 default parity)
TRANSLATED_FIELDS: list[tuple[str, str]] = [
    # (toml_field_name, runtime_field_name)
    ("auto_request_permission", "web_permission_auto_request"),
]


def _equivalent_defaults(toml_val: object, runtime_val: object) -> bool:
    """判断 TOML 默认值与 runtime 默认值是否等价。"""
    if toml_val == runtime_val:
        return True
    # sound_volume: TOML int 0-100, runtime float 0-1
    return (
        isinstance(toml_val, int)
        and isinstance(runtime_val, float)
        and 0 <= toml_val <= 100
        and 0.0 <= runtime_val <= 1.0
        and abs(toml_val / 100.0 - runtime_val) < 1e-9
    )


class TestLayer1AnchorBothModelsLoadable:
    """Layer 1: 两个模型都可加载, ``model_fields`` 非空。"""

    def test_runtime_model_loadable(self):
        from ai_intervention_agent.notification_manager import (
            NotificationConfig,
        )

        fields = set(NotificationConfig.model_fields.keys())
        assert len(fields) >= 15, (
            f"R370-L1: NotificationConfig has only {len(fields)} "
            f"fields, expected >= 15 (current ~26)"
        )

    def test_toml_section_model_loadable(self):
        from ai_intervention_agent.shared_types import (
            NotificationSectionConfig,
        )

        fields = set(NotificationSectionConfig.model_fields.keys())
        assert len(fields) >= 15, (
            f"R370-L1: NotificationSectionConfig has only {len(fields)} "
            f"fields, expected >= 15"
        )


class TestLayer2DefaultParity:
    """Layer 2: 共享字段名的默认值必须等价。"""

    def test_shared_name_field_defaults_match(self, subtests):
        from ai_intervention_agent.notification_manager import (
            NotificationConfig,
        )
        from ai_intervention_agent.shared_types import (
            NotificationSectionConfig,
        )

        runtime_fields = NotificationConfig.model_fields
        toml_fields = NotificationSectionConfig.model_fields
        shared_names = set(runtime_fields.keys()) & set(toml_fields.keys())

        # 至少有 10 个共享字段, 否则可能模型被重构, 测试假阴性
        assert len(shared_names) >= 10, (
            f"R370-L2: only {len(shared_names)} shared field names "
            f"between Runtime / TOML notification configs — expected "
            f">= 10. Models may have diverged unexpectedly."
        )

        violations: list[str] = []
        for name in sorted(shared_names):
            with subtests.test(field=name):
                rt_def = runtime_fields[name].default
                toml_def = toml_fields[name].default
                if not _equivalent_defaults(toml_def, rt_def):
                    violations.append(
                        f"  {name}: TOML default={toml_def!r}, "
                        f"runtime default={rt_def!r}"
                    )
        if violations:
            raise AssertionError(
                f"R370-L2: {len(violations)} shared-name field(s) have "
                f"divergent defaults:\n"
                + "\n".join(violations)
                + "\nFix: align defaults in both models, or add a "
                "normalization helper to ``_equivalent_defaults()`` "
                "if the divergence is intentional (e.g., unit "
                "conversion like sound_volume int 0-100 ↔ float 0-1)."
            )


class TestLayer3TranslatedFieldWhitelist:
    """Layer 3: 翻译字段白名单必须含核心翻译对, 字段必须真实存在。"""

    def test_translated_fields_not_empty(self):
        assert len(TRANSLATED_FIELDS) > 0, (
            "R370-L3: TRANSLATED_FIELDS is empty — should at least "
            "contain web_permission_auto_request ↔ "
            "auto_request_permission pair as evidence the translation "
            "bridge is in active use."
        )

    def test_translated_fields_exist_on_models(self):
        from ai_intervention_agent.notification_manager import (
            NotificationConfig,
        )
        from ai_intervention_agent.shared_types import (
            NotificationSectionConfig,
        )

        runtime_names = set(NotificationConfig.model_fields.keys())
        toml_names = set(NotificationSectionConfig.model_fields.keys())
        for toml_name, runtime_name in TRANSLATED_FIELDS:
            assert toml_name in toml_names, (
                f"R370-L3: translated TOML field {toml_name!r} not on "
                f"NotificationSectionConfig (stale whitelist?)"
            )
            assert runtime_name in runtime_names, (
                f"R370-L3: translated runtime field {runtime_name!r} "
                f"not on NotificationConfig (stale whitelist?)"
            )


class TestR370LineageMarker:
    def test_this_file_contains_r370_marker(self):
        text = Path(__file__).read_text(encoding="utf-8")
        assert "R370" in text

    def test_this_file_references_default_drift_lineage(self):
        text = Path(__file__).read_text(encoding="utf-8")
        for kw in (
            "test_server_config_defaults_parity",
            "配置默认值漂移防护",
        ):
            assert kw in text, f"R370: missing keyword: {kw!r}"
