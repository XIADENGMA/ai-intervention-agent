"""R122 — 图片上传 MIME 白名单三端一致性 + SVG 拒收回归护栏。

## 背景

历史上前端有三处独立的 `SUPPORTED_IMAGE_TYPES` MIME 白名单：

1. ``src/ai_intervention_agent/static/js/image-upload.js`` — Web UI 主上传逻辑
2. ``src/ai_intervention_agent/static/js/validation-utils.js`` — 通用 ValidationUtils 工具类
3. ``packages/vscode/webview-ui.js`` — VS Code 扩展 webview UI

后端 ``src/ai_intervention_agent/file_validator.py::IMAGE_MAGIC_NUMBERS``
是终极仲裁——通过文件魔数识别真实类型，**只支持 PNG / JPEG / GIF /
WebP / BMP 五种**（无 SVG）。

R122 之前的状态：

- ``image-upload.js`` / ``webview-ui.js`` 都把 ``image/svg+xml`` 列入白名单
- ``validation-utils.js`` 的白名单不含 ``image/svg+xml`` **也不含** ``image/jpg``
- 后端 ``file_validator.py`` 不识别 SVG（无 magic-byte）

后果：

- **安全风险**：SVG 是 XML 文本格式，可携带 ``<script>``/``onload`` 等
  实现 XSS（[OWASP SVG Security](https://owasp.org/www-community/attacks/Server_Side_Request_Forgery_via_SVG_files)）。
  前端 MIME 白名单"放行" SVG → 用户能在拖拽/选择阶段确认上传 → 但
  后端会因为 magic-byte 不命中而拒绝 → UX 断裂兼安全错觉（用户以为
  SVG 被支持了）。
- **一致性 bug**：``validation-utils.js`` 与 ``image-upload.js`` /
  ``webview-ui.js`` 不同步——同样是 Web UI 的两个验证入口，只要前者
  被先调用就可能放行/拦截行为不一致（``image-upload.js:75`` 优先委
  托给 ``ValidationUtils``，再回退本地白名单）。

R122 修复策略：**前端三处统一拒收 SVG**，与后端默认拒绝行为对齐。
不在后端添加 SVG magic-byte 是因为：

- SVG 安全展示需要 sanitize（DOMPurify / 服务端 SVG sanitizer），
  这是单独的、复杂得多的话题；
- 当前用户场景是"AI 输出 → 用户上传截图给 AI 看"，PNG/JPG/WebP 已
  完全覆盖；
- 默认拒绝最安全。如未来真要支持 SVG，应单独走 R-XXX 计划，先做
  sanitize 层。

R122 同时把 ``validation-utils.js`` 加上 ``image/jpg``——少数浏览器
/上传组件（特别是 Edge legacy 与某些 Windows 老版本）会上报
``image/jpg`` 而非标准 ``image/jpeg``，三端 MIME 白名单都收两个，
后端 magic-byte 检测层仍按 ``image/jpeg`` 一种实际格式识别。

## 本测试锁定的不变量

1. **三端 MIME 白名单完全一致**（同样的 6 种 MIME，同序列）
2. **三端都不含 ``image/svg+xml``**
3. **三端都同时含 ``image/jpeg`` 与 ``image/jpg``**
4. **后端 ``file_validator.IMAGE_MAGIC_NUMBERS`` 不含 SVG mime_type**
   （反向锁——未来如果有人加 SVG magic-byte，就要补 sanitize 层）

任何一条违反都会让 CI 立即失败，把"前端 X 处放行 SVG / 后端 Y 处不
识别 SVG"这种类型的悄悄回归挡在合并前。
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# ----------------------------------------------------------------------
# R122 期望的统一白名单（按 image-upload.js 的字面顺序，三端必须一致）
# ----------------------------------------------------------------------
EXPECTED_MIME_WHITELIST: tuple[str, ...] = (
    "image/jpeg",
    "image/jpg",
    "image/png",
    "image/gif",
    "image/webp",
    "image/bmp",
)

# ----------------------------------------------------------------------
# 三处前端白名单源文件
# ----------------------------------------------------------------------
IMAGE_UPLOAD_JS = (
    REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "js" / "image-upload.js"
)
VALIDATION_UTILS_JS = (
    REPO_ROOT
    / "src"
    / "ai_intervention_agent"
    / "static"
    / "js"
    / "validation-utils.js"
)
WEBVIEW_UI_JS = REPO_ROOT / "packages" / "vscode" / "webview-ui.js"

# 后端文件
FILE_VALIDATOR_PY = REPO_ROOT / "src" / "ai_intervention_agent" / "file_validator.py"


def _extract_mime_array(source: str, marker: str) -> list[str]:
    """从 JS 源里抓 ``marker`` 之后第一个 ``[...]`` 数组里的 MIME 字符串。

    具体来说，先定位 ``marker``（比如
    ``SUPPORTED_IMAGE_TYPES = [`` 或 ``SUPPORTED_IMAGE_TYPES = [``）的位置，
    再用最朴素的 ``[`` ... 第一个匹配 ``]`` 之间的内容做正则抽取。

    这里**故意**不调 JS engine 来 eval（保留 unit test 纯静态、跨语言、
    秒级跑完的特性）。如果未来有人把 MIME 字面量替换成 ``"image/" +
    "jpeg"`` 这种拼接，会扫不到，但那种代码会先被 ESLint / minify 阶段
    标记，本测试退化为不约束—不是一个值得保护的场景。
    """
    idx = source.find(marker)
    if idx < 0:
        raise AssertionError(f"在源里找不到锚点字符串 {marker!r}")
    bracket_start = source.find("[", idx)
    if bracket_start < 0:
        raise AssertionError(f"锚点 {marker!r} 之后找不到 '[' 起始")
    bracket_end = source.find("]", bracket_start)
    if bracket_end < 0:
        raise AssertionError(f"锚点 {marker!r} 之后的 '[' 没有匹配的 ']'")
    body = source[bracket_start + 1 : bracket_end]

    return re.findall(r"['\"]([^'\"]+)['\"]", body)


class TestMimeWhitelistThreeSiteParity(unittest.TestCase):
    """前端三处 ``SUPPORTED_IMAGE_TYPES`` 必须严格相等。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.image_upload_src = IMAGE_UPLOAD_JS.read_text(encoding="utf-8")
        cls.validation_utils_src = VALIDATION_UTILS_JS.read_text(encoding="utf-8")
        cls.webview_ui_src = WEBVIEW_UI_JS.read_text(encoding="utf-8")

    def test_image_upload_js_matches_expected(self) -> None:
        actual = _extract_mime_array(
            self.image_upload_src, "const SUPPORTED_IMAGE_TYPES"
        )
        self.assertEqual(
            tuple(actual),
            EXPECTED_MIME_WHITELIST,
            "src/ai_intervention_agent/static/js/image-upload.js 的 "
            "SUPPORTED_IMAGE_TYPES 不再与 R122 期望白名单一致。"
            "如需调整，请同时改三处前端白名单 + 评估后端 file_validator.py "
            f"是否也需要支持新 MIME。期望: {EXPECTED_MIME_WHITELIST}, 实际: {actual}",
        )

    def test_validation_utils_js_matches_expected(self) -> None:
        actual = _extract_mime_array(
            self.validation_utils_src, "static SUPPORTED_IMAGE_TYPES"
        )
        self.assertEqual(
            tuple(actual),
            EXPECTED_MIME_WHITELIST,
            "src/ai_intervention_agent/static/js/validation-utils.js 的 "
            "SUPPORTED_IMAGE_TYPES 不再与 R122 期望白名单一致。注意 "
            "ValidationUtils 是 Web UI 的通用工具类，image-upload.js 优先委"
            "托它做校验，两者必须严格相等。"
            f"期望: {EXPECTED_MIME_WHITELIST}, 实际: {actual}",
        )

    def test_webview_ui_js_matches_expected(self) -> None:
        actual = _extract_mime_array(self.webview_ui_src, "const SUPPORTED_IMAGE_TYPES")
        self.assertEqual(
            tuple(actual),
            EXPECTED_MIME_WHITELIST,
            "packages/vscode/webview-ui.js 的 SUPPORTED_IMAGE_TYPES 不再与 "
            "R122 期望白名单一致。VS Code 扩展与 Web UI 后端共享 /api/submit "
            "上传路径，三端 MIME 白名单必须一致以避免 UX 断裂（用户在 VS "
            "Code 里能选 SVG 但服务端拒绝）。"
            f"期望: {EXPECTED_MIME_WHITELIST}, 实际: {actual}",
        )


class TestSvgRejectedByFrontendThreeSites(unittest.TestCase):
    """三端前端白名单都必须**不**含 ``image/svg+xml``（XSS 风险）。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.image_upload_src = IMAGE_UPLOAD_JS.read_text(encoding="utf-8")
        cls.validation_utils_src = VALIDATION_UTILS_JS.read_text(encoding="utf-8")
        cls.webview_ui_src = WEBVIEW_UI_JS.read_text(encoding="utf-8")

    def test_image_upload_js_has_no_svg(self) -> None:
        types = _extract_mime_array(
            self.image_upload_src, "const SUPPORTED_IMAGE_TYPES"
        )
        self.assertNotIn(
            "image/svg+xml",
            types,
            "image-upload.js 不应允许 SVG 上传——SVG 是 XML 文本，可携带 "
            "<script>/onload 实现 XSS；后端 file_validator.py 也不识别 "
            "SVG，前端放行只会让用户先选 SVG 再被后端 reject。如需支持 "
            "SVG，请先实现 sanitize 层（DOMPurify 或服务端 SVG sanitizer）"
            "再单独走 R-XXX 计划。",
        )

    def test_validation_utils_js_has_no_svg(self) -> None:
        types = _extract_mime_array(
            self.validation_utils_src, "static SUPPORTED_IMAGE_TYPES"
        )
        self.assertNotIn(
            "image/svg+xml",
            types,
            "validation-utils.js (ValidationUtils.SUPPORTED_IMAGE_TYPES) "
            "不应允许 SVG 上传——同 R122 安全理由。",
        )

    def test_webview_ui_js_has_no_svg(self) -> None:
        types = _extract_mime_array(self.webview_ui_src, "const SUPPORTED_IMAGE_TYPES")
        self.assertNotIn(
            "image/svg+xml",
            types,
            "VS Code webview-ui.js 不应允许 SVG 上传——同 R122 安全理由。",
        )


class TestJpgAliasPresentThreeSites(unittest.TestCase):
    """三端前端白名单都必须同时含 ``image/jpeg`` 与 ``image/jpg``。

    why：少数浏览器/上传组件（Edge legacy / Windows 老版本 / 某些剪贴板
    路径）会把 .jpg 文件的 MIME 报作 ``image/jpg`` 而非标准
    ``image/jpeg``。R122 把两个 MIME 都列入白名单，后端 magic-byte
    检测仍按 ``image/jpeg`` 一种实际格式识别。
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.image_upload_src = IMAGE_UPLOAD_JS.read_text(encoding="utf-8")
        cls.validation_utils_src = VALIDATION_UTILS_JS.read_text(encoding="utf-8")
        cls.webview_ui_src = WEBVIEW_UI_JS.read_text(encoding="utf-8")

    def test_image_upload_js_has_jpg_alias(self) -> None:
        types = _extract_mime_array(
            self.image_upload_src, "const SUPPORTED_IMAGE_TYPES"
        )
        self.assertIn("image/jpeg", types)
        self.assertIn("image/jpg", types)

    def test_validation_utils_js_has_jpg_alias(self) -> None:
        types = _extract_mime_array(
            self.validation_utils_src, "static SUPPORTED_IMAGE_TYPES"
        )
        self.assertIn("image/jpeg", types)
        self.assertIn(
            "image/jpg",
            types,
            "validation-utils.js 缺少 image/jpg ——R122 之前是这条 bug 的"
            "唯一漏网之鱼（少数 Edge legacy / Windows 老版本剪贴板路径"
            "上报 image/jpg，会被 ValidationUtils 误判为不支持格式）。",
        )

    def test_webview_ui_js_has_jpg_alias(self) -> None:
        types = _extract_mime_array(self.webview_ui_src, "const SUPPORTED_IMAGE_TYPES")
        self.assertIn("image/jpeg", types)
        self.assertIn("image/jpg", types)


class TestBackendFileValidatorRejectsSvg(unittest.TestCase):
    """后端 ``file_validator.IMAGE_MAGIC_NUMBERS`` 必须**不**含 SVG mime_type。

    反向锁：如果未来有人在后端加了 SVG magic-byte 支持，必须同步：

    1. 实现服务端 SVG sanitizer（剔除 ``<script>`` / ``on*=`` /
       ``xlink:href`` / 嵌入 JS 的 ``<foreignObject>`` 等）；
    2. 评估并加 CSP ``img-src`` 是否要继续允许 SVG（当前 CSP 是
       ``img-src 'self' data: blob:``，SVG 渲染走的是 ``<img>`` 还是
       直接 inline ``<svg>`` 的 DOM 注入？后者会绕过 CSP）；
    3. 同步前端三处白名单。

    本测试不直接禁止后端添加 SVG，只是要求"加 SVG 时先打破这个测试"，
    强制评审者去 review 上述三件事。
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.src = FILE_VALIDATOR_PY.read_text(encoding="utf-8")

    def test_image_magic_numbers_table_excludes_svg(self) -> None:
        # IMAGE_MAGIC_NUMBERS 表里每个 entry 的 mime_type 字段不应包含 svg
        # 我们用一个粗粒度的字符串扫描 + 正则锁，避免在未来重构成更复杂的
        # type system 时整个测试就跪了。
        # 表的开始锚点
        idx = self.src.find("IMAGE_MAGIC_NUMBERS")
        self.assertGreaterEqual(
            idx, 0, "在 file_validator.py 里找不到 IMAGE_MAGIC_NUMBERS"
        )
        # 表的结束锚点：定义后第一个顶层 ``}\n``——保守起见，扫到第一个
        # 模块级常量 / 函数定义即可
        next_def = self.src.find("\ndef ", idx)
        next_class = self.src.find("\nclass ", idx)
        end_candidates = [c for c in (next_def, next_class) if c > 0]
        end = len(self.src) if not end_candidates else min(end_candidates)
        table_body = self.src[idx:end]

        self.assertNotIn(
            '"image/svg+xml"',
            table_body,
            "后端 IMAGE_MAGIC_NUMBERS 不应支持 image/svg+xml ——"
            "SVG 安全展示需要 sanitize 层（DOMPurify 或服务端 SVG "
            "sanitizer）。如确实要加，请先实现 sanitize、评估 CSP "
            "img-src 兼容性、同步前端三处白名单，再删掉本测试。",
        )
        self.assertNotIn(
            "'image/svg+xml'",
            table_body,
            "（同上，单引号变体）",
        )


if __name__ == "__main__":
    unittest.main()
