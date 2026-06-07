"""R317 · Notification permission 三层一致性 invariant
(v3.7 三层一致性 pattern 3rd app)。

背景
----

v3.7 三层一致性 pattern 至今已应用 2 次:

1. R306 (cr61) — **CSP nonce**: HTTP response header + Jinja template ``nonce=``
   + Python context injection 三层一致
2. R312 (cr62) — **PWA Service Worker cache**: Flask Cache-Control header +
   SW JS constants + Runtime cache cleanup 三层一致

R317 是第 3 次应用, 锁定 **Web Notification permission** 的三层一致性:

- **Layer 1 (Python config / config schema)**:
  ``NotificationConfig.web_permission_auto_request: bool = True``
  ↔ JSON key ``auto_request_permission``
  ↔ ``/api/get-notification-config`` API 暴露
- **Layer 2 (浏览器配置层, settings-manager.js)**:
  ``defaultSettings.autoRequestPermission: true``
  ↔ 从 ``serverConfig.auto_request_permission`` 读
  ↔ 落地到 ``localStorage`` 持久化
- **Layer 3 (浏览器运行时层, notification-manager.js)**:
  ``this.config.autoRequestPermission`` 门控
  ↔ ``Notification.requestPermission()`` 真实浏览器 API 调用
  ↔ user gesture binding (``bindAutoPermissionRequest``)

**为什么三层都要锁?**

任何一层与其他两层 drift 都会出现 user-visible bug:

- L1 关 / L2 开 / L3 开 → server 默认禁用但浏览器仍然弹窗 (用户被"突袭")
- L1 开 / L2 关 / L3 开 → 用户在 settings 关了, 但因为 notification-manager
  直接读 default 仍弹 (UX 错觉)
- L1 开 / L2 开 / L3 关 → 配置看起来允许, 但实际不弹 ("功能坏了" 反馈)

R317 invariant 强制三层 key name + 默认值 + 字段流向都一致, 任何一层未来
被改名或默认值漂移立刻 fail, 阻止 silent regression。

Pattern lineage:

- 1st: R306 (cr61) — CSP nonce
- 2nd: R312 (cr62) — PWA SW cache
- **3rd: R317 (本 commit)** — Web Notification permission

到此 v3.7 三层一致性 pattern **3 个应用全部达成**, 进入 **v3.7 完全工业化**
(与 v3.6 同等级别)。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

JS_DIR = SRC / "ai_intervention_agent" / "static" / "js"

_PY_NOTIF_MGR = SRC / "ai_intervention_agent" / "notification_manager.py"
_JS_SETTINGS_MGR = JS_DIR / "settings-manager.js"
_JS_NOTIF_MGR = JS_DIR / "notification-manager.js"


# ------------------------------------------------------------------
# Layer 1 — Python config schema
# ------------------------------------------------------------------


class TestLayer1PythonConfigContract:
    """Python `NotificationConfig.web_permission_auto_request` 字段契约。

    - 字段名固定: ``web_permission_auto_request``
    - 类型固定: ``bool``
    - 默认值固定: ``True``
    - JSON key (从 config file 读): ``auto_request_permission``
    """

    def test_python_field_with_default_true(self):
        from ai_intervention_agent.notification_manager import NotificationConfig

        fields = NotificationConfig.model_fields
        assert "web_permission_auto_request" in fields, (
            "R317 Layer 1: NotificationConfig must have "
            "`web_permission_auto_request` field"
        )
        finfo = fields["web_permission_auto_request"]
        assert finfo.default is True, (
            f"R317 Layer 1: web_permission_auto_request default must be True, "
            f"got {finfo.default!r}"
        )
        assert finfo.annotation is bool, (
            f"R317 Layer 1: web_permission_auto_request type must be bool, "
            f"got {finfo.annotation!r}"
        )

    def test_python_config_reads_snake_case_key(self):
        text = _PY_NOTIF_MGR.read_text(encoding="utf-8")
        pattern = (
            r"web_permission_auto_request\s*=\s*cfg\.get\(\s*"
            r'["\']auto_request_permission["\']\s*,\s*True\s*\)'
        )
        assert re.search(pattern, text), (
            "R317 Layer 1: Python must read JSON key 'auto_request_permission' "
            "from config, default True. Current pattern not found:\n"
            f"  {pattern}"
        )

    def test_python_api_exposes_snake_case_key(self):
        text = _PY_NOTIF_MGR.read_text(encoding="utf-8")
        pattern = (
            r'["\']auto_request_permission["\']\s*:\s*self\.config\.'
            r"web_permission_auto_request"
        )
        assert re.search(pattern, text), (
            "R317 Layer 1: Python API must expose 'auto_request_permission' "
            "as snake_case key mapping from config.web_permission_auto_request"
        )


# ------------------------------------------------------------------
# Layer 2 — settings-manager.js (浏览器配置层)
# ------------------------------------------------------------------


def _strip_js_comments(text: str) -> str:
    """删除单行 // 和多行 /* */ 注释, 避免注释里的字符串被误匹配。"""
    text = re.sub(r"/\*[\s\S]*?\*/", "", text)
    text = re.sub(r"//[^\n]*", "", text)
    return text


class TestLayer2SettingsManagerContract:
    """settings-manager.js 必须:
    - defaultSettings.autoRequestPermission: true (camelCase, 默认 true)
    - 从 serverConfig.auto_request_permission 读 (snake_case bridging)
    - fallback 到 defaultSettings.autoRequestPermission
    """

    def test_settings_manager_default_is_true(self):
        text = _strip_js_comments(_JS_SETTINGS_MGR.read_text(encoding="utf-8"))
        pattern = r"autoRequestPermission\s*:\s*true"
        assert re.search(pattern, text), (
            "R317 Layer 2: settings-manager.js defaultSettings must have "
            "`autoRequestPermission: true`"
        )

    def test_settings_manager_reads_snake_case_from_server(self):
        text = _strip_js_comments(_JS_SETTINGS_MGR.read_text(encoding="utf-8"))
        # serverConfig.auto_request_permission ?? this.defaultSettings.autoRequestPermission
        pattern = (
            r"autoRequestPermission\s*:\s*\n?\s*serverConfig\."
            r"auto_request_permission\s*\?\?\s*\n?\s*this\.defaultSettings\."
            r"autoRequestPermission"
        )
        assert re.search(pattern, text), (
            "R317 Layer 2: settings-manager.js loadSettings() must bridge "
            "serverConfig.auto_request_permission → "
            "defaultSettings.autoRequestPermission with ?? fallback"
        )


# ------------------------------------------------------------------
# Layer 3 — notification-manager.js (浏览器运行时层)
# ------------------------------------------------------------------


class TestLayer3NotificationManagerContract:
    """notification-manager.js 必须:
    - config.autoRequestPermission: true (默认值)
    - bindAutoPermissionRequest 必须 check config.autoRequestPermission
    - 调用 Notification.requestPermission()
    """

    def test_notification_manager_default_is_true(self):
        text = _strip_js_comments(_JS_NOTIF_MGR.read_text(encoding="utf-8"))
        pattern = r"autoRequestPermission\s*:\s*true"
        assert re.search(pattern, text), (
            "R317 Layer 3: notification-manager.js config default must have "
            "`autoRequestPermission: true`"
        )

    def test_notification_manager_gates_auto_bind_by_config(self):
        text = _strip_js_comments(_JS_NOTIF_MGR.read_text(encoding="utf-8"))
        # if (!this.config.autoRequestPermission || ...) { ... removeAutoPermissionRequestListeners ... }
        pattern = r"!this\.config\.autoRequestPermission\b"
        assert re.search(pattern, text), (
            "R317 Layer 3: notification-manager.js bindAutoPermissionRequest "
            "must gate by `!this.config.autoRequestPermission` to skip when "
            "user opts out"
        )

    def test_notification_manager_calls_browser_api(self):
        text = _strip_js_comments(_JS_NOTIF_MGR.read_text(encoding="utf-8"))
        assert "Notification.requestPermission" in text, (
            "R317 Layer 3: notification-manager.js must call "
            "Notification.requestPermission() (real browser API)"
        )


# ------------------------------------------------------------------
# Cross-layer — 三层之间字段名 / 默认值 / bridging 必须一致
# ------------------------------------------------------------------


class TestCrossLayerConsistency:
    """三层一致性最关键的检查 — 没有 silent drift。"""

    def test_python_default_eq_js_settings_default_eq_js_runtime_default(self):
        """Layer 1 = Layer 2 = Layer 3 默认值都必须是 True/true。"""
        from ai_intervention_agent.notification_manager import NotificationConfig

        py_default = NotificationConfig.model_fields[
            "web_permission_auto_request"
        ].default
        assert py_default is True

        # JS Layer 2 + 3: 默认值都 true (已分别在 layer 类里验证, 这里 cross-check)
        l2_text = _strip_js_comments(_JS_SETTINGS_MGR.read_text(encoding="utf-8"))
        l3_text = _strip_js_comments(_JS_NOTIF_MGR.read_text(encoding="utf-8"))
        for layer_name, text in [("Layer 2", l2_text), ("Layer 3", l3_text)]:
            # 必须有 autoRequestPermission: true (不是 false)
            assert re.search(r"autoRequestPermission\s*:\s*true", text), (
                f"R317 cross-layer: {layer_name} default must be true to "
                "match Python Layer 1 default"
            )
            # 反向检查: 不能有 autoRequestPermission: false 字面量
            assert not re.search(r"autoRequestPermission\s*:\s*false", text), (
                f"R317 cross-layer: {layer_name} contains "
                "`autoRequestPermission: false` literal, violating "
                "default-true contract"
            )

    def test_json_bridge_key_is_consistent_snake_case(self):
        """三层之间的 bridging key 必须是 ``auto_request_permission`` (snake)。

        Python config file key + Python API exposing key + JS settings-manager
        bridging from server, 三个地方都引用同一个 key 字符串。
        """
        py_text = _PY_NOTIF_MGR.read_text(encoding="utf-8")
        l2_text = _strip_js_comments(_JS_SETTINGS_MGR.read_text(encoding="utf-8"))

        # Python 中至少出现 2 次 (一次读 config 一次暴露 API)
        py_matches = re.findall(r'["\']auto_request_permission["\']', py_text)
        assert len(py_matches) >= 2, (
            f"R317 cross-layer: Python must reference 'auto_request_permission' "
            f"snake_case key at least 2x (read + expose), found "
            f"{len(py_matches)}"
        )

        # JS settings-manager 必须引用 serverConfig.auto_request_permission
        assert re.search(r"serverConfig\.auto_request_permission\b", l2_text), (
            "R317 cross-layer: settings-manager.js must read "
            "serverConfig.auto_request_permission (the bridge key)"
        )

    def test_js_camel_case_key_is_consistent(self):
        """Layer 2 + Layer 3 浏览器侧统一用 ``autoRequestPermission`` (camelCase)。"""
        l2_text = _strip_js_comments(_JS_SETTINGS_MGR.read_text(encoding="utf-8"))
        l3_text = _strip_js_comments(_JS_NOTIF_MGR.read_text(encoding="utf-8"))
        for layer_name, text in [("Layer 2", l2_text), ("Layer 3", l3_text)]:
            assert "autoRequestPermission" in text, (
                f"R317 cross-layer: {layer_name} must use camelCase "
                "`autoRequestPermission` field name"
            )
            # 不能用 snake_case (除了 bridging 处, 但 bridging 是从 serverConfig
            # 读的, 用的是 serverConfig.xxx, 不会与配置字段冲突)
            # 注意: 故意不禁止 snake_case, 因为 bridging 处合法使用


# ------------------------------------------------------------------
# Pattern lineage marker
# ------------------------------------------------------------------


class TestR317LineageMarker:
    """R317 是 v3.7 三层一致性 pattern 3rd app, 锁定 docstring 引用。"""

    def test_this_file_contains_r317_marker(self):
        text = Path(__file__).read_text(encoding="utf-8")
        assert "R317" in text
        assert "三层一致性" in text or "three-layer" in text.lower()

    def test_this_file_references_prior_apps_r306_r312(self):
        text = Path(__file__).read_text(encoding="utf-8")
        for prior in ("R306", "R312"):
            assert prior in text, (
                f"R317 docstring must cite prior 三层一致性 app: {prior}"
            )

    def test_this_file_documents_three_layers(self):
        text = Path(__file__).read_text(encoding="utf-8")
        for kw in (
            "Layer 1",
            "Layer 2",
            "Layer 3",
            "web_permission_auto_request",
            "autoRequestPermission",
            "auto_request_permission",
            "Notification.requestPermission",
        ):
            assert kw in text, f"R317 docstring missing keyword: {kw!r}"
