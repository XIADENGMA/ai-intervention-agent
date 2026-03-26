"""静态资源路由 Mixin — 字体、图标、音频、CSS、JS、Lottie、favicon。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from flask import abort, request, send_from_directory
from flask.typing import ResponseReturnValue

from enhanced_logging import EnhancedLogger

if TYPE_CHECKING:
    pass

logger = EnhancedLogger(__name__)


class StaticRoutesMixin:
    """提供 8 个静态资源路由，由 WebFeedbackUI 通过 MRO 继承。"""

    def _setup_static_routes(self) -> None:  # noqa: C901  — 路由注册集中在此方法
        @self.app.route("/fonts/<filename>")  # type: ignore[attr-defined]
        @self.limiter.exempt  # type: ignore[attr-defined]
        def serve_fonts(filename: str) -> ResponseReturnValue:
            """提供字体文件的静态资源路由

            功能说明：
                安全地提供fonts目录下的字体文件（woff、woff2、ttf等）。

            参数说明：
                filename: 字体文件名（URL路径参数）

            返回值：
                字体文件的二进制内容（application/font-woff等MIME类型）

            频率限制：
                - 已豁免（静态资源不做限流，避免首屏加载被 429 影响）

            注意事项：
                - 使用send_from_directory防止路径遍历攻击
                - 文件名自动清理，不支持../ 等危险路径
            """
            fonts_dir = self._project_root / "fonts"  # type: ignore[attr-defined]
            return send_from_directory(str(fonts_dir), filename)

        @self.app.route("/icons/<filename>")  # type: ignore[attr-defined]
        @self.limiter.exempt  # type: ignore[attr-defined]
        def serve_icons(filename: str) -> ResponseReturnValue:
            """提供图标文件的静态资源路由

            功能说明：
                安全地提供icons目录下的图标文件（ico、png、svg等）。

            参数说明：
                filename: 图标文件名（URL路径参数）

            返回值：
                图标文件的二进制内容（image/x-icon、image/png等MIME类型）

            频率限制：
                - 已豁免（静态资源不做限流，避免首屏加载被 429 影响）

            注意事项：
                - 使用send_from_directory防止路径遍历攻击
                - 文件名自动清理，不支持../ 等危险路径
            """
            icons_dir = self._project_root / "icons"  # type: ignore[attr-defined]
            return send_from_directory(str(icons_dir), filename)

        @self.app.route("/sounds/<filename>")  # type: ignore[attr-defined]
        @self.limiter.exempt  # type: ignore[attr-defined]
        def serve_sounds(filename: str) -> ResponseReturnValue:
            """提供音频文件的静态资源路由

            功能说明：
                安全地提供sounds目录下的音频文件（mp3、wav、ogg等）。

            参数说明：
                filename: 音频文件名（URL路径参数）

            返回值：
                音频文件的二进制内容（audio/mpeg、audio/wav等MIME类型）

            频率限制：
                - 已豁免（静态资源不做限流，避免首屏加载被 429 影响）

            注意事项：
                - 使用send_from_directory防止路径遍历攻击
                - 文件名自动清理，不支持../ 等危险路径
                - 音频文件较大，注意带宽占用
            """
            sounds_dir = self._project_root / "sounds"  # type: ignore[attr-defined]
            return send_from_directory(str(sounds_dir), filename)

        @self.app.route("/static/css/<filename>")  # type: ignore[attr-defined]
        @self.limiter.exempt  # type: ignore[attr-defined]
        def serve_css(filename: str) -> ResponseReturnValue:
            """提供CSS文件的静态资源路由

            功能说明：
                安全地提供static/css目录下的CSS样式文件。

            参数说明：
                filename: CSS文件名（URL路径参数）

            返回值：
                CSS文件内容（text/css MIME类型）

            【性能优化】缓存策略：
                - 普通 CSS 文件：缓存 1 小时
                - 带版本号的 CSS 文件（?v=xxx）：缓存 1 年

            【性能优化】自动压缩版本选择：
                - 自动检测并优先使用 .min.css 压缩版本
                - 如果请求 main.css，优先返回 main.min.css（如存在）

            频率限制：
                - 已豁免（静态资源不做限流，避免首屏加载/MathJax 等资源被 429 影响）

            注意事项：
                - 使用send_from_directory防止路径遍历攻击
                - CSS文件通过CSP nonce验证安全性
                - 使用版本号参数实现缓存失效控制
            """
            css_dir = self._project_root / "static" / "css"  # type: ignore[attr-defined]

            actual_filename = self._get_minified_file(css_dir, filename, ".css")  # type: ignore[attr-defined]

            response = send_from_directory(str(css_dir), actual_filename)

            if request.args.get("v"):
                response.headers["Cache-Control"] = (
                    "public, max-age=31536000, immutable"
                )
            else:
                response.headers["Cache-Control"] = "public, max-age=3600"

            return response

        @self.app.route("/static/js/<filename>")  # type: ignore[attr-defined]
        @self.limiter.exempt  # type: ignore[attr-defined]
        def serve_js(filename: str) -> ResponseReturnValue:
            """提供JavaScript文件的静态资源路由

            功能说明：
                安全地提供static/js目录下的JavaScript脚本文件。

            参数说明：
                filename: JavaScript文件名（URL路径参数）

            返回值：
                JavaScript文件内容（application/javascript MIME类型）

            【性能优化】缓存策略：
                - 普通 JS 文件：缓存 1 小时
                - 带版本号的 JS 文件（?v=xxx）：缓存 1 年

            【性能优化】自动压缩版本选择：
                - 自动检测并优先使用 .min.js 压缩版本
                - 如果请求 multi_task.js，优先返回 multi_task.min.js（如存在）

            频率限制：
                - 已豁免（静态资源不做限流，避免首屏加载/MathJax 等资源被 429 影响）

            注意事项：
                - 使用send_from_directory防止路径遍历攻击
                - JavaScript文件通过CSP nonce验证安全性
                - 使用版本号参数实现缓存失效控制
            """
            js_dir = self._project_root / "static" / "js"  # type: ignore[attr-defined]

            actual_filename = self._get_minified_file(js_dir, filename, ".js")  # type: ignore[attr-defined]

            response = send_from_directory(str(js_dir), actual_filename)

            if request.args.get("v"):
                response.headers["Cache-Control"] = (
                    "public, max-age=31536000, immutable"
                )
            else:
                response.headers["Cache-Control"] = "public, max-age=3600"

            return response

        @self.app.route("/notification-service-worker.js")  # type: ignore[attr-defined]
        @self.limiter.exempt  # type: ignore[attr-defined]
        def serve_notification_service_worker() -> ResponseReturnValue:
            """提供通知 service worker，并允许其控制整个站点作用域。"""
            js_dir = self._project_root / "static" / "js"  # type: ignore[attr-defined]
            response = send_from_directory(
                str(js_dir), "notification-service-worker.js"
            )
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Service-Worker-Allowed"] = "/"
            return response

        @self.app.route("/static/lottie/<filename>")  # type: ignore[attr-defined]
        @self.limiter.exempt  # type: ignore[attr-defined]
        def serve_lottie(filename: str) -> ResponseReturnValue:
            """提供 Lottie 动画 JSON 文件的静态资源路由

            功能说明：
                安全地提供 static/lottie 目录下的 Lottie 动画 JSON 文件。
                主要用于"无有效内容"页面的嫩芽/沙漏等动画资源加载。

            参数说明：
                filename: 动画 JSON 文件名（URL 路径参数）

            返回值：
                JSON 文件内容（application/json MIME 类型）

            频率限制：
                - 已豁免（静态资源不做限流，避免首屏加载时因 429 退化到 emoji）

            注意事项：
                - 仅允许 .json 文件，避免意外暴露其他类型文件
                - 使用 send_from_directory 防止路径遍历攻击
                - 缓存策略由 after_request 统一设置（/static/lottie/ 默认 30 天）
            """
            if not filename or not str(filename).lower().endswith(".json"):
                abort(404)

            lottie_dir = self._project_root / "static" / "lottie"  # type: ignore[attr-defined]
            return send_from_directory(
                str(lottie_dir), filename, mimetype="application/json"
            )

        @self.app.route("/favicon.ico")  # type: ignore[attr-defined]
        @self.limiter.exempt  # type: ignore[attr-defined]
        def favicon() -> ResponseReturnValue:
            """提供网站图标的路由

            功能说明：
                提供网站favicon.ico文件，浏览器会自动请求此文件用于标签页图标。

            返回值：
                icon.ico文件的二进制内容（image/x-icon MIME类型）

            处理逻辑：
                1. 构建icon.ico文件路径
                2. 记录调试日志（路径、文件存在性）
                3. 使用send_from_directory返回文件
                4. 设置正确的MIME类型（image/x-icon）
                5. 禁用缓存（no-cache, no-store, must-revalidate）

            频率限制：
                - 已豁免（静态资源不做限流，避免 favicon 请求被 429 影响）

            副作用：
                - 修改响应头部（Content-Type、Cache-Control等）

            注意事项：
                - 禁用缓存确保图标更新立即生效
                - 浏览器每次访问页面都会请求favicon
                - 文件不存在时Flask返回404
            """
            icons_dir = self._project_root / "icons"  # type: ignore[attr-defined]
            icon_path = icons_dir / "icon.ico"
            logger.debug(f"Favicon请求 - 图标目录: {icons_dir}")
            logger.debug(f"Favicon请求 - 图标文件: {icon_path}")
            logger.debug(f"Favicon请求 - 文件存在: {icon_path.exists()}")

            response = send_from_directory(str(icons_dir), "icon.ico")
            response.headers["Content-Type"] = "image/x-icon"
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
            return response
