"""静态资源路由 Mixin — 字体、图标、音频、CSS、JS、Lottie、favicon。"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from flask import abort, request, send_from_directory
from flask.typing import ResponseReturnValue

from enhanced_logging import EnhancedLogger

if TYPE_CHECKING:
    from flask import Flask
    from flask.wrappers import Response
    from flask_limiter import Limiter

logger = EnhancedLogger(__name__)


# R20.14-D + R21.4：静态资源 Brotli + gzip 预压缩响应器
# ============================================================================
#
# ``scripts/precompress_static.py`` 离线把 ``static/css/*.css``、
# ``static/js/*.js``、``static/locales/*.json`` 这类大文件压成同名 ``.br``
# (R21.4) 和 ``.gz`` (R20.14-D) 副本。本 helper 把「请求带
# ``Accept-Encoding: br, gzip`` 时按优先级 br > gzip > identity 返回对应
# 副本」的协商写到一个地方，所有 serve_* 路由共享。
#
# 协商优先级
# -----------
# 1. 客户端 ``Accept-Encoding`` 含 ``br`` 且 ``.br`` 副本存在 → 服务 ``.br``；
# 2. 客户端 ``Accept-Encoding`` 含 ``gzip`` 且 ``.gz`` 副本存在 → 服务 ``.gz``；
# 3. 否则服务原文件（零开销，识别 ``identity``）。
#
# Brotli 优先于 gzip 的理由：体积更小（实测 R21.4 -17% 到 -23% on top of gzip），
# 主流浏览器自 2017 起全部支持，没有兼容性损失；少数 ``curl`` / 老脚本只发
# ``gzip`` 我们退化到 gzip 也无碍。
#
# 失败兜底：
# - 双副本都不存在 → 服务原文件（zero overhead）；
# - 客户端不支持任何压缩 → 服务原文件（``Accept-Encoding: identity``）；
# - 任何 IO 异常 → fallback 到原路径，让上层路由处理常规 404 / 500。
#
# 必须给所有响应（无论是否压缩）打 ``Vary: Accept-Encoding``，让 CDN /
# 反向代理知道「同一 URL 在不同 Accept-Encoding 下产出不同响应」，避免一个
# 客户端拿到的 ``.br`` 被另一个只支持 gzip 的客户端从中间缓存里命中。


def _parse_accept_encoding(req_obj: object | None = None) -> set[str]:
    """解析 ``Accept-Encoding`` 头，返回客户端支持的编码集合（小写）。

    不严格做 q 值排序——大多数现实客户端要么列了 ``br, gzip``（默认偏好按
    顺序），要么用 ``*`` 占位；少数 ``q=0`` 表示「明确拒绝」时我们也尊重
    （``gzip;q=0`` 表示不要 gzip）。
    """
    # 显式三元 + ``getattr`` 兜底：``req_obj`` 是 ``object | None`` 形式以
    # 兼容测试时传 mock；ty 静态分析看不出 ``req_obj or request`` 在
    # ``req_obj is None`` 时回退到全局 Flask ``request`` 代理，所以做一次
    # 精确判空让类型推断把 fallback 路径单独 narrow 到 ``request``。
    src = req_obj if req_obj is not None else request
    accept = getattr(src, "headers", {}).get("Accept-Encoding", "")
    if not accept:
        return set()

    accepted: set[str] = set()
    for raw_token in accept.split(","):
        token = raw_token.strip()
        if not token:
            continue
        # 拆 ``gzip;q=0.5`` → name="gzip" + qval=0.5
        if ";" in token:
            name_part, _, params = token.partition(";")
            name = name_part.strip().lower()
            qval = 1.0
            for param in params.split(";"):
                pp = param.strip().lower()
                if pp.startswith("q="):
                    try:
                        qval = float(pp[2:])
                    except ValueError:
                        qval = 1.0
                    break
            if qval > 0:
                accepted.add(name)
        else:
            accepted.add(token.lower())
    return accepted


def _client_accepts_gzip(req_obj: object | None = None) -> bool:
    """向后兼容（R20.14-D）：客户端是否支持 gzip。

    R21.4 之后建议直接用 :func:`_parse_accept_encoding`，但保留此 wrapper
    以避免破坏外部调用方（如果有人在 fork 里直接 import 它）。
    """
    encs = _parse_accept_encoding(req_obj)
    return "gzip" in encs or "*" in encs


def _client_accepts_brotli(req_obj: object | None = None) -> bool:
    """R21.4：客户端是否支持 Brotli。"""
    encs = _parse_accept_encoding(req_obj)
    return "br" in encs or "*" in encs


def _send_with_optional_gzip(
    directory: Path,
    filename: str,
    *,
    mimetype: str | None = None,
) -> Response:
    """``send_from_directory`` 的 Brotli/gzip 协商版本（R20.14-D + R21.4）。

    协商优先级（R21.4）：
    1. 客户端支持 ``br`` 且 ``directory / (filename + '.br')`` 存在 → 服务 ``.br``；
    2. 客户端支持 ``gzip`` 且 ``directory / (filename + '.gz')`` 存在 → 服务 ``.gz``；
    3. 否则退化到 ``send_from_directory(directory, filename)`` —— 历史行为。

    Content-Type 永远是 ``mimetype`` （原文件的类型），哪怕实际发送了
    ``.br`` / ``.gz`` 副本——``Content-Encoding`` 头告诉浏览器「这是
    transfer-encoding，原始内容是 mimetype」。

    所有响应都打 ``Vary: Accept-Encoding``。

    函数名仍带 ``gzip`` 是历史包袱（R20.14-D 时只有 gzip）；R21.4 改实现
    增加 brotli 协商但不改函数名以免破坏既有调用。新代码可以直接用此函数，
    它实质是 ``_send_with_optional_compressed``。
    """
    br_filename = filename + ".br"
    gz_filename = filename + ".gz"
    br_path = directory / br_filename
    gz_path = directory / gz_filename

    response: Response | None = None
    try:
        if _client_accepts_brotli() and br_path.is_file():
            # R21.4：Brotli 优先（实测体积比 gzip 小 17-23%，主流 client 全支持）
            response = send_from_directory(
                str(directory), br_filename, mimetype=mimetype
            )
            response.headers["Content-Encoding"] = "br"
        elif _client_accepts_gzip() and gz_path.is_file():
            response = send_from_directory(
                str(directory), gz_filename, mimetype=mimetype
            )
            response.headers["Content-Encoding"] = "gzip"
    except OSError:
        # IO 异常时落到 identity 分支
        response = None

    if response is None:
        response = send_from_directory(str(directory), filename, mimetype=mimetype)

    # 即使没用压缩也要打 Vary，否则中间缓存可能错配。
    existing_vary = response.headers.get("Vary", "")
    if "Accept-Encoding" not in existing_vary:
        response.headers["Vary"] = (
            f"{existing_vary}, Accept-Encoding".lstrip(", ")
            if existing_vary
            else "Accept-Encoding"
        )

    return response


class StaticRoutesMixin:
    """提供 8 个静态资源路由，由 WebFeedbackUI 通过 MRO 继承。"""

    if TYPE_CHECKING:
        app: Flask
        limiter: Limiter
        _project_root: Path

        def _get_minified_file(
            self, directory: str | Path, filename: str, extension: str
        ) -> str: ...

    def _setup_static_routes(self) -> None:
        @self.app.route("/fonts/<filename>")
        @self.limiter.exempt
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
            fonts_dir = self._project_root / "fonts"
            return send_from_directory(str(fonts_dir), filename)

        @self.app.route("/icons/<filename>")
        @self.limiter.exempt
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
            icons_dir = self._project_root / "icons"
            return send_from_directory(str(icons_dir), filename)

        @self.app.route("/manifest.webmanifest")
        @self.limiter.exempt
        def serve_webmanifest() -> ResponseReturnValue:
            """提供 PWA Web App Manifest 文件。

            功能说明：
                返回 ``icons/manifest.webmanifest``，供浏览器在
                ``Add to Home Screen`` / ``Install app`` 时识别应用名、图标
                与启动 URL，是 ai.local 等域名安装为 PWA 后图标显示正确的关键。

            返回值：
                manifest 文件内容（application/manifest+json MIME 类型）。

            频率限制：
                - 已豁免：浏览器仅在 PWA 安装/检测时拉取，几乎不产生流量。
            """
            icons_dir = self._project_root / "icons"
            response = send_from_directory(
                str(icons_dir),
                "manifest.webmanifest",
                mimetype="application/manifest+json",
            )
            response.headers["Cache-Control"] = "public, max-age=3600"
            return response

        @self.app.route("/sounds/<filename>")
        @self.limiter.exempt
        def serve_sounds(filename: str) -> ResponseReturnValue:
            """提供音频文件的静态资源路由

            功能说明：
                安全地提供sounds目录下的音频文件（mp3、wav、ogg）。

            参数说明：
                filename: 音频文件名（URL路径参数）

            返回值：
                音频文件的二进制内容（audio/mpeg、audio/wav等MIME类型）

            频率限制：
                - 已豁免（静态资源不做限流，避免首屏加载被 429 影响）

            注意事项：
                - 仅允许 .mp3 / .wav / .ogg 三种扩展名（与 ``/static/lottie/``
                  的白名单同构）；意图：``send_from_directory`` 仅防路径穿越，
                  没有"只暴露音频"的语义保证；如果将来 ``sounds/`` 目录被
                  误放入 ``.json`` 配置 / ``.txt`` README，扩展名白名单
                  能继续把它们关在 404 后面，避免意外信息泄露。
                - 使用send_from_directory防止路径遍历攻击
                - 文件名自动清理，不支持../ 等危险路径
                - 音频文件较大，注意带宽占用
            """
            if not filename or not str(filename).lower().endswith(
                (".mp3", ".wav", ".ogg")
            ):
                abort(404)

            sounds_dir = self._project_root / "sounds"
            return send_from_directory(str(sounds_dir), filename)

        @self.app.route("/static/css/<filename>")
        @self.limiter.exempt
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
            css_dir = self._project_root / "static" / "css"

            actual_filename = self._get_minified_file(css_dir, filename, ".css")

            # R20.14-D：``Accept-Encoding: gzip`` + 同名 ``.gz`` 时，发送预压缩
            # 副本（运行时零 CPU 开销，体积砍 70-85%）；否则原路径不变。
            response = _send_with_optional_gzip(
                css_dir, actual_filename, mimetype="text/css"
            )

            if request.args.get("v"):
                response.headers["Cache-Control"] = (
                    "public, max-age=31536000, immutable"
                )
            else:
                response.headers["Cache-Control"] = "public, max-age=3600"

            return response

        @self.app.route("/static/js/<filename>")
        @self.limiter.exempt
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
            js_dir = self._project_root / "static" / "js"

            actual_filename = self._get_minified_file(js_dir, filename, ".js")

            # R20.14-D：同 serve_css，gzip 协商优先，无 .gz 副本则透明 fallback。
            response = _send_with_optional_gzip(
                js_dir, actual_filename, mimetype="application/javascript"
            )

            if request.args.get("v"):
                response.headers["Cache-Control"] = (
                    "public, max-age=31536000, immutable"
                )
            else:
                response.headers["Cache-Control"] = "public, max-age=3600"

            return response

        @self.app.route("/notification-service-worker.js")
        @self.limiter.exempt
        def serve_notification_service_worker() -> ResponseReturnValue:
            """提供通知 service worker，并允许其控制整个站点作用域。"""
            js_dir = self._project_root / "static" / "js"
            response = send_from_directory(
                str(js_dir), "notification-service-worker.js"
            )
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Service-Worker-Allowed"] = "/"
            return response

        @self.app.route("/static/locales/<filename>")
        @self.limiter.exempt
        def serve_locales(filename: str) -> ResponseReturnValue:
            """提供 i18n 语言包 JSON 文件。

            R20.14-D 引入此路由前，``/static/locales/<lang>.json`` 走 Flask
            默认 ``static_folder`` 处理，没有 gzip 协商。语言包单文件 ~11 KB，
            gzip 后 ~2 KB，对 ``language='auto'`` 模式（R20.12-B 的 inline
            优化对它无效）的首屏 i18n 切换体感影响明显。

            白名单：仅 ``.json`` 防止意外暴露其他类型文件。
            缓存：带 ``?v=hash`` 走 1 年 immutable，无版本号走 1 小时短缓存。
            """
            if not filename or not str(filename).lower().endswith(".json"):
                abort(404)

            locales_dir = self._project_root / "static" / "locales"
            response = _send_with_optional_gzip(
                locales_dir, filename, mimetype="application/json"
            )

            if request.args.get("v"):
                response.headers["Cache-Control"] = (
                    "public, max-age=31536000, immutable"
                )
            else:
                response.headers["Cache-Control"] = "public, max-age=3600"
            return response

        @self.app.route("/static/lottie/<filename>")
        @self.limiter.exempt
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

            lottie_dir = self._project_root / "static" / "lottie"
            # R20.14-D：Lottie JSON 通常 50-200 KB（``loading-leaves.json`` 即
            # 50 KB+），gzip 后 ~10-30 KB，3-5× 体积比，值得协商压缩。
            return _send_with_optional_gzip(
                lottie_dir, filename, mimetype="application/json"
            )

        @self.app.route("/favicon.ico")
        @self.limiter.exempt
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
            icons_dir = self._project_root / "icons"
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
