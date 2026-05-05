"""
运行时行为正确性验证测试

针对静态代码审查（Code Review）无法发现的缺陷类型：
- Design Token Drift：硬编码颜色值 vs CSS 变量
- I18n Bootstrap Failure：国际化 key 覆盖率与 locale 一致性
- Configuration Propagation Gap：配置传播完整性
- Integration Gap：跨模块数据流断裂
"""

import json
import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WEB_LOCALES_DIR = REPO_ROOT / "static" / "locales"
VSCODE_LOCALES_DIR = REPO_ROOT / "packages" / "vscode" / "locales"
TEMPLATES_DIR = REPO_ROOT / "templates"
STATIC_JS_DIR = REPO_ROOT / "static" / "js"
VSCODE_DIR = REPO_ROOT / "packages" / "vscode"


def _flatten_keys(d: dict, prefix: str = "") -> set[str]:
    """将嵌套 dict 展平为点分键集合：{"a": {"b": "v"}} → {"a.b"}"""
    keys: set[str] = set()
    for k, v in d.items():
        full = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            keys.update(_flatten_keys(v, full))
        else:
            keys.add(full)
    return keys


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# ============================================================================
# 1. Design Token Drift（排查 Visual Regression）
# ============================================================================

# 需要审计的 CSS 颜色属性
_COLOR_PROPERTIES = (
    "color",
    "background-color",
    "border-color",
    "outline-color",
    "text-decoration-color",
)

# 硬编码颜色值模式：#hex / rgb() / rgba() / hsl() / hsla()
_HARDCODED_COLOR_RE = re.compile(
    r"#[0-9a-fA-F]{3,8}\b|rgba?\s*\(|hsla?\s*\(",
)


class TestDesignTokenDrift(unittest.TestCase):
    """排查 Visual Regression：HTML 模板中不应使用硬编码颜色值，应使用 CSS 变量"""

    def _extract_inline_style_colors(self, html: str) -> list[tuple[int, str, str]]:
        """提取所有内联 style 中使用硬编码颜色值的位置

        Returns:
            [(行号, CSS 属性, 值)] 列表
        """
        violations: list[tuple[int, str, str]] = []
        for line_no, line in enumerate(html.splitlines(), 1):
            style_matches = re.finditer(r'style="([^"]*)"', line, re.IGNORECASE)
            for m in style_matches:
                style_content = m.group(1)
                declarations = style_content.split(";")
                for decl in declarations:
                    decl = decl.strip()
                    if ":" not in decl:
                        continue
                    prop, _, value = decl.partition(":")
                    prop = prop.strip().lower()
                    value = value.strip()
                    if prop not in _COLOR_PROPERTIES:
                        continue
                    if "var(--" in value:
                        continue
                    if _HARDCODED_COLOR_RE.search(value):
                        violations.append((line_no, prop, value))
        return violations

    def test_web_template_no_hardcoded_inline_colors(self):
        """web_ui.html 中 color 相关内联样式不应包含硬编码值（应使用 CSS 变量）"""
        template = TEMPLATES_DIR / "web_ui.html"
        if not template.exists():
            self.skipTest("web_ui.html 不存在")

        html = template.read_text(encoding="utf-8")
        violations = self._extract_inline_style_colors(html)

        if violations:
            msg_lines = [
                "以下内联样式使用了硬编码颜色值（应改为 CSS 变量 var(--...)）："
            ]
            for line_no, prop, value in violations:
                msg_lines.append(f"  行 {line_no}: {prop}: {value}")
            self.fail("\n".join(msg_lines))


# ============================================================================
# 2. I18n Key Coverage（排查 I18n Bootstrap Failure）
# ============================================================================

# 同时匹配：data-i18n / data-i18n-html / data-i18n-title / data-i18n-placeholder /
# data-i18n-alt / data-i18n-value / data-i18n-aria-label。用 [\w-]* 支持含连字符的变体。
_DATA_I18N_RE = re.compile(r'data-i18n(?:-[a-z][\w-]*)?="([^"]+)"')
# 匹配翻译函数调用：
#   - t('key')       — 主 i18n 入口（static/js/i18n.js 暴露 window.AIIA_I18N.t）
#   - _t('key')      — multi_task.js 的内联封装
#   - tl('key')      — 历史保留的 VSCode host 端快捷方式
#   - hostT('key')   — VSCode 扩展主进程内的 i18n helper
#   - __vuT('key')   — validation-utils.js 的本地 helper（避开 import 循环）
#   - __domSecT('key') — dom-security.js 的本地 helper（同上）
#   - __ncT('key')   — webview-notify-core.js 的本地 helper（P8 新增）
# 负向先行 ``(?<![.\w])`` 避免把 ``obj.t('foo')`` 这类属性访问误判成翻译。
_JS_T_CALL_RE = re.compile(
    # ``\(\s*`` 而不是 ``\(``：Prettier 把
    # ``_tl("settings.openConfigInIdeOpened", "Opened with {editor}.")``
    # 切成多行后第一参数前会带 ``\n      `` 缩进，旧正则 silent miss → 4 个
    # 真在用的 key 被误判 dead；锁在 R18.3。必须与
    # ``scripts/check_i18n_orphan_keys.py::JS_T_CALL_RE`` 同步。
    r"""(?<![.\w])(?:_?tl?|hostT|__vuT|__domSecT|__ncT)\(\s*['"]([a-zA-Z][a-zA-Z0-9_.]+)['"]\s*[,)]"""
)


class TestI18nKeyCoverage(unittest.TestCase):
    """排查 I18n Bootstrap Failure：所有使用的 i18n key 必须在所有 locale 文件中存在"""

    def _get_web_locale_keys(self) -> dict[str, set[str]]:
        """加载 Web UI 所有 locale 文件的键集合"""
        result: dict[str, set[str]] = {}
        for f in sorted(WEB_LOCALES_DIR.glob("*.json")):
            data = _load_json(f)
            result[f.stem] = _flatten_keys(data)
        return result

    def _get_vscode_locale_keys(self) -> dict[str, set[str]]:
        """加载 VS Code 插件所有 locale 文件的键集合"""
        result: dict[str, set[str]] = {}
        for f in sorted(VSCODE_LOCALES_DIR.glob("*.json")):
            data = _load_json(f)
            result[f.stem] = _flatten_keys(data)
        return result

    def _extract_data_i18n_keys(self) -> set[str]:
        """从 web_ui.html 提取所有 data-i18n 属性引用的 key"""
        template = TEMPLATES_DIR / "web_ui.html"
        if not template.exists():
            return set()
        html = template.read_text(encoding="utf-8")
        return set(_DATA_I18N_RE.findall(html))

    # 第三方/vendor 文件：变量名可能被压缩为 t，产生误匹配
    _VENDOR_JS = frozenset(
        {
            "tex-mml-chtml.js",
            "tex-mml-svg.js",
            "marked.js",
            "prism.js",
            "lottie.min.js",
        }
    )

    def _extract_js_t_keys(self, directory: Path, glob: str = "*.js") -> set[str]:
        """从 JS 文件提取所有 t('key') 调用中的 key（跳过 .min.js 和第三方文件）"""
        keys: set[str] = set()
        for f in sorted(directory.glob(glob)):
            if ".min." in f.name or f.name in self._VENDOR_JS:
                continue
            js = f.read_text(encoding="utf-8", errors="ignore")
            keys.update(_JS_T_CALL_RE.findall(js))
        return keys

    def test_web_data_i18n_keys_exist_in_all_locales(self):
        """web_ui.html 中 data-i18n 引用的 key 必须在所有 Web locale 文件中存在"""
        i18n_keys = self._extract_data_i18n_keys()
        if not i18n_keys:
            self.skipTest("未提取到 data-i18n key")

        locale_keys = self._get_web_locale_keys()
        self.assertTrue(locale_keys, "未找到 Web locale 文件")

        missing: dict[str, list[str]] = {}
        for lang, available in locale_keys.items():
            diff = sorted(i18n_keys - available)
            if diff:
                missing[lang] = diff

        if missing:
            lines = ["以下 data-i18n key 在 locale 文件中缺失："]
            for lang, keys in missing.items():
                for k in keys:
                    lines.append(f"  [{lang}] 缺失: {k}")
            self.fail("\n".join(lines))

    def test_web_js_t_keys_exist_in_all_locales(self):
        """Web JS 文件中 t() 调用的 key 必须在所有 Web locale 文件中存在"""
        t_keys = self._extract_js_t_keys(STATIC_JS_DIR)
        if not t_keys:
            self.skipTest("未提取到 Web JS t() key")

        locale_keys = self._get_web_locale_keys()
        self.assertTrue(locale_keys, "未找到 Web locale 文件")

        missing: dict[str, list[str]] = {}
        for lang, available in locale_keys.items():
            diff = sorted(t_keys - available)
            if diff:
                missing[lang] = diff

        if missing:
            lines = ["以下 Web JS t() key 在 locale 文件中缺失："]
            for lang, keys in missing.items():
                for k in keys:
                    lines.append(f"  [{lang}] 缺失: {k}")
            self.fail("\n".join(lines))

    def test_vscode_js_t_keys_exist_in_all_locales(self):
        """VS Code 插件 JS 中 t() 调用的 key 必须在所有插件 locale 文件中存在"""
        t_keys: set[str] = set()
        for name in ("webview-ui.js", "webview-settings-ui.js"):
            f = VSCODE_DIR / name
            if f.exists():
                js = f.read_text(encoding="utf-8", errors="ignore")
                t_keys.update(_JS_T_CALL_RE.findall(js))

        if not t_keys:
            self.skipTest("未提取到 VS Code JS t() key")

        locale_keys = self._get_vscode_locale_keys()
        self.assertTrue(locale_keys, "未找到 VS Code locale 文件")

        missing: dict[str, list[str]] = {}
        for lang, available in locale_keys.items():
            diff = sorted(t_keys - available)
            if diff:
                missing[lang] = diff

        if missing:
            lines = ["以下 VS Code JS t() key 在插件 locale 文件中缺失："]
            for lang, keys in missing.items():
                for k in keys:
                    lines.append(f"  [{lang}] 缺失: {k}")
            self.fail("\n".join(lines))


# ============================================================================
# 3. Locale Parity（排查多语言文件结构漂移）
# ============================================================================


class TestLocaleParity(unittest.TestCase):
    """排查 Locale 结构漂移：所有 locale 文件应有完全相同的键结构"""

    def _assert_keys_equal(
        self, keys_a: set[str], keys_b: set[str], label_a: str, label_b: str
    ):
        only_in_a = sorted(keys_a - keys_b)
        only_in_b = sorted(keys_b - keys_a)
        if only_in_a or only_in_b:
            lines = [f"Locale 键结构不一致 ({label_a} vs {label_b})："]
            for k in only_in_a:
                lines.append(f"  仅在 {label_a}: {k}")
            for k in only_in_b:
                lines.append(f"  仅在 {label_b}: {k}")
            self.fail("\n".join(lines))

    def test_web_locale_parity(self):
        """Web UI 的 en.json 和 zh-CN.json 应有完全相同的键结构"""
        en_path = WEB_LOCALES_DIR / "en.json"
        zh_path = WEB_LOCALES_DIR / "zh-CN.json"
        if not en_path.exists() or not zh_path.exists():
            self.skipTest("Web locale 文件不完整")

        en_keys = _flatten_keys(_load_json(en_path))
        zh_keys = _flatten_keys(_load_json(zh_path))
        self._assert_keys_equal(en_keys, zh_keys, "en.json", "zh-CN.json")

    def test_vscode_locale_parity(self):
        """VS Code 插件的 en.json 和 zh-CN.json 应有完全相同的键结构"""
        en_path = VSCODE_LOCALES_DIR / "en.json"
        zh_path = VSCODE_LOCALES_DIR / "zh-CN.json"
        if not en_path.exists() or not zh_path.exists():
            self.skipTest("VS Code locale 文件不完整")

        en_keys = _flatten_keys(_load_json(en_path))
        zh_keys = _flatten_keys(_load_json(zh_path))
        self._assert_keys_equal(en_keys, zh_keys, "en.json", "zh-CN.json")

    def _aiia_keys(self, path: Path) -> set[str]:
        """抽取单个 locale 文件里 ``aiia.*`` 命名空间下的展平 key 集合。"""
        data = _load_json(path)
        block = data.get("aiia")
        if not isinstance(block, dict):
            return set()
        return _flatten_keys(block, prefix="aiia")

    def test_aiia_namespace_cross_platform_parity_en(self):
        """IG-8：Web UI 和 VSCode 插件的 en.json 在 ``aiia.*`` 下必须完全一致"""
        web_en = WEB_LOCALES_DIR / "en.json"
        vscode_en = VSCODE_LOCALES_DIR / "en.json"
        if not web_en.exists() or not vscode_en.exists():
            self.skipTest("en.json 文件不完整")

        web_keys = self._aiia_keys(web_en)
        vscode_keys = self._aiia_keys(vscode_en)
        self._assert_keys_equal(
            web_keys,
            vscode_keys,
            "Web UI en.json aiia.*",
            "VSCode en.json aiia.*",
        )

    def test_aiia_namespace_cross_platform_parity_zh(self):
        """IG-8：Web UI 和 VSCode 插件的 zh-CN.json 在 ``aiia.*`` 下必须完全一致"""
        web_zh = WEB_LOCALES_DIR / "zh-CN.json"
        vscode_zh = VSCODE_LOCALES_DIR / "zh-CN.json"
        if not web_zh.exists() or not vscode_zh.exists():
            self.skipTest("zh-CN.json 文件不完整")

        web_keys = self._aiia_keys(web_zh)
        vscode_keys = self._aiia_keys(vscode_zh)
        self._assert_keys_equal(
            web_keys,
            vscode_keys,
            "Web UI zh-CN.json aiia.*",
            "VSCode zh-CN.json aiia.*",
        )


# ============================================================================
# 4. Configuration Propagation（排查 Integration Gap）
# ============================================================================


class TestConfigPropagation(unittest.TestCase):
    """排查 Integration Gap：API 返回应包含所有必要的配置字段"""

    @classmethod
    def setUpClass(cls):
        from web_ui import WebFeedbackUI

        cls.ui = WebFeedbackUI(
            prompt="配置传播测试",
            task_id="config-prop-test",
            port=8979,
        )
        cls.app = cls.ui.app
        cls.app.config["TESTING"] = True
        cls.client = cls.app.test_client()

    def test_api_config_returns_language_field(self):
        """/api/config 应返回 language 字段（TOML 配置传播到 API 响应）"""
        resp = self.client.get("/api/config")
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertIn(
            "language",
            data,
            "/api/config 响应缺少 language 字段（TOML web_ui.language 未传播到 API）",
        )

    def test_api_config_language_value_valid(self):
        """/api/config 的 language 字段应为 auto/en/zh-CN 等合法值"""
        resp = self.client.get("/api/config")
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        lang = data.get("language", "")
        valid = {"auto", "en", "zh-CN", "zh", "zh-cn"}
        self.assertIn(
            lang.lower() if lang != "zh-CN" else lang,
            valid,
            f"language 值 '{lang}' 不在预期范围内",
        )


# ============================================================================
# 5. Extension Version Sanity（排查 Environment-specific Defect）
# ============================================================================


class TestExtensionVersionSanity(unittest.TestCase):
    """排查 Environment-specific Defect：插件版本号不应为 fallback 值 0.0.0"""

    def test_package_json_version_not_fallback(self):
        """packages/vscode/package.json 的 version 不应为 0.0.0"""
        pkg_path = VSCODE_DIR / "package.json"
        if not pkg_path.exists():
            self.skipTest("package.json 不存在")

        pkg = _load_json(pkg_path)
        version = pkg.get("version", "")
        self.assertTrue(version, "package.json 缺少 version 字段")
        self.assertNotEqual(version, "0.0.0", "版本号不应为 fallback 值 0.0.0")
        self.assertRegex(
            version,
            r"^\d+\.\d+\.\d+",
            f"版本号 '{version}' 格式不符合 semver",
        )

    def test_webview_ts_uses_extension_uri_for_version(self):
        """webview.ts 应通过 extensionUri 读取版本号（而非 require('./package.json')）"""
        webview_ts = VSCODE_DIR / "webview.ts"
        if not webview_ts.exists():
            self.skipTest("webview.ts 不存在")

        source = webview_ts.read_text(encoding="utf-8")
        self.assertIn(
            "extensionVersion",
            source,
            "webview.ts 应使用 extensionVersion 变量",
        )
        self.assertNotIn(
            "require('./package.json')",
            source,
            "webview.ts 不应使用 require('./package.json')（打包后路径不可靠）",
        )


# ============================================================================
# 6. Static Resource Integrity（排查 Build-time Resource Resolution Failure）
# ============================================================================

_TEMPLATE_SRC_RE = re.compile(r'(?:src|href)="(/static/[^"?]+)')
_JINJA_TAG_RE = re.compile(r"\{\{[^}]+\}\}")


class TestStaticResourceIntegrity(unittest.TestCase):
    """排查 Build-time Resource Resolution Failure：模板引用的所有静态资源必须存在"""

    def test_web_template_referenced_resources_exist(self):
        """web_ui.html 中 <script src> 和 <link href> 引用的本地资源必须存在"""
        template = TEMPLATES_DIR / "web_ui.html"
        if not template.exists():
            self.skipTest("web_ui.html 不存在")

        html = template.read_text(encoding="utf-8")
        refs = _TEMPLATE_SRC_RE.findall(html)
        self.assertTrue(refs, "未提取到任何资源引用")

        missing: list[str] = []
        for ref in refs:
            clean = _JINJA_TAG_RE.sub("", ref)
            file_path = REPO_ROOT / clean.lstrip("/")
            if not file_path.exists():
                missing.append(ref)

        if missing:
            self.fail(
                "以下静态资源在仓库中不存在（可能未构建或路径错误）：\n  "
                + "\n  ".join(missing)
            )

    def test_lottie_animation_resources_exist_and_valid(self):
        """Lottie 动画 JSON 文件必须存在且为有效 JSON"""
        lottie_dir = REPO_ROOT / "static" / "lottie"
        if not lottie_dir.exists():
            self.skipTest("static/lottie/ 不存在")

        json_files = list(lottie_dir.glob("*.json"))
        self.assertTrue(json_files, "static/lottie/ 目录下无 JSON 文件")

        for f in json_files:
            text = f.read_text(encoding="utf-8")
            try:
                data = json.loads(text)
                self.assertIsInstance(data, dict, f"{f.name} 应为 JSON 对象")
            except json.JSONDecodeError as e:
                self.fail(f"{f.name} 不是有效的 JSON: {e}")

    def test_web_locale_files_valid_json(self):
        """Web locale 文件必须为有效 JSON 且非空"""
        for f in WEB_LOCALES_DIR.glob("*.json"):
            data = _load_json(f)
            self.assertIsInstance(data, dict, f"{f.name} 应为 JSON 对象")
            self.assertTrue(data, f"{f.name} 不应为空")

    def test_vscode_locale_files_valid_json(self):
        """VS Code 插件 locale 文件必须为有效 JSON 且非空"""
        for f in VSCODE_LOCALES_DIR.glob("*.json"):
            data = _load_json(f)
            self.assertIsInstance(data, dict, f"{f.name} 应为 JSON 对象")
            self.assertTrue(data, f"{f.name} 不应为空")

    def test_minified_source_file_sync(self):
        """每个 Web JS 源文件应有对应的 .min.js（防止修改源文件后忘记重新 minify）"""
        source_files = {
            f.stem
            for f in STATIC_JS_DIR.glob("*.js")
            if ".min." not in f.name
            and f.stem not in {"marked", "prism", "tex-mml-chtml", "tex-mml-svg"}
        }
        min_files = {f.stem.replace(".min", "") for f in STATIC_JS_DIR.glob("*.min.js")}

        missing_min = sorted(source_files - min_files)
        if missing_min:
            self.fail(
                "以下 JS 源文件缺少 .min.js（可能修改后未重新 minify）：\n  "
                + "\n  ".join(f"{name}.js → {name}.min.js" for name in missing_min)
            )


# ============================================================================
# 7. API Response Schema（排查 Integration Gap / Config Propagation）
# ============================================================================


class TestAPIResponseSchema(unittest.TestCase):
    """排查 Integration Gap：API 响应应包含所有客户端依赖的字段"""

    @classmethod
    def setUpClass(cls):
        from web_ui import WebFeedbackUI

        cls.ui = WebFeedbackUI(
            prompt="API Schema 测试",
            task_id="api-schema-test",
            port=8978,
        )
        cls.app = cls.ui.app
        cls.app.config["TESTING"] = True
        cls.client = cls.app.test_client()

    def test_api_config_schema_completeness(self):
        """/api/config 应包含前端渲染所需的所有字段"""
        resp = self.client.get("/api/config")
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        required_fields = {"prompt", "has_content", "language"}
        missing = required_fields - set(data.keys())
        self.assertFalse(missing, f"/api/config 缺少字段: {missing}")

    def test_api_tasks_schema_completeness(self):
        """/api/tasks 应包含任务列表和统计信息"""
        resp = self.client.get("/api/tasks")
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertIn("tasks", data, "/api/tasks 缺少 tasks 字段")
        self.assertIn("stats", data, "/api/tasks 缺少 stats 字段")

        stats = data["stats"]
        stats_required = {"total", "active", "pending", "completed", "max"}
        missing = stats_required - set(stats.keys())
        self.assertFalse(missing, f"/api/tasks stats 缺少字段: {missing}")

    def test_api_get_notification_config_schema(self):
        """/api/get-notification-config 应返回通知配置结构"""
        resp = self.client.get("/api/get-notification-config")
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertIn("config", data, "/api/get-notification-config 缺少 config 字段")

        config = data["config"]
        config_required = {"enabled", "web_enabled", "bark_enabled", "sound_enabled"}
        missing = config_required - set(config.keys())
        self.assertFalse(
            missing, f"/api/get-notification-config config 缺少字段: {missing}"
        )

    def test_api_get_feedback_prompts_schema(self):
        """/api/get-feedback-prompts 应返回反馈配置结构"""
        resp = self.client.get("/api/get-feedback-prompts")
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertIn("status", data)
        self.assertIn("config", data)
        self.assertIn("meta", data)

        config = data["config"]
        config_required = {"frontend_countdown", "resubmit_prompt", "prompt_suffix"}
        missing = config_required - set(config.keys())
        self.assertFalse(
            missing, f"/api/get-feedback-prompts config 缺少字段: {missing}"
        )


# ============================================================================
# 8. Config Round-trip（排查 Configuration Propagation Gap）
# ============================================================================


class TestFeedbackConfigRoundTrip(unittest.TestCase):
    """排查 Configuration Propagation Gap：保存的配置应能正确读回"""

    @classmethod
    def setUpClass(cls):
        from web_ui import WebFeedbackUI

        cls.ui = WebFeedbackUI(
            prompt="反馈配置回路测试",
            task_id="feedback-roundtrip",
            port=8977,
        )
        cls.app = cls.ui.app
        cls.app.config["TESTING"] = True
        cls.client = cls.app.test_client()

    def test_feedback_config_save_and_read_back(self):
        """POST /api/update-feedback-config → GET /api/get-feedback-prompts → 值一致"""
        save_data = {
            "frontend_countdown": 120,
            "resubmit_prompt": "测试-重调提示",
            "prompt_suffix": "测试-后缀",
        }
        resp = self.client.post(
            "/api/update-feedback-config",
            data=json.dumps(save_data),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)

        resp = self.client.get("/api/get-feedback-prompts")
        self.assertEqual(resp.status_code, 200)
        config = json.loads(resp.data).get("config", {})

        self.assertEqual(
            config.get("frontend_countdown"),
            120,
            "保存的 frontend_countdown 读回不一致",
        )
        self.assertEqual(
            config.get("resubmit_prompt"),
            "测试-重调提示",
            "保存的 resubmit_prompt 读回不一致",
        )
        self.assertEqual(
            config.get("prompt_suffix"),
            "测试-后缀",
            "保存的 prompt_suffix 读回不一致",
        )


class TestNotificationConfigRoundTrip(unittest.TestCase):
    """排查 Configuration Propagation Gap：通知配置保存后应能正确读回"""

    @classmethod
    def setUpClass(cls):
        from web_ui import WebFeedbackUI

        cls.ui = WebFeedbackUI(
            prompt="通知配置回路测试",
            task_id="notify-roundtrip",
            port=8976,
        )
        cls.app = cls.ui.app
        cls.app.config["TESTING"] = True
        cls.client = cls.app.test_client()

    def test_notification_config_save_and_read_back(self):
        """POST /api/update-notification-config → GET /api/get-notification-config → 值一致"""
        save_data = {"barkEnabled": True, "barkDeviceKey": "roundtrip-key-test"}
        resp = self.client.post(
            "/api/update-notification-config",
            data=json.dumps(save_data),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)

        resp = self.client.get("/api/get-notification-config")
        self.assertEqual(resp.status_code, 200)
        config = json.loads(resp.data).get("config", {})

        self.assertTrue(
            config.get("bark_enabled"),
            "保存的 bark_enabled 读回不一致",
        )
        self.assertEqual(
            config.get("bark_device_key"),
            "roundtrip-key-test",
            "保存的 bark_device_key 读回不一致",
        )


# ============================================================================
# 9. I18n Dead Key Detection（排查 Locale Drift）
# ============================================================================


class TestI18nDeadKeys(unittest.TestCase):
    """排查 Locale Drift：locale 文件中不应存在未被任何代码引用的 dead key

    注意 C10a（IG-8 §四 预留 key 清单）引入的**预留** key 需要显式豁免：
    这些 key 已经**同步注入** Web UI 与 VSCode 插件两端的 locale（受
    ``check_cross_platform_aiia_parity`` 守护跨端对齐），以便 C10b / C10c
    落地三态面板时直接引用——避免"阶段 1 先各加两份、阶段 3 再合并"的改动发散。

    C10b（BEST_PRACTICES_PLAN.tmp.md §T1 v3 §4）升级了反向闸门：原先
    ``_PRE_RESERVED_KEYS`` 是 ``frozenset[str]``，"任一端消费"就触发 fail；
    但 C10b 只先消费 Web 端（C10c 才消费 VSCode 端），旧闸门会在 C10b 阶段
    误报。升级后的数据结构是 ``dict[str, frozenset[str]]``，value 是该 key
    "需要哪些端都消费过才能从 allowlist 移除"——只有当实际消费端集合
    **完全覆盖**预期集合时，反向闸门才 fail。这样：

    * C10b 消费 web 端 → actual={web}，expected={web, vscode} → 不 fail（继续豁免）
    * C10c 消费 vscode 端 → actual={web, vscode} == expected → fail，强制删除

    删除后，普通 dead-key 检查会立即接管，保证新一轮 locale 改动不出 dead key。
    """

    # T1 · C10c 已完成（packages/vscode/webview.ts 注入了 13 个 data-i18n
    # 与 ${tl(...)} SSR 调用，_collect_all_used_vscode_keys 也将 aiia.state.*
    # 标记为 vscode 已消费），双端皆已消费 → 反向闸门移除豁免，普通 dead-key
    # 检查接管。如果未来又新增"短期单端豁免"，再按 T1 v3 §4 的 dict[str, frozenset[str]]
    # 形态填回；空字典 + skipTest 是常态。
    _PRE_RESERVED_KEYS: dict[str, frozenset[str]] = {}

    @classmethod
    def _pre_reserved_key_set(cls) -> set[str]:
        """为 dead-key 豁免提供扁平 key 集合（不区分端）。"""

        return set(cls._PRE_RESERVED_KEYS.keys())

    def _collect_all_used_web_keys(self) -> set[str]:
        """收集 Web 端（HTML + JS）使用的所有 i18n key"""
        keys: set[str] = set()
        template = TEMPLATES_DIR / "web_ui.html"
        if template.exists():
            html = template.read_text(encoding="utf-8")
            keys.update(_DATA_I18N_RE.findall(html))

        for f in sorted(STATIC_JS_DIR.glob("*.js")):
            if ".min." in f.name or f.name in TestI18nKeyCoverage._VENDOR_JS:
                continue
            js = f.read_text(encoding="utf-8", errors="ignore")
            keys.update(_JS_T_CALL_RE.findall(js))
        return keys

    def _collect_all_used_vscode_keys(self) -> set[str]:
        """收集 VS Code 插件使用的所有 i18n key（含 .js 和 .ts 文件）"""
        keys: set[str] = set()
        for name in (
            "webview-ui.js",
            "webview-settings-ui.js",
            "webview-notify-core.js",
            "webview.ts",
            "extension.ts",
        ):
            f = VSCODE_DIR / name
            if f.exists():
                text = f.read_text(encoding="utf-8", errors="ignore")
                keys.update(_JS_T_CALL_RE.findall(text))
        return keys

    def test_web_locale_no_dead_keys(self):
        """Web locale 文件中不应存在未被 HTML/JS 引用的 dead key"""
        used = self._collect_all_used_web_keys()
        if not used:
            self.skipTest("未提取到使用中的 key")

        en_path = WEB_LOCALES_DIR / "en.json"
        if not en_path.exists():
            self.skipTest("en.json 不存在")

        all_keys = _flatten_keys(_load_json(en_path))
        dead = sorted(all_keys - used - self._pre_reserved_key_set())

        if dead:
            self.fail(
                f"Web locale 中有 {len(dead)} 个 dead key（未被任何代码引用，可能是废弃翻译）：\n  "
                + "\n  ".join(dead[:20])
                + (f"\n  ...（共 {len(dead)} 个）" if len(dead) > 20 else "")
            )

    def test_vscode_locale_no_dead_keys(self):
        """VS Code 插件 locale 中不应存在未被 JS 引用的 dead key"""
        used = self._collect_all_used_vscode_keys()
        if not used:
            self.skipTest("未提取到使用中的 key")

        en_path = VSCODE_LOCALES_DIR / "en.json"
        if not en_path.exists():
            self.skipTest("en.json 不存在")

        all_keys = _flatten_keys(_load_json(en_path))
        dead = sorted(all_keys - used - self._pre_reserved_key_set())

        if dead:
            self.fail(
                f"VS Code locale 中有 {len(dead)} 个 dead key（未被任何代码引用）：\n  "
                + "\n  ".join(dead[:20])
                + (f"\n  ...（共 {len(dead)} 个）" if len(dead) > 20 else "")
            )

    def test_pre_reserved_keys_not_yet_consumed(self):
        """反向断言：``_PRE_RESERVED_KEYS`` 里 key 的实际消费端必须**真子集**于预期端。

        C10b（BEST_PRACTICES_PLAN.tmp.md §T1 v3 §4）升级：原先只要任一端消费
        就 fail，这会在 C10b（只消费 Web）阶段误报；升级后按端跟踪消费，只有
        当 key 的实际消费端完全覆盖预期端集合时，本测试才 fail，强制提交者
        从 ``_PRE_RESERVED_KEYS`` 移除该 key。

        判定逻辑：
            actual = {平台 | key 已被该平台代码引用（HTML data-i18n / JS t(...)）}
            expected = _PRE_RESERVED_KEYS[key]
            - 若 actual ⊇ expected（所有预期端都已消费）→ fail，必须从清单删除
            - 否则（仍有端未消费）→ 通过

        这样清单只会 "从多到少单向收敛"，不会变成"任一端消费就炸"的假警报，
        也不会退化为"permanent backdoor"。
        """
        if not self._PRE_RESERVED_KEYS:
            self.skipTest("_PRE_RESERVED_KEYS 已清空，C10b / C10c 已全部消费")

        web_used = self._collect_all_used_web_keys()
        vscode_used = self._collect_all_used_vscode_keys()

        fully_consumed: list[tuple[str, frozenset[str]]] = []
        for key, expected_platforms in self._PRE_RESERVED_KEYS.items():
            actual_platforms: set[str] = set()
            if key in web_used:
                actual_platforms.add("web")
            if key in vscode_used:
                actual_platforms.add("vscode")
            if actual_platforms >= expected_platforms:
                fully_consumed.append((key, expected_platforms))

        if fully_consumed:
            self.fail(
                f"以下 {len(fully_consumed)} 个 key 已被所有预期平台消费，"
                f"但仍留在 TestI18nDeadKeys._PRE_RESERVED_KEYS 清单里——"
                f"请把它们从 _PRE_RESERVED_KEYS 中删除：\n  "
                + "\n  ".join(
                    f"{key}  （预期平台 {sorted(platforms)} 全部已消费）"
                    for key, platforms in fully_consumed
                )
            )


# ============================================================================
# 10. Plugin Resource Bundle Completeness（排查 VSIX 打包产物缺失）
# ============================================================================


class TestPluginResourceBundle(unittest.TestCase):
    """排查 VSIX 打包产物缺失：package.json files[] 中声明的文件必须存在"""

    # 构建产物目录：仅在 npm run compile 后存在，源码仓库中不检查
    _BUILD_ARTIFACT_PREFIXES = ("dist/",)

    def test_package_json_files_all_exist(self):
        """packages/vscode/package.json 的 files[] 中非构建产物条目应存在"""
        pkg_path = VSCODE_DIR / "package.json"
        if not pkg_path.exists():
            self.skipTest("package.json 不存在")

        pkg = _load_json(pkg_path)
        files_list = pkg.get("files", [])
        if not files_list:
            self.skipTest("package.json 无 files 字段")

        missing: list[str] = []
        for entry in files_list:
            if any(entry.startswith(p) for p in self._BUILD_ARTIFACT_PREFIXES):
                continue
            if "**" in entry or "*" in entry:
                import glob as glob_mod

                matches = glob_mod.glob(str(VSCODE_DIR / entry))
                if not matches:
                    missing.append(f"{entry} (glob 无匹配)")
            else:
                if not (VSCODE_DIR / entry).exists():
                    missing.append(entry)

        if missing:
            self.fail(
                "以下 package.json files[] 条目在仓库中不存在：\n  "
                + "\n  ".join(missing)
            )

    def test_required_locale_files_listed_in_package_json(self):
        """locale 文件应在 package.json files[] 中被包含"""
        pkg_path = VSCODE_DIR / "package.json"
        if not pkg_path.exists():
            self.skipTest("package.json 不存在")

        pkg = _load_json(pkg_path)
        files_list = pkg.get("files", [])
        files_str = " ".join(files_list)

        self.assertIn(
            "locales",
            files_str,
            "package.json files[] 未包含 locales 目录（打包后 i18n 将失效）",
        )


# ============================================================================
# 11. I18n Interpolation Placeholder Parity
#     排查 Locale Drift / Silent Interpolation Failure
# ============================================================================

_PLACEHOLDER_RE = re.compile(r"\{\{(\w+)\}\}")


class TestI18nPlaceholderParity(unittest.TestCase):
    """不同语言的同一 key 应包含完全相同的 {{param}} 占位符集合"""

    @staticmethod
    def _extract_placeholders(value: str) -> set[str]:
        return set(_PLACEHOLDER_RE.findall(value))

    @staticmethod
    def _flat_values(d: dict, prefix: str = "") -> dict[str, str]:
        result: dict[str, str] = {}
        for k, v in d.items():
            full = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict):
                result.update(TestI18nPlaceholderParity._flat_values(v, full))
            elif isinstance(v, str):
                result[full] = v
        return result

    def _check_parity(self, dir_path: Path, label: str):
        locale_files = sorted(dir_path.glob("*.json"))
        if len(locale_files) < 2:
            self.skipTest(f"{label} locale 文件不足 2 个")

        base_file = locale_files[0]
        base_data = self._flat_values(_load_json(base_file))

        violations: list[str] = []
        for other_file in locale_files[1:]:
            other_data = self._flat_values(_load_json(other_file))
            for key in base_data:
                if key not in other_data:
                    continue
                base_ph = self._extract_placeholders(base_data[key])
                other_ph = self._extract_placeholders(other_data[key])
                if base_ph != other_ph:
                    violations.append(
                        f"  {key}: {base_file.name} has {base_ph}, "
                        f"{other_file.name} has {other_ph}"
                    )

        if violations:
            self.fail(
                f"{label} 中以下 key 的 {{{{param}}}} 占位符不一致（运行时插值将静默失败）：\n"
                + "\n".join(violations)
            )

    def test_web_locale_placeholder_parity(self):
        """Web locale 文件之间的 {{param}} 占位符应完全一致"""
        self._check_parity(WEB_LOCALES_DIR, "Web")

    def test_vscode_locale_placeholder_parity(self):
        """VS Code 插件 locale 文件之间的 {{param}} 占位符应完全一致"""
        self._check_parity(VSCODE_LOCALES_DIR, "VS Code")


# ============================================================================
# 12. CSS Variable Reference Integrity
#     排查 Design Token Drift / Visual Regression
# ============================================================================

_CSS_VAR_USAGE_RE = re.compile(r"var\(--([a-zA-Z0-9_-]+)")
_CSS_VAR_DEFINITION_RE = re.compile(r"--([a-zA-Z0-9_-]+)\s*:")

CSS_DIR = REPO_ROOT / "static" / "css"


class TestCSSVariableReferenceIntegrity(unittest.TestCase):
    """所有 var(--xxx) 引用的 CSS 变量必须在 CSS 中有定义"""

    def _collect_defined_vars(self) -> set[str]:
        defined: set[str] = set()
        for f in CSS_DIR.glob("*.css"):
            if ".min." in f.name:
                continue
            text = f.read_text(encoding="utf-8")
            defined.update(_CSS_VAR_DEFINITION_RE.findall(text))
        return defined

    def _collect_used_vars_in_file(self, path: Path) -> set[str]:
        if not path.exists():
            return set()
        text = path.read_text(encoding="utf-8")
        return set(_CSS_VAR_USAGE_RE.findall(text))

    def test_html_inline_style_var_references_defined(self):
        """web_ui.html 内联 style 中使用的 var(--xxx) 必须在 CSS 中有定义"""
        template = TEMPLATES_DIR / "web_ui.html"
        if not template.exists():
            self.skipTest("web_ui.html 不存在")

        defined = self._collect_defined_vars()
        used = self._collect_used_vars_in_file(template)
        undefined = sorted(used - defined)

        if undefined:
            self.fail(
                "以下 CSS 变量在 HTML 中被引用但未在 CSS 中定义（浏览器将静默降级为空值）：\n  "
                + "\n  ".join(f"var(--{v})" for v in undefined)
            )

    def test_css_self_referencing_vars_defined(self):
        """CSS 文件中 var(--xxx) 引用的变量必须在某处有定义"""
        defined = self._collect_defined_vars()
        all_used: set[str] = set()
        for f in CSS_DIR.glob("*.css"):
            if ".min." in f.name:
                continue
            all_used.update(self._collect_used_vars_in_file(f))

        undefined = sorted(all_used - defined)
        if undefined:
            self.fail(
                "以下 CSS 变量被引用但未定义（可能是拼写错误或遗漏）：\n  "
                + "\n  ".join(f"var(--{v})" for v in undefined)
            )


# ============================================================================
# 13. Client-Server Route Alignment
#     排查 Integration Gap / 404 Silent Failure
# ============================================================================

_JS_FETCH_ROUTE_RE = re.compile(r"""fetch\s*\(\s*['"]([^'"]+/api/[^'"?]+)""")
_JS_FETCH_RELATIVE_RE = re.compile(
    r"""fetch\s*\(\s*(?:SERVER_URL\s*\+\s*)?['"](/api/[^'"?]+)"""
)


class TestClientServerRouteAlignment(unittest.TestCase):
    """前端 JS 调用的 /api/... 路由必须在 Flask 后端有注册"""

    @classmethod
    def setUpClass(cls):
        from web_ui import WebFeedbackUI

        cls.ui = WebFeedbackUI(
            prompt="路由对齐测试",
            task_id="route-align-test",
            port=8975,
        )
        cls.app = cls.ui.app
        cls.app.config["TESTING"] = True
        cls.registered_rules: set[str] = set()
        for rule in cls.app.url_map.iter_rules():
            cls.registered_rules.add(rule.rule)

    def _extract_js_routes(self, directory: Path, glob: str = "*.js") -> set[str]:
        routes: set[str] = set()
        for f in sorted(directory.glob(glob)):
            if ".min." in f.name:
                continue
            js = f.read_text(encoding="utf-8", errors="ignore")
            routes.update(_JS_FETCH_RELATIVE_RE.findall(js))
        return routes

    @staticmethod
    def _normalize_route(route: str) -> str:
        """将 /api/tasks/xxx 参数化为 /api/tasks/<param> 以匹配 Flask 规则"""
        route = route.rstrip("/")
        parts = route.split("/")
        normalized_parts: list[str] = []
        for i, part in enumerate(parts):
            if i > 2 and not part.startswith("<"):
                normalized_parts.append("<param>")
            else:
                normalized_parts.append(part)
        return "/".join(normalized_parts)

    def _route_matches_any_rule(self, route: str) -> bool:
        route = route.rstrip("/")
        if route in self.registered_rules:
            return True
        for rule in self.registered_rules:
            rule_static = rule.split("<")[0].rstrip("/")
            if route.startswith(rule_static) and "<" in rule:
                return True
        return False

    def test_web_js_fetch_routes_exist_in_flask(self):
        """Web JS 中 fetch('/api/...') 的路由必须在 Flask 中有注册"""
        js_routes = self._extract_js_routes(STATIC_JS_DIR)
        if not js_routes:
            self.skipTest("未提取到 Web JS fetch 路由")

        missing: list[str] = []
        for route in sorted(js_routes):
            if not self._route_matches_any_rule(route):
                missing.append(route)

        if missing:
            self.fail(
                "以下 API 路由在 JS 中被调用但 Flask 中未注册（运行时将 404）：\n  "
                + "\n  ".join(missing)
            )

    def test_vscode_js_fetch_routes_exist_in_flask(self):
        """VS Code 插件 JS 中 fetch('/api/...') 的路由必须在 Flask 中有注册"""
        routes: set[str] = set()
        for name in ("webview-ui.js", "webview-settings-ui.js"):
            f = VSCODE_DIR / name
            if f.exists():
                js = f.read_text(encoding="utf-8", errors="ignore")
                routes.update(_JS_FETCH_RELATIVE_RE.findall(js))

        if not routes:
            self.skipTest("未提取到 VS Code JS fetch 路由")

        missing: list[str] = []
        for route in sorted(routes):
            if not self._route_matches_any_rule(route):
                missing.append(route)

        if missing:
            self.fail(
                "以下 API 路由在插件 JS 中被调用但 Flask 中未注册：\n  "
                + "\n  ".join(missing)
            )


# ============================================================================
# 14. WebView Message Type Handler Matching
#     排查 Integration Gap / Silent Message Drop
# ============================================================================

_POSTMESSAGE_TYPE_RE = re.compile(
    r"""postMessage\s*\(\s*\{[^}]*type\s*:\s*['"](\w+)['"]"""
)
_CASE_HANDLER_RE = re.compile(r"""case\s+['"](\w+)['"]""")


class TestWebviewMessageTypeMatching(unittest.TestCase):
    """webview JS 发送的 postMessage type 必须在 webview.ts 中有对应 case 处理"""

    def test_all_postmessage_types_have_handlers(self):
        """所有 vscode.postMessage({ type: 'xxx' }) 的 type 必须在 webview.ts switch/case 中有处理"""
        sent_types: set[str] = set()
        for name in ("webview-ui.js", "webview-settings-ui.js"):
            f = VSCODE_DIR / name
            if f.exists():
                js = f.read_text(encoding="utf-8", errors="ignore")
                sent_types.update(_POSTMESSAGE_TYPE_RE.findall(js))

        if not sent_types:
            self.skipTest("未提取到 postMessage type")

        webview_ts = VSCODE_DIR / "webview.ts"
        if not webview_ts.exists():
            self.skipTest("webview.ts 不存在")

        ts_source = webview_ts.read_text(encoding="utf-8")
        handled_types = set(_CASE_HANDLER_RE.findall(ts_source))

        unhandled = sorted(sent_types - handled_types)
        if unhandled:
            self.fail(
                "以下 postMessage type 在 JS 中发送但 webview.ts 中无 case 处理"
                "（消息将被静默丢弃）：\n  " + "\n  ".join(unhandled)
            )


# ============================================================================
# 15. Jinja2 Template Variable Injection
#     排查 Environment-specific Defect / Template Render Failure
# ============================================================================

_JINJA2_VARIABLE_RE = re.compile(r"\{\{\s*(\w+)[\s|]")


class TestJinja2TemplateVariableInjection(unittest.TestCase):
    """HTML 模板中使用的 Jinja2 变量必须在 Python 端 render_template 调用中提供"""

    def test_all_template_variables_provided(self):
        """web_ui.html 中的 {{ variable }} 必须在 _get_template_context() 中有提供"""
        template = TEMPLATES_DIR / "web_ui.html"
        if not template.exists():
            self.skipTest("web_ui.html 不存在")

        html = template.read_text(encoding="utf-8")
        used_vars = set(_JINJA2_VARIABLE_RE.findall(html))
        used_vars.discard("config")
        used_vars.discard("request")
        used_vars.discard("session")
        used_vars.discard("g")
        used_vars.discard("url_for")

        from web_ui import WebFeedbackUI

        ui = WebFeedbackUI(
            prompt="模板变量测试",
            task_id="tpl-var-test",
            port=8974,
        )
        context_keys = set(ui._get_template_context().keys())

        missing = sorted(used_vars - context_keys)
        if missing:
            self.fail(
                "以下 Jinja2 变量在模板中使用但 _get_template_context() 未提供"
                "（渲染时将为空或报错）：\n  " + "\n  ".join(missing)
            )


# ============================================================================
# 16. Theme Token Coverage
#     排查 Visual Regression / Design Token Drift
# ============================================================================


class TestThemeTokenCoverage(unittest.TestCase):
    """浅色主题 [data-theme='light'] 应覆盖 :root 中定义的所有关键 CSS 变量"""

    _CORE_TOKEN_PREFIXES = (
        "bg-",
        "text-",
        "border-",
        "shadow-",
    )

    def test_light_theme_covers_core_root_tokens(self):
        """[data-theme='light'] 应覆盖 :root 中所有 bg-/text-/border-/shadow- 开头的 CSS 变量"""
        css_file = CSS_DIR / "main.css"
        if not css_file.exists():
            self.skipTest("main.css 不存在")

        text = css_file.read_text(encoding="utf-8")

        root_match = re.search(r":root\s*\{([^}]+)\}", text)
        if not root_match:
            self.skipTest("未找到 :root 块")
        assert root_match is not None

        root_vars = set(_CSS_VAR_DEFINITION_RE.findall(root_match.group(1)))

        light_blocks = re.findall(
            r"""\[data-theme=['"]light['"]\]\s*\{([^}]+)\}""", text
        )
        light_vars: set[str] = set()
        for block in light_blocks:
            light_vars.update(_CSS_VAR_DEFINITION_RE.findall(block))

        core_root_vars = {
            v
            for v in root_vars
            if any(v.startswith(p) for p in self._CORE_TOKEN_PREFIXES)
        }

        missing = sorted(core_root_vars - light_vars)
        if missing:
            self.fail(
                f":root 中 {len(missing)} 个核心 CSS 变量在 [data-theme='light'] 中未覆盖"
                f"（主题切换时将继承深色值，导致 Visual Regression）：\n  "
                + "\n  ".join(f"--{v}" for v in missing)
            )


# ============================================================================
# 17. Locale Value Quality（排查细粒度显示问题）
# ============================================================================


class TestLocaleValueQuality(unittest.TestCase):
    """排查 locale 值层面的显示问题：空值 / 尾部空白 / 损坏的占位符"""

    @staticmethod
    def _flat_values(d: dict, prefix: str = "") -> dict[str, str]:
        result: dict[str, str] = {}
        for k, v in d.items():
            full = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict):
                result.update(TestLocaleValueQuality._flat_values(v, full))
            elif isinstance(v, str):
                result[full] = v
        return result

    def _check_quality(self, dir_path: Path, label: str):
        issues: list[str] = []
        for f in sorted(dir_path.glob("*.json")):
            data = _load_json(f)
            flat = self._flat_values(data)
            for key, val in flat.items():
                if not val.strip():
                    issues.append(f"[{f.name}] {key}: 空值（UI 将显示空白）")
                if val != val.strip():
                    issues.append(f"[{f.name}] {key}: 尾部/首部空白（'{val[:20]}…'）")
                # 旧实现只数 ``{{`` / ``}}``（Mustache），引入 ICU subset 之后
                # 会漏报 ``{count, plural, one {...}}`` 这类单大括号模板的不平
                # 衡问题。改为统计单个 ``{`` 与 ``}`` 是否成对 —— 这同时覆盖
                # Mustache（每个占位符各自含一对）和 ICU（嵌套也必须配对）。
                single_opens = val.count("{")
                single_closes = val.count("}")
                if single_opens != single_closes:
                    issues.append(
                        f"[{f.name}] {key}: 占位符括号不匹配"
                        f"（{{ 出现 {single_opens} 次，"
                        f"}} 出现 {single_closes} 次）"
                    )

        if issues:
            self.fail(f"{label} locale 值质量问题：\n  " + "\n  ".join(issues))

    def test_web_locale_value_quality(self):
        """Web locale 值不应有空值、尾部空白或损坏的占位符"""
        self._check_quality(WEB_LOCALES_DIR, "Web")

    def test_vscode_locale_value_quality(self):
        """VS Code locale 值不应有空值、尾部空白或损坏的占位符"""
        self._check_quality(VSCODE_LOCALES_DIR, "VS Code")


# ============================================================================
# 18. data-i18n Attribute Variant Coverage
#     排查 I18n Bootstrap Failure —— 分别验证各 data-i18n-* 变体
# ============================================================================

_DATA_I18N_VARIANTS = {
    "data-i18n": re.compile(r'data-i18n="([^"]+)"'),
    "data-i18n-title": re.compile(r'data-i18n-title="([^"]+)"'),
    "data-i18n-placeholder": re.compile(r'data-i18n-placeholder="([^"]+)"'),
    "data-i18n-html": re.compile(r'data-i18n-html="([^"]+)"'),
}


class TestDataI18nVariantCoverage(unittest.TestCase):
    """分别验证 data-i18n / data-i18n-title / data-i18n-placeholder / data-i18n-html
    引用的 key 都存在于所有 locale 文件中"""

    def test_all_data_i18n_variants_covered(self):
        """HTML 中每种 data-i18n-* 变体引用的 key 必须在所有 Web locale 中存在"""
        template = TEMPLATES_DIR / "web_ui.html"
        if not template.exists():
            self.skipTest("web_ui.html 不存在")

        html = template.read_text(encoding="utf-8")

        locale_keys: dict[str, set[str]] = {}
        for f in sorted(WEB_LOCALES_DIR.glob("*.json")):
            locale_keys[f.stem] = _flatten_keys(_load_json(f))

        if not locale_keys:
            self.skipTest("未找到 Web locale 文件")

        missing: list[str] = []
        for attr_name, regex in _DATA_I18N_VARIANTS.items():
            keys = set(regex.findall(html))
            for lang, available in locale_keys.items():
                for k in sorted(keys - available):
                    missing.append(f'  [{lang}] {attr_name}="{k}" 缺失')

        if missing:
            self.fail(
                "以下 data-i18n-* 属性引用的 key 在 locale 中缺失：\n"
                + "\n".join(missing)
            )


# ============================================================================
# 19. TOML Config Structural Integrity
#     排查 Configuration Schema Mismatch
# ============================================================================


class TestTOMLConfigIntegrity(unittest.TestCase):
    """验证 config.toml 结构完整性：必要 section 和 key 必须存在"""

    _REQUIRED_SECTIONS = ("notification", "web_ui", "feedback")

    def test_config_toml_parseable(self):
        """config.toml 应为有效的 TOML 文件"""
        config_path = REPO_ROOT / "config.toml"
        if not config_path.exists():
            self.skipTest("config.toml 不存在")

        try:
            import tomllib
        except ModuleNotFoundError:
            import tomli as tomllib  # type: ignore[no-redef]

        text = config_path.read_text(encoding="utf-8")
        try:
            data = tomllib.loads(text)
            self.assertIsInstance(data, dict)
        except Exception as e:
            self.fail(f"config.toml 解析失败: {e}")

    def test_config_toml_required_sections_exist(self):
        """config.toml 应包含所有必要的 section"""
        config_path = REPO_ROOT / "config.toml"
        if not config_path.exists():
            self.skipTest("config.toml 不存在")

        try:
            import tomllib
        except ModuleNotFoundError:
            import tomli as tomllib  # type: ignore[no-redef]

        data = tomllib.loads(config_path.read_text(encoding="utf-8"))
        missing = [s for s in self._REQUIRED_SECTIONS if s not in data]
        if missing:
            self.fail(f"config.toml 缺少必要的 section: {missing}")

    def test_config_web_ui_language_key_exists(self):
        """config.toml [web_ui] 应包含 language 字段"""
        config_path = REPO_ROOT / "config.toml"
        if not config_path.exists():
            self.skipTest("config.toml 不存在")

        try:
            import tomllib
        except ModuleNotFoundError:
            import tomli as tomllib  # type: ignore[no-redef]

        data = tomllib.loads(config_path.read_text(encoding="utf-8"))
        web_ui = data.get("web_ui", {})
        self.assertIn(
            "language",
            web_ui,
            "config.toml [web_ui] 缺少 language 字段（语言切换将失效）",
        )


# ============================================================================
# 20. Locale Nesting Depth Consistency
#     排查 Key Resolution Failure（嵌套结构不一致导致 t() 返回 undefined）
# ============================================================================


class TestLocaleNestingConsistency(unittest.TestCase):
    """同一 key 在不同 locale 中的类型应一致（不能一个是字符串另一个是对象）"""

    @staticmethod
    def _type_map(d: dict, prefix: str = "") -> dict[str, str]:
        result: dict[str, str] = {}
        for k, v in d.items():
            full = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict):
                result[full] = "object"
                result.update(TestLocaleNestingConsistency._type_map(v, full))
            else:
                result[full] = "leaf"
        return result

    def _check_nesting(self, dir_path: Path, label: str):
        files = sorted(dir_path.glob("*.json"))
        if len(files) < 2:
            self.skipTest(f"{label} locale 文件不足 2 个")

        base_types = self._type_map(_load_json(files[0]))
        violations: list[str] = []

        for other in files[1:]:
            other_types = self._type_map(_load_json(other))
            for key in set(base_types) & set(other_types):
                if base_types[key] != other_types[key]:
                    violations.append(
                        f"  {key}: {files[0].name} 是 {base_types[key]}，"
                        f"{other.name} 是 {other_types[key]}"
                    )

        if violations:
            self.fail(
                f"{label} locale 嵌套结构不一致（会导致 t() 返回 [object Object] 或 undefined）：\n"
                + "\n".join(violations)
            )

    def test_web_locale_nesting_consistency(self):
        """Web locale 文件之间的嵌套结构应一致"""
        self._check_nesting(WEB_LOCALES_DIR, "Web")

    def test_vscode_locale_nesting_consistency(self):
        """VS Code locale 文件之间的嵌套结构应一致"""
        self._check_nesting(VSCODE_LOCALES_DIR, "VS Code")
