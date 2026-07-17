"""Web 反馈界面 - Flask Web UI，支持多任务、文件上传、通知、安全机制。"""

__all__ = [
    "AUTO_RESUBMIT_TIMEOUT_MAX",
    "AUTO_RESUBMIT_TIMEOUT_MIN",
    "DEFAULT_ALLOWED_NETWORKS",
    "MDNS_DEFAULT_HOSTNAME",
    "MDNS_SERVICE_TYPE_HTTP",
    "VALID_BIND_INTERFACES",
    "WebFeedbackUI",
    "_get_default_route_ipv4",
    "_is_probably_virtual_interface",
    "_list_non_loopback_ipv4",
    "_sync_existing_tasks_timeout_from_config",
    "_sync_network_security_from_config",
    "build_trusted_hosts",
    "detect_best_publish_ipv4",
    "normalize_mdns_hostname",
    "validate_allowed_networks",
    "validate_bind_interface",
    "validate_blocked_ips",
    "validate_network_cidr",
    "validate_network_security_config",
    "validate_trusted_hosts",
]

import argparse
import json
import os
import re
import signal
import sys
import threading
import time
from functools import lru_cache
from pathlib import Path
from typing import Any, cast

from flask import (
    Flask,
    jsonify,
    render_template,
    request,
)
from flask.typing import ResponseReturnValue
from flask_compress import Compress
from flask_cors import CORS

# R26.3: ``markdown`` 顶级 import 实测 ~8.9 ms cold-start cost (cold cache, macOS M1 / Python 3.11)，
# 加上 ``markdown.Markdown(extensions=[...10 plugins...])`` 实例化的 ~10-15 ms（codehilite
# Pygments + footnote AST + nl2br + md_in_html + ... 一次性预热全部插件的 regex/lexer），合计
# ~20-25 ms 落在 ``web_ui`` 子进程冷启动的 wall-clock 上。R26.3 把两件事都推迟到首次
# ``render_markdown(text)`` 调用：(1) ``import markdown`` 下沉到 ``render_markdown`` 体内，
# (2) ``markdown.Markdown(...)`` 实例化也推迟，由 ``self.md`` 的 ``None`` sentinel 触发，
# 配 ``self._md_lock`` 守住「双重检查 lazy init」语义（``markdown.Markdown`` 实例非线程安全，
# 现成的锁顺手保护初始化 race）。生产路径上首次 ``render_markdown`` 是 ``GET /api/config``
# 第一次轮询命中 active task 时；早于此之前的 ``GET /static/*``、``GET /``、``OPTIONS *``
# 等路径都不需要 Markdown 实例，纯粹的延迟收益。
#
# R26.1/R452: ``flask_limiter`` imports 故意不在这里，也不在
# ``WebFeedbackUI.__init__`` 里。Web UI 默认桌面 profile 用本地
# ``WebUiRateLimiter`` 保留 ``limit`` / ``exempt`` 兼容面，避免构造期重新拉入
# ``flask_limiter`` 的 cold-start 成本。
from ai_intervention_agent.enhanced_logging import EnhancedLogger
from ai_intervention_agent.feedback_types import FeedbackResult
from ai_intervention_agent.i18n import msg
from ai_intervention_agent.protocol import get_capabilities, get_server_clock
from ai_intervention_agent.remote_environment import detect_remote_environment

# R20.8: 直接 import 自 task_queue_singleton 模块，避免拖入 fastmcp/mcp 依赖链
# （web_ui.py 是子进程入口，不需要 MCP server 能力，详见 task_queue_singleton.py 注释）。
from ai_intervention_agent.runtime_constants import (
    AUTO_RESUBMIT_TIMEOUT_DEFAULT,
    AUTO_RESUBMIT_TIMEOUT_MAX,
    AUTO_RESUBMIT_TIMEOUT_MIN,
)
from ai_intervention_agent.task_queue_singleton import get_task_queue
from ai_intervention_agent.web_ui_config_sync import (
    _ensure_config_changed_sse_callback_registered,
    _ensure_feedback_timeout_hot_reload_callback_registered,
    _ensure_network_security_hot_reload_callback_registered,
    _get_default_auto_resubmit_timeout_from_config,
    _sync_existing_tasks_timeout_from_config,
    _sync_network_security_from_config,
)
from ai_intervention_agent.web_ui_mdns import MdnsMixin
from ai_intervention_agent.web_ui_mdns_utils import (
    MDNS_DEFAULT_HOSTNAME,
    MDNS_SERVICE_TYPE_HTTP,
    _get_default_route_ipv4,
    _is_probably_virtual_interface,
    _list_non_loopback_ipv4,
    detect_best_publish_ipv4,
    normalize_mdns_hostname,
)
from ai_intervention_agent.web_ui_rate_limiter import (
    WebUiLimiterProtocol,
    WebUiRateLimiter,
)
from ai_intervention_agent.web_ui_routes import (
    FeedbackRoutesMixin,
    NotificationRoutesMixin,
    StaticRoutesMixin,
    SystemRoutesMixin,
    TaskRoutesMixin,
)
from ai_intervention_agent.web_ui_routes._upload_helpers import MAX_TOTAL_UPLOAD_BYTES
from ai_intervention_agent.web_ui_security import SecurityMixin, build_trusted_hosts
from ai_intervention_agent.web_ui_validators import (
    DEFAULT_ALLOWED_NETWORKS,
    VALID_BIND_INTERFACES,
    validate_allowed_networks,
    validate_auto_resubmit_timeout,
    validate_bind_interface,
    validate_blocked_ips,
    validate_network_cidr,
    validate_network_security_config,
    validate_trusted_hosts,
)

logger = EnhancedLogger(__name__)


def get_config() -> Any:
    """Lazy proxy for the global ConfigManager.

    ``config_manager`` constructs its global ``ConfigManager()`` at module import
    time, and that path imports ``shared_types`` / Pydantic section models.
    ``web_ui`` only needs configuration once an instance is rendering or handling
    a route, so keep the public ``web_ui.get_config`` patch surface but defer the
    heavy import until first use.
    """
    from ai_intervention_agent.config_manager import get_config as _get_config

    return _get_config()


# ============================================================================
# 版本号和项目信息
# ============================================================================

# GitHub 仓库地址
GITHUB_URL = "https://github.com/XIADENGMA/ai-intervention-agent"


@lru_cache(maxsize=1)
def get_project_version() -> str:
    """读取本包版本号，结果用 ``lru_cache`` 缓存。

    BUG3 修复 — 历史实现把 ``pyproject.toml`` 拼成
    ``src/ai_intervention_agent/pyproject.toml``（与 ``__file__`` 同目录），
    但仓库实际只有 ``<repo-root>/pyproject.toml``；开发模式 / pip 安装下都
    找不到文件，函数永远返回 ``"unknown"``，前端拼 ``v`` 前缀后渲染为
    ``vunknown``。

    新实现的多层兜底：
        1. ``importlib.metadata.version("ai-intervention-agent")`` — 标准
           PEP 566 dist-info 元数据读取，pip / uv / editable install 全
           覆盖；这是 Python 3.8+ 唯一稳定的运行时版本号获取方式。
        2. ``<repo-root>/pyproject.toml`` 解析 — 开发模式下若包还没安装
           dist-info（罕见，但 ``python -m`` 直接跑源码会命中）的兜底。
           ``Path(__file__).parents[2]`` 才是仓库根（parent 是 module
           dir、parent.parent 是 src/、parent.parent.parent 是 repo root）。
        3. 返回 ``"unknown"`` — 上述两层全失败时的最终兜底，前端会自行
           隐藏版本号或显示为 ``vunknown``（仍可用，但代表上游真异常）。
    """
    try:
        from importlib.metadata import PackageNotFoundError, version

        return version("ai-intervention-agent")
    except PackageNotFoundError:
        # 包尚未通过 pip / uv 安装；走开发模式 pyproject.toml 解析路径。
        pass
    except Exception as e:
        logger.warning(
            f"importlib.metadata 读取版本号失败，尝试 pyproject.toml 兜底：{e}",
            exc_info=True,
        )

    try:
        # __file__ 是 src/ai_intervention_agent/web_ui.py：
        #   parents[0] = src/ai_intervention_agent/
        #   parents[1] = src/
        #   parents[2] = <repo-root>/
        pyproject_path = Path(__file__).resolve().parents[2] / "pyproject.toml"

        if pyproject_path.exists():
            try:
                import tomllib

                with open(pyproject_path, "rb") as f:
                    data = tomllib.load(f)
                project_data = data.get("project")
                raw_version: Any = (
                    project_data.get("version", "unknown")
                    if isinstance(project_data, dict)
                    else "unknown"
                )
                return raw_version if isinstance(raw_version, str) else str(raw_version)
            except Exception:
                # 兜底：正则提取 version = "X.Y.Z" 那一行
                with open(pyproject_path, encoding="utf-8") as f:
                    content = f.read()
                match = re.search(r'version\s*=\s*["\']([^"\']+)["\']', content)
                if match:
                    return match.group(1)
    except Exception as e:
        logger.warning(f"读取 pyproject.toml 版本号失败：{e}", exc_info=True)

    return "unknown"


@lru_cache(maxsize=8)
def _read_inline_locale_json(locale_path_str: str) -> str | None:
    """读取 locale JSON 文件并返回已序列化的字符串（R20.12-B 内联首屏 locale）。

    返回值约定：
        - 成功：JSON 序列化后的紧凑字符串（``json.dumps(data, ensure_ascii=False, separators=(",", ":"))``），
          模板用 Jinja2 ``|safe`` 注入到 ``window._AIIA_INLINE_LOCALE``；
        - 失败：``None``，模板会跳过 inline 注入，前端 ``i18n.init`` 走原 fetch 兜底路径。

    设计要点：
        - **缓存**：``lru_cache(maxsize=8)`` 让每次 ``GET /`` 请求只读 1 次磁盘（首请求 ~3 ms 解析+
          序列化，命中后 <1 μs）。8 条容量足够覆盖 ``en`` / ``zh-CN`` / ``_pseudo/pseudo`` 等
          所有 locale 同时被多 Web UI 实例调用的场景；
        - **入参 str 而非 Path**：``Path`` 虽然可哈希，但 ``Path("a/b") == Path("./a/b")`` 不成立，
          可能造成同一文件被缓存为两条；接受 ``str`` 让调用方先 ``str(path.resolve())`` 归一化；
        - **紧凑序列化**：``separators=(",", ":")`` 删空格让 inline 体积比直接传 dict 给
          Jinja ``|tojson`` 小 ~15%（zh-CN.json 11 KB → 9.4 KB），HTML 体积更友好；
        - **ensure_ascii=False**：中文/日文等 BMP 外字符直接保留 UTF-8，避免 ``\\uXXXX`` 转义把
          字节数翻倍。模板已声明 ``<meta charset="UTF-8">``，安全；
        - **失败默认 None**：磁盘损坏 / 权限问题 / JSON 解析失败均不影响 Web UI 正常启动，
          前端 ``i18n.init`` 检测到 ``window._AIIA_INLINE_LOCALE === undefined`` 后走旧 fetch 路径。

    安全：
        locale 文件来自项目内置 ``static/locales/``，**非用户输入**，不存在注入风险。Jinja2 的
        ``|safe`` filter 在这里安全 —— 我们已经 ``json.dumps`` 把所有特殊字符转义。但仍要在
        模板中用 ``</script>`` 字符串截断防御（``<`` 替换为 ``\\u003c``），见 ``templates/web_ui.html``。
    """
    try:
        with open(locale_path_str, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return None
        return json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    except (OSError, json.JSONDecodeError, ValueError):
        return None


# ============================================================================
# Swagger UI opt-in helpers (R23.3)
# ============================================================================

# 接受的"启用 Swagger"环境变量取值（大小写不敏感、首尾空白 strip）。这套
# 真值集合与 ``config_manager`` 内的 env-bool 解析保持一致，方便运维脚本
# 用同一组取值控制各种 opt-in flag。其它任何字符串（含未设置 / 空串 /
# "0" / "false" / "no" / "off"）都视为禁用，避免「无意中泄漏环境变量」
# 误启用 Swagger 文档端点。
_SWAGGER_ENABLED_TRUTHY_VALUES: frozenset[str] = frozenset({"1", "true", "yes", "on"})
_MISSING_OPTION_DEFAULTS: object = object()
_SWAGGER_DISABLED_FALLBACK_HTML = """<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><title>API docs disabled</title>
<style>body{{font-family:system-ui,-apple-system,sans-serif;max-width:640px;margin:48px auto;padding:0 16px;color:#333;line-height:1.5}}
code{{background:#f4f4f4;padding:2px 6px;border-radius:3px;font-size:0.95em}}
a{{color:#0366d6}}h1{{font-size:1.4em;margin-bottom:8px}}p{{margin:12px 0}}</style></head><body>
<h1>API docs are disabled by default</h1>
<p>The interactive Swagger UI for this Web UI's REST API is disabled by default to keep the
subprocess cold-start fast (saves ~75 ms by skipping <code>flasgger</code> import).</p>
<p>To enable the Swagger UI, set the environment variable
<code>AI_AGENT_ENABLE_SWAGGER=1</code> (or <code>true</code> / <code>yes</code> / <code>on</code>)
when launching <code>web_ui.py</code> and reload this page.</p>
<p>The Web UI's REST API itself is fully functional — only the human-friendly documentation
viewer is gated. See the <a href="{github_url}#api-docs">project README</a> for the
complete API reference.</p>
</body></html>
"""


def _is_swagger_enabled_via_env() -> bool:
    """检查 ``AI_AGENT_ENABLE_SWAGGER`` 环境变量是否启用 Swagger UI。

    R23.3：这个 helper 故意写成模块级函数（不放进 ``WebFeedbackUI`` 类），
    便于测试时直接 ``patch.object(web_ui, "_is_swagger_enabled_via_env",
    return_value=True)``，且支持子进程在 ``__init__`` 之前的早期路径
    （未来如果有别的 module-level setup 也要看这个 flag，可以共用同一函数）。

    取值约定：
    - 设置为 ``"1"`` / ``"true"`` / ``"yes"`` / ``"on"``（大小写不敏感、首
      尾空白 strip）→ 启用，``__init__`` 同步 import flasgger + 实例化 Swagger，
      cold start +75 ms 但 ``/apidocs/`` 真实可用。
    - 其它任何取值（空串 / 未设置 / ``"0"`` / ``"false"`` / 其它字符串）→ 禁
      用，``__init__`` 跳过 flasgger 完全，注册 fallback ``/apidocs/`` 路由
      返回轻量级 HTML 提示页面。

    Returns:
        bool: 是否启用 Swagger UI。
    """
    raw = os.environ.get("AI_AGENT_ENABLE_SWAGGER", "")
    return raw.strip().lower() in _SWAGGER_ENABLED_TRUTHY_VALUES


def _task_predefined_options_defaults(task: Any) -> Any:
    """Return task option defaults without eager fallback allocation."""
    defaults = getattr(task, "predefined_options_defaults", None)
    return defaults or []


def _task_remaining_time(task: Any, now_monotonic: float) -> int:
    """Return task remaining time, reusing a caller-provided monotonic snapshot."""
    get_remaining_time = task.get_remaining_time
    try:
        return int(get_remaining_time(now_monotonic=now_monotonic))
    except TypeError:
        # Compatibility for old task-like objects and tests whose method predates
        # the injected monotonic snapshot argument.
        return int(get_remaining_time())


# ============================================================================
# 模块级状态（配置热更新回调使用，web_ui_config_sync 通过 lazy import 访问）
# ============================================================================

_FEEDBACK_TIMEOUT_CALLBACK_REGISTERED: bool = False
_LAST_APPLIED_AUTO_RESUBMIT_TIMEOUT: int | None = None
_CURRENT_WEB_UI_INSTANCE: Any | None = None
_NETWORK_SECURITY_CALLBACK_REGISTERED: bool = False
_NETWORK_SECURITY_CALLBACK_LOCK = threading.Lock()
# RLock rationale (R331 contract): _ensure_feedback_timeout_hot_reload_
# callback_registered 在持有此锁的 with 块内直接调用 _sync_existing_tasks_
# timeout_from_config (web_ui_config_sync.py:128 → :137), 而后者**也会**
# `with _FEEDBACK_TIMEOUT_CALLBACK_LOCK:` (line 47), 即同一线程在持锁状态
# 下重入获取同一锁。Lock 会 self-deadlock, 必须 RLock。
_FEEDBACK_TIMEOUT_CALLBACK_LOCK = threading.RLock()
# R48：``config_changed`` SSE 推送回调注册状态。一次注册全局生效；后续
# config 文件 mtime 变化时通过 ``_sse_bus.emit("config_changed", ...)``
# 让所有连着的 client（浏览器 PWA / VSCode webview / 状态栏）显式提示
# 「配置已变更，建议重载」，而不是让用户忍受"我以为我改了配置但没生效"
# 的 silent staleness。
_CONFIG_CHANGED_SSE_CALLBACK_REGISTERED: bool = False
_CONFIG_CHANGED_SSE_CALLBACK_LOCK = threading.Lock()

# ============================================================================
# R26.2: ``_get_template_context`` 热路径常量与 lru_cache
# ============================================================================
#
# ``_get_template_context`` 在两条路径上跑：(a) 浏览器对 ``/`` 的每次 GET（人
# 类用户每次刷新页面 1 次），(b) VS Code webview 的每次 ``_getHtmlContent`` 重
# 渲染（``resolveWebviewView`` 初始 + ``setUrl`` 切换 + 语言切换 re-render
# 等场景，单次会话可能 5-10 次）。每次调用之前实测 ~0.07 ms，但里面有 4 次
# ``Path(file_path).stat().st_mtime`` syscall（CSS/multi_task/theme/app 各
# 一次）+ 一次 ``Path(__file__).resolve()`` syscall + 每次都重新分配 12 元素
# 的 ``_RTL_LANG_PREFIXES`` tuple，全是稳态可缓存的纯函数依赖。R26.2 做以下三
# 件事：
# - 把 ``_RTL_LANG_PREFIXES`` 提到模块级 frozenset（lookup O(1)，分配一次）；
# - 在 ``__init__`` 里把 ``static_dir`` 算好缓存到 ``self``；
# - 把 ``_get_file_version`` 拆成接受 ``str`` 的 ``@lru_cache`` 自由函数，按文件路径缓存
#   stat 结果。dev 场景下编辑文件需要重启 web_ui subprocess 才能反映新版本号，
#   但这与现有 ``_read_inline_locale_json`` 的 lru_cache 行为一致——dev 重启
#   subprocess 已是日常操作，不算回归。
#
# 收益：``_get_template_context`` 从 ~0.07 ms 进一步降到 ~0.02 ms（每次调用
# 省 4 个 stat() syscall + 1 个 Path.resolve() syscall + 12 元素 tuple 分配），
# 在多 webview 重渲染场景下累积可见。
# R26.3: ``markdown.Markdown`` 实例的 extensions / extension_configs 提到模块级，
# 让 ``render_markdown`` 的 lazy-init 路径只调用一行 ``markdown.Markdown(**_MD_INIT_KWARGS)``，
# 配置内容与原来逐字相同——10 个扩展（fenced_code / codehilite / tables / toc / nl2br /
# attr_list / def_list / abbr / footnotes / md_in_html）+ codehilite 的 Pygments + monokai
# 内联样式配置。修改这两个常量等同于改变全部 prompt 的渲染行为，需要走 doc + 测试同步流程。
_MD_EXTENSIONS: list[str] = [
    "fenced_code",
    "codehilite",
    "tables",
    "toc",
    "nl2br",
    "attr_list",
    "def_list",
    "abbr",
    "footnotes",
    "md_in_html",
]

_MD_EXTENSION_CONFIGS: dict[str, dict[str, Any]] = {
    "codehilite": {
        "css_class": "highlight",
        "use_pygments": True,
        "noclasses": True,
        "pygments_style": "monokai",
        "guess_lang": True,
        "linenums": False,
    }
}


_RTL_LANG_PREFIXES: frozenset[str] = frozenset(
    {
        "ar",
        "fa",
        "he",
        "iw",
        "ps",
        "ur",
        "yi",
        "ug",
        "ckb",
        "ku",
        "dv",
        "sd",
    }
)


@lru_cache(maxsize=64)
def _compute_file_version(file_path_str: str) -> str:
    """根据文件 mtime 生成 8 位版本字符串，按 ``file_path_str`` 缓存。

    使用 ``str`` 而不是 ``Path`` 作为 cache key，因为 ``Path`` 的 ``__hash__`` 比
    ``str`` 的更慢；外层调用方传 ``str(path)`` 即可。

    缓存语义与 ``_read_inline_locale_json`` 一致：进程级缓存，文件改动需重启进程
    才能反映新 mtime——dev 重启 web_ui subprocess 已是日常操作，prod 部署后文件
    不变所以缓存命中率 100%。
    """
    try:
        from pathlib import Path as _P

        mtime = _P(file_path_str).stat().st_mtime
        return str(int(mtime))[-8:]
    except OSError:
        return "1"


@lru_cache(maxsize=1)
def _get_module_static_dir() -> Path:
    """返回 ``web_ui.py`` 同目录下的 ``static/`` 路径，模块级 lru_cache 一次。

    R26.2 引入：``WebFeedbackUI._get_template_context`` 优先使用 ``self._static_dir``
    （由 ``__init__`` 填充），但部分单元测试通过 ``object.__new__(WebFeedbackUI)``
    跳过 ``__init__`` 直接构造裸对象，此时 ``self._static_dir`` 不存在；这条
    fallback 路径让那些测试继续工作而不必显式设置 ``_static_dir``。
    """
    return Path(__file__).resolve().parent / "static"


class WebFeedbackUI(
    SecurityMixin,
    MdnsMixin,
    TaskRoutesMixin,
    FeedbackRoutesMixin,
    NotificationRoutesMixin,
    StaticRoutesMixin,
    SystemRoutesMixin,
):
    """Web 反馈界面核心类 - Flask 应用、安全策略、API 路由、任务管理。

    功能通过 Mixin 组织：
    - SecurityMixin          — IP 访问控制、CSP、安全头（web_ui_security.py）
    - MdnsMixin              — mDNS/Zeroconf 服务发布（web_ui_mdns.py）
    - TaskRoutesMixin        — 任务 CRUD（5 个路由）
    - FeedbackRoutesMixin    — 反馈提交/查询（3 个路由）
    - NotificationRoutesMixin — 通知配置/触发（5 个路由）
    - StaticRoutesMixin      — 静态资源（8 个路由）
    - SystemRoutesMixin      — 系统集成（用 IDE 打开配置文件等）
    核心路由（index / config / health / close）保留在本类。
    """

    def __init__(
        self,
        prompt: str,
        predefined_options: list[str] | None = None,
        task_id: str | None = None,
        auto_resubmit_timeout: int = AUTO_RESUBMIT_TIMEOUT_DEFAULT,
        host: str = "0.0.0.0",
        port: int = 8080,
        external_base_url: str = "",
        mdns_hostname: str = MDNS_DEFAULT_HOSTNAME,
        trusted_hosts: list[str] | None = None,
    ):
        """初始化 Flask 应用、安全策略、路由"""
        self.prompt = prompt
        self.predefined_options = predefined_options or []
        self.task_id = task_id
        self.auto_resubmit_timeout = auto_resubmit_timeout
        self.host = host
        self.port = port
        self.external_base_url = external_base_url
        self.mdns_hostname = mdns_hostname
        self.trusted_hosts = trusted_hosts or []
        # mDNS / DNS-SD 状态（仅在 run() 真正启动服务时启用）
        self._mdns_zeroconf: Any | None = None
        self._mdns_service_info: Any | None = None
        self._mdns_hostname: str | None = None
        self._mdns_publish_ip: str | None = None
        # R20.11: mDNS register 在后台 daemon 线程异步执行，避免 1.7s 的 conflict-probe
        # 阻塞 Flask listen socket 的可用性。run() 启动 thread，_stop_mdns 在 finally
        # 中 join 等待清理。
        self._mdns_thread: threading.Thread | None = None
        self.feedback_result: FeedbackResult | None = None
        self._project_root: Path = Path(__file__).resolve().parent
        # R26.2: 缓存 static 目录路径，避免每次 ``_get_template_context`` 都重新
        # ``Path(__file__).resolve().parent / "static"``（含 syscall + 字符串拼接）
        self._static_dir: Path = self._project_root / "static"
        self.current_prompt = prompt if prompt else ""
        self.current_options = predefined_options or []
        self.current_options_defaults: list[bool] = []
        self.current_task_id = task_id
        self.current_auto_resubmit_timeout = auto_resubmit_timeout
        # 单任务模式下：current_auto_resubmit_timeout 是否为“显式指定”（/api/update 传入）
        # - False：认为来自配置默认值，应随配置热更新
        # - True：认为调用方显式指定，不随全局配置变化
        self._single_task_timeout_explicit = False
        self.has_content = bool(prompt)
        self.initial_empty = not bool(prompt)
        # RLock rationale (R331 contract): WebFeedbackUI 会被轮询与提交并发
        # 访问（Flask 默认 threaded）, 用锁保护共享状态。RLock 而非 Lock 是
        # 防御性选择: 未来若有 callback (render_markdown / update_*) 在持锁
        # 状态下回调回来访问同一状态, RLock 避免 self-deadlock。当前 codebase
        # 内无实际 reentry chain, 但为防御未来扩展保留 RLock。
        self._state_lock = threading.RLock()
        self._network_security_config_lock = threading.Lock()
        self._network_security_config_loaded_from_config = False
        self._base_config_runtime_hooks_registered = False
        self._base_config_runtime_hooks_lock = threading.Lock()
        self._task_queue_runtime_hooks_registered = False
        self._task_queue_runtime_hooks_lock = threading.Lock()
        self.app = Flask(__name__)
        self.app.config["TRUSTED_HOSTS"] = build_trusted_hosts(
            host=host,
            mdns_hostname=mdns_hostname,
            external_base_url=external_base_url,
            configured_trusted_hosts=self.trusted_hosts,
        )
        _cors_origins: list[str | re.Pattern[str]] = [
            f"http://localhost:{port}",
            f"http://127.0.0.1:{port}",
            re.compile(r"^vscode-webview://"),
        ]
        if host not in ("127.0.0.1", "localhost", "::1"):
            _cors_origins.append(f"http://{host}:{port}")
        CORS(
            self.app,
            origins=_cors_origins,
            supports_credentials=False,
        )

        # ==================================================================
        # R17.6 第一道闸：请求体上限（multipart 解析前的硬闸）
        # ==================================================================
        # 设 ``MAX_CONTENT_LENGTH`` 让 Flask/Werkzeug 在 multipart 解析阶段就 reject
        # 超大请求 —— 避免恶意请求把 100GB 单个 ``image_*`` part 先流到磁盘临时文件
        # 再被下游 ``_upload_helpers`` cap 拒绝（已经晚了：磁盘写入 + 后续
        # ``file.read()`` 全量加载 = 必然 OOM/磁盘写满）。
        #
        # 阈值 = ``MAX_TOTAL_UPLOAD_BYTES`` (100 MB) + 1 MB buffer，覆盖：
        #   - multipart boundary + part headers（每张图 ~1-2 KB × 10 张 = ~20 KB）
        #   - ``feedback_text`` / ``selected_options`` form 字段（< 100 KB 上限）
        #   - 其他 form 字段 + safety margin
        # form-only 文本请求 < 1 KB，不受影响（OWASP "Limit upload size" 推荐做法）。
        #
        # 这是分层防御的第一层；后续闸在 ``_upload_helpers.py`` 的模块 docstring
        # 中详细枚举（per-file cap / per-request cap / magic-number 验证）。
        # ==================================================================
        self.app.config["MAX_CONTENT_LENGTH"] = MAX_TOTAL_UPLOAD_BYTES + 1024 * 1024

        # OpenAPI / Swagger 文档（访问 /apidocs 查看交互式 API 文档）
        # ------------------------------------------------------------------
        # R23.3：env-gated lazy init —— 默认完全跳过 flasgger 导入与 Swagger
        # 实例化，给 web_ui 子进程 cold start 省回 ~75 ms。
        #
        # why
        # - 实测 ``from flasgger import Swagger`` 在 macOS / Python 3.11 上
        #   是 74-78 ms 的同步成本（pulls in ``flasgger.base``、``jsonschema``
        #   验证器图、``mistune`` 渲染器、``yaml.SafeLoader`` 等），加上
        #   ``Swagger(app, template=...)`` 实例化又 ~0.5 ms。这 75 ms 全部
        #   阻塞在 web_ui 子进程的 main thread 上，直接出现在「AI agent 调
        #   ``interactive_feedback`` → 浏览器能打开页面」的用户感知延迟里
        #   （``service_manager.spawn_subprocess`` 的 ready-probe 必须等 web_ui
        #   listen socket bind 完成才会 return；flasgger import 在 listen 之前）。
        # - Swagger UI 是开发者调试工具，不是面向最终用户的功能 —— 在 GitHub
        #   issues 历史 + Discord 反馈里，没有任何普通用户提到访问 /apidocs/，
        #   只有少数几个项目维护者在 debug API 时会用。把它做成 opt-in 等于
        #   把 75 ms 的成本只让真正需要它的开发者付。
        # - opt-in 写法选用环境变量而不是 config.json 字段：(a) 子进程启动早于
        #   ``config_manager.get_config()`` 完成 schema 校验，env var 是最早可
        #   读的；(b) 12-factor 应用最佳实践把"是否启用调试端点"放在环境，
        #   不污染持久化配置；(c) 开发场景一行 ``AI_AGENT_ENABLE_SWAGGER=1
        #   uv run python web_ui.py ...`` 就能切回去，零仓库改动。
        # - 默认禁用时 ``/apidocs/`` 仍然可访问，但返回一个轻量级 HTML 提示
        #   页面（< 2 KB，纯 inline，无 JS 依赖）解释如何启用，并链回 GitHub
        #   README 的 dev guide section —— 避免「访问得到 404 但不知道为啥」
        #   的认知摩擦，符合 OWASP "fail informatively, not silently" 准则。
        #
        # 启用条件：``AI_AGENT_ENABLE_SWAGGER`` 取值在 {"1", "true", "yes",
        # "on"}（大小写不敏感、首尾空白 strip）。其它值（含未设置 / 空串 /
        # "0" / "false"）一律视为禁用。这套布尔解析与 ``config_manager`` 里
        # 已有的 env-bool helper 行为一致，便于运维自动化脚本统一传参。
        self.app.config["SWAGGER"] = {
            "title": "AI Intervention Agent API",
            "version": get_project_version(),
            "description": "AI 交互反馈代理的 RESTful API，支持多任务管理、反馈提交、通知配置等功能。",
            "termsOfService": "",
            "specs_route": "/apidocs/",
        }
        if _is_swagger_enabled_via_env():
            self._init_swagger_lazy()
        else:
            self._register_swagger_disabled_fallback()

        # 记录当前实例（用于单任务模式热更新兜底）
        global _CURRENT_WEB_UI_INSTANCE
        _CURRENT_WEB_UI_INSTANCE = self

        # ==================================================================
        # Gzip 压缩配置
        # ==================================================================
        # 启用响应压缩，显著减少传输大小：
        # - CSS: ~85% 压缩率（232KB → ~35KB）
        # - JavaScript: ~70% 压缩率
        # - JSON: ~90% 压缩率（包括 Lottie 动画）
        #
        # 配置项：
        # - COMPRESS_MIMETYPES: 压缩的 MIME 类型
        # - COMPRESS_LEVEL: 压缩级别（1-9，6 为平衡点）
        # - COMPRESS_MIN_SIZE: 最小压缩阈值（500 字节以下不压缩）
        # ==================================================================
        self.app.config["COMPRESS_MIMETYPES"] = [
            "text/html",
            "text/css",
            "text/xml",
            "text/javascript",
            "application/json",
            "application/javascript",
            "application/x-javascript",
            "application/xml",
            "application/xml+rss",
            "image/svg+xml",
        ]
        self.app.config["COMPRESS_LEVEL"] = 6  # 压缩级别（平衡压缩率和 CPU）
        self.app.config["COMPRESS_MIN_SIZE"] = 500  # 小于 500 字节不压缩
        Compress(self.app)

        self.network_security_config = validate_network_security_config({})

        # R452: construction-time cold start now stays off the config_manager /
        # pydantic / task_queue / flask_limiter graph. Runtime hooks are installed
        # by the first request that needs them, while this lightweight limiter keeps
        # the long-standing ``self.limiter.limit/exempt`` route-decorator surface.
        self.limiter: WebUiLimiterProtocol = WebUiRateLimiter(
            app=self.app,
            default_limits=["60 per minute", "10 per second"],
            headers_enabled=True,
        )

        self.setup_security_headers()
        self.setup_markdown()
        self.setup_routes()

    def _ensure_base_config_runtime_hooks_registered(self) -> None:
        """Register config callbacks on first request that touches config."""
        if self._base_config_runtime_hooks_registered:
            return
        with self._base_config_runtime_hooks_lock:
            if self._base_config_runtime_hooks_registered:
                return
            _ensure_network_security_hot_reload_callback_registered()
            _ensure_config_changed_sse_callback_registered()
            self._base_config_runtime_hooks_registered = True

    def _ensure_task_queue_runtime_hooks_registered(self) -> None:
        """Register TaskQueue-touching config callbacks on task/config requests."""
        if self._task_queue_runtime_hooks_registered:
            return
        with self._task_queue_runtime_hooks_lock:
            if self._task_queue_runtime_hooks_registered:
                return
            _ensure_feedback_timeout_hot_reload_callback_registered()
            self._task_queue_runtime_hooks_registered = True

    def _init_swagger_lazy(self) -> None:
        """opt-in 路径：同步 import + 实例化 flasgger.Swagger（R23.3）。

        ``AI_AGENT_ENABLE_SWAGGER`` 真值时由 ``__init__`` 调用一次。``import``
        语句故意写在函数内部 —— 模块顶部不再 ``from flasgger import Swagger``，
        所以禁用路径上 ``flasgger`` 包的 75 ms 加载成本不会被触发；启用路径上
        每个进程依然只 import 一次（Python ``sys.modules`` 缓存）。

        这里 import + 实例化串行同步执行；启用 Swagger 的开发者明确选择支
        付 75 ms 来换取 ``/apidocs/`` 可用，不需要再加 daemon thread 提速。
        """
        from flasgger import Swagger

        Swagger(
            self.app,
            template={
                "info": {
                    "title": "AI Intervention Agent API",
                    "version": get_project_version(),
                    "description": "AI 交互反馈代理的 RESTful API",
                    "contact": {"url": GITHUB_URL},
                    "license": {"name": "MIT"},
                },
                "basePath": "/",
                "schemes": ["http"],
                "tags": [
                    {
                        "name": "Tasks",
                        "description": "任务管理（创建、查询、激活、提交）",
                    },
                    {"name": "Feedback", "description": "反馈提交与查询"},
                    {"name": "Notification", "description": "通知配置与测试"},
                    {"name": "System", "description": "系统状态与配置"},
                ],
            },
        )

    def _register_swagger_disabled_fallback(self) -> None:
        """禁用路径：注册轻量级 ``/apidocs/`` 路由返回 HTML 提示页（R23.3）。

        why：访问 ``/apidocs/`` 拿到 404 时，开发者的第一反应是「我哪里配错
        了」，会去翻 README / 提 issue。返回一个 200 + 内嵌 HTML 的提示页
        让"为什么文档没了"在第一时间被解释清楚，并指向 GitHub README 的
        启用方式 —— 符合 OWASP "fail informatively, not silently" 准则。

        页面纯 inline（< 2 KB，无 JS / 无外链 CSS），所以即使下游 CSP 把
        ``script-src`` / ``style-src`` 锁得很紧也能正常显示；模板里的
        ``{github_url}`` 在模块加载时就替换为 ``GITHUB_URL`` 常量，运行
        时无 f-string 解析开销。
        """
        rendered = _SWAGGER_DISABLED_FALLBACK_HTML.format(github_url=GITHUB_URL)

        def _swagger_disabled_view() -> ResponseReturnValue:
            return rendered, 200, {"Content-Type": "text/html; charset=utf-8"}

        # 与 flasgger 启用时注册的 ``/apidocs/`` 路由路径保持一致，方便
        # docs 链接跨启用 / 禁用模式都用同一个 URL。
        self.app.add_url_rule(
            "/apidocs/",
            endpoint="swagger_disabled_apidocs",
            view_func=_swagger_disabled_view,
            methods=["GET"],
        )
        self.app.add_url_rule(
            "/apidocs",
            endpoint="swagger_disabled_apidocs_no_slash",
            view_func=_swagger_disabled_view,
            methods=["GET"],
        )

    def setup_markdown(self) -> None:
        """设置Markdown渲染器和扩展

        功能说明：
            初始化Python-Markdown实例，配置渲染扩展和代码高亮样式。

        启用的扩展：
            - fenced_code：围栏代码块（```语法）
            - codehilite：代码语法高亮（基于Pygments）
            - tables：表格支持（GFM风格）
            - toc：自动生成目录
            - nl2br：换行符转<br>标签
            - attr_list：元素属性语法
            - def_list：定义列表
            - abbr：缩写词
            - footnotes：脚注支持
            - md_in_html：HTML中嵌入Markdown

        代码高亮配置：
            - css_class: highlight（用于CSS样式）
            - use_pygments: True（使用Pygments进行语法高亮）
            - noclasses: True（内联样式，无需外部CSS）
            - pygments_style: monokai（Monokai配色方案）
            - guess_lang: True（自动检测代码语言）
            - linenums: False（禁用行号）

        副作用：
            - 创建 ``self._md_lock``（线程安全锁）+ ``self._md_cache``（LRU 缓存）
            - **不**立即创建 ``self.md`` 实例——见 R26.3 lazy-init 注释

        R26.3 lazy-init 行为：
            - ``self.md`` 初始化为 ``None`` sentinel（类型是 ``Any``，因为 ``markdown``
              不在模块级 import）
            - 真正的 ``markdown.Markdown(extensions=..., extension_configs=...)``
              实例化推迟到首次 ``render_markdown(text)`` 调用
            - ``self._md_lock`` 守住双重检查 lazy-init 的 race：第一个进入临界区的
              线程负责构造 ``self.md``，后续线程看到非 None 直接走 reset/convert 流程
            - 单元测试如果想直接访问 ``self.ui.md.convert``，必须先调用一次
              ``render_markdown(...)`` 触发懒初始化（已有测试 ``tests/test_render_markdown_cache.py``
              都符合这条调用顺序，无需改测试）

        注意事项：
            - Pygments需要额外安装（pip install pygments）
            - 内联样式会增加HTML体积，但避免CSP问题
            - 扩展顺序可能影响渲染结果
        """
        self._md_lock = threading.Lock()
        self.md: Any = None
        # P0 / R20.7：``/api/config`` 是被 VSCode webview + 浏览器 web UI 每 ~2-30s
        # 反复轮询的 hot path，handler 中的 ``render_markdown(active_task.prompt)``
        # 是 ~5-20 ms 的 CPU 密集型路径（codehilite Pygments + footnote AST + LaTeX
        # 扫描 + nl2br rewrite 等 10+ 扩展）。但 prompt 在同一个 task 生命周期内
        # **不会变**（除非 ``/api/update`` 显式改写或新 task 接管 active），所以
        # 同一个文本会被重新解析几十到几百次。
        #
        # 缓存策略：以完整 prompt 字符串为 key，渲染后的 HTML 为 value，dict 配合
        # 插入顺序当 LRU。容量 16 = 远大于 ``max_tasks=10``，在合理使用场景下能
        # 同时缓存所有 active + pending 任务的渲染结果，命中率应接近 100%。
        # 共享 ``_md_lock``：避免在 ``self.md.reset() / convert()`` 期间又有
        # 线程穿越 cache miss 路径触发并发 reset/convert（``markdown.Markdown``
        # 实例**非线程安全**，不能并发 convert）。
        self._md_cache: dict[str, str] = {}
        self._md_cache_capacity: int = 16

    def render_markdown(self, text: str) -> str:
        """渲染Markdown文本为HTML

        功能说明：
            将Markdown格式的文本转换为HTML，应用代码高亮、表格、LaTeX等扩展。
            **R20.7：附带 LRU 缓存**——同一 ``text`` 重复调用直接命中 cache。

        参数说明：
            text: Markdown格式的文本字符串（支持GFM风格）

        返回值：
            str: 渲染后的HTML字符串（已应用语法高亮和格式化）

        处理流程：
            1. 检查文本是否为空
            2. **缓存查表**：命中则 LRU touch（pop + 重新插入末尾）后直接返回
            3. **缓存未命中**：重置 Markdown 实例 → convert → 写入 cache
               （超过容量时 evict 最旧条目）

        缓存语义
        --------
        - **key**：完整 prompt 字符串（避免 hash 冲突；prompt 长度受
          ``PROMPT_MAX_LENGTH`` 上限保护，R166 起单条最多 ~100KB）。
        - **value**：渲染后的 HTML 字符串。
        - **容量**：16 条（远大于 ``max_tasks=10``，合理场景命中率 ~100%）。
        - **LRU 实现**：``dict`` 插入顺序保证（Python 3.7+），命中时
          ``pop`` + 重新插入把热条目移到末尾，逐出时
          ``next(iter(...))`` 是最旧的 key。

        线程安全
        --------
        - 共享 ``self._md_lock``：``markdown.Markdown`` 实例非线程安全，
          ``reset() + convert()`` 必须串行执行；缓存读写也在同一锁内，
          避免 cache write 与 markdown convert race。
        - 没用 ``RLock`` 因为方法内部不会递归 acquire 自己。

        注意事项：
            - 空文本返回空字符串（避免None错误）
            - HTML未进行额外的XSS过滤，依赖Markdown库的安全性
            - cache 不在 ``/api/update`` 时显式失效——新 prompt 会作为新 key
              进入 cache，旧 key 自然 LRU evict，简化逻辑且无正确性问题。
        """
        if not text:
            return ""
        with self._md_lock:
            # R26.3: lazy-init ``markdown.Markdown(...)`` 实例。
            # 临界区已经持有 ``self._md_lock``，所以这是个标准的「单次初始化」
            # pattern——即使 N 个线程同时跑到这里，第一个进入锁的线程构造实例，
            # 后续线程看到 ``self.md is not None`` 直接跳过初始化 block。
            # ``import markdown`` 也在此处下沉，sys.modules 缓存让重复 import
            # 是 ~50 ns 的字典查询，不是真的重新解析模块。
            if self.md is None:
                import markdown

                self.md = markdown.Markdown(
                    extensions=_MD_EXTENSIONS,
                    extension_configs=_MD_EXTENSION_CONFIGS,
                )

            cached = self._md_cache.get(text)
            if cached is not None:
                # LRU touch：把命中条目移到末尾（最近使用）
                self._md_cache.pop(text)
                self._md_cache[text] = cached
                return cached

            self.md.reset()
            html = str(self.md.convert(text))

            # 写入 cache（超容量时逐出最旧条目）
            if len(self._md_cache) >= self._md_cache_capacity:
                # ``dict`` 保证插入顺序，``next(iter(...))`` 是最旧 key
                oldest_key = next(iter(self._md_cache))
                self._md_cache.pop(oldest_key, None)
            self._md_cache[text] = html
            return html

    def setup_routes(self) -> None:
        """注册所有API路由和静态资源路由

        功能说明：
            注册Flask路由处理器，包括主页面、API端点、静态资源服务。

        路由分类：
            **页面路由**：
                - GET / - 主页面HTML

            **任务管理API**：
                - GET  /api/config              - 获取当前任务配置
                - GET  /api/tasks               - 获取所有任务列表
                - POST /api/tasks               - 创建新任务
                - GET  /api/tasks/<id>          - 获取单个任务详情
                - POST /api/tasks/<id>/activate - 激活指定任务
                - POST /api/tasks/<id>/submit   - 提交任务反馈

            **反馈API**：
                - POST /api/submit              - 提交反馈（通用端点）
                - POST /api/update              - 更新页面内容
                - GET  /api/feedback            - 获取反馈结果

            **系统API**：
                - GET  /api/health              - 健康检查
                - POST /api/close               - 关闭服务器

            **通知API**：
                - POST /api/test-bark                - 测试Bark通知
                - POST /api/notify-new-tasks         - 新任务 Bark 触发（兼容第三方外部调用；内部 UI 不再调用，由 MCP 主进程统一推送）
                - POST /api/update-notification-config - 更新通知配置
                - GET  /api/get-notification-config  - 获取通知配置

            **静态资源**：
                - /static/css/<filename>        - CSS文件
                - /static/js/<filename>         - JavaScript文件
                - /fonts/<filename>             - 字体文件
                - /icons/<filename>             - 图标文件
                - /sounds/<filename>            - 音频文件
                - /favicon.ico                  - 网站图标

        频率限制：
            - 默认：60次/分钟，10次/秒（全局）
            - /api/config：300次/分钟（轮询高频场景）
            - /api/tasks（GET）：300次/分钟（轮询高频场景）
            - /api/submit：60次/分钟（防止恶意提交）
            - /api/tasks（POST）：60次/分钟（防止任务创建滥用）

        注意事项：
            - 所有路由处理器定义为内部函数，通过闭包访问self
            - limiter装饰器需要放在路由装饰器之后
            - 静态资源路由使用send_from_directory安全地提供文件
        """

        @self.app.before_request
        def _ensure_task_queue_hooks_for_task_requests() -> None:
            if request.path == "/api/config":
                self._ensure_task_queue_runtime_hooks_registered()

        @self.app.route("/")
        def index() -> ResponseReturnValue:
            """主页面路由：通过 Jinja2 原生渲染 web_ui.html 模板。"""
            return render_template("web_ui.html", **self._get_template_context())

        @self.app.route("/api/config")
        @self.limiter.limit("300 per minute")
        def get_api_config() -> ResponseReturnValue:
            """获取当前激活任务的配置信息
            ---
            tags:
              - System
            responses:
              200:
                description: 当前任务配置
                schema:
                  type: object
                  properties:
                    prompt:
                      type: string
                      description: 提示文本（Markdown 原文）
                    prompt_html:
                      type: string
                      description: 渲染后的 HTML
                    predefined_options:
                      type: array
                      items:
                        type: string
                      description: 预定义选项列表
                    predefined_options_defaults:
                      type: array
                      items:
                        type: boolean
                      description: 与 predefined_options 按位置对应的默认勾选状态
                    task_id:
                      type: string
                    auto_resubmit_timeout:
                      type: number
                      description: 超时时间（秒）
                    has_content:
                      type: boolean
                    initial_empty:
                      type: boolean
              500:
                description: 服务器内部错误
            """
            try:
                # 从 TOML 配置读取语言设置，随每次响应返回给前端（插件/Web 通用）
                try:
                    ui_lang = get_config().get_section("web_ui").get("language", "auto")
                except Exception:
                    ui_lang = "auto"

                # 优先从 TaskQueue 获取激活任务
                task_queue = get_task_queue()
                active_task = task_queue.get_active_task()

                if active_task:
                    # 使用TaskQueue中的激活任务
                    # 返回剩余时间而非固定超时，解决刷新页面后倒计时重置的问题
                    # 【优化】添加 server_time 和 deadline，让前端可以基于服务器时间计算倒计时
                    now_monotonic = time.monotonic()
                    remaining_time = _task_remaining_time(active_task, now_monotonic)
                    server_time = time.time()
                    return jsonify(
                        {
                            "prompt": active_task.prompt,
                            "prompt_html": self.render_markdown(active_task.prompt),
                            "predefined_options": active_task.predefined_options,
                            "predefined_options_defaults": (
                                _task_predefined_options_defaults(active_task)
                            ),
                            "task_id": active_task.task_id,
                            "auto_resubmit_timeout": active_task.auto_resubmit_timeout,
                            "remaining_time": remaining_time,
                            "server_time": server_time,
                            "deadline": active_task.created_at.timestamp()
                            + active_task.auto_resubmit_timeout,
                            "language": ui_lang,
                            "persistent": True,
                            "has_content": True,
                            "initial_empty": False,
                            # R691（TODO#5 跨端一致性）：/api/config 补齐三个
                            # 任务级字段。此前仅 /api/tasks/<id> 返回，导致
                            # 依赖本端点的 VSCode webview 拿不到 per-task
                            # placeholder / yesno / header chip 信息。
                            # getattr 兜底：路由历史上兼容 duck-typed
                            # task（部分单测用 SimpleNamespace 构造），真实
                            # Task 模型始终携带这三个字段。
                            "feedback_placeholder": getattr(
                                active_task, "feedback_placeholder", None
                            ),
                            "question_type": getattr(
                                active_task, "question_type", None
                            ),
                            "header_label": getattr(active_task, "header_label", None),
                        }
                    )
                else:
                    # 如果没有激活任务，检查是否有 pending 任务
                    first_task = task_queue.get_first_incomplete_task()
                    if first_task is not None:
                        # 有未完成任务存在，激活第一个
                        task_queue.set_active_task(first_task.task_id)
                        logger.info(f"自动激活第一个pending任务: {first_task.task_id}")

                        # 【优化】添加 server_time 和 deadline，让前端可以基于服务器时间计算倒计时
                        now_monotonic = time.monotonic()
                        remaining_time = _task_remaining_time(first_task, now_monotonic)
                        server_time = time.time()
                        return jsonify(
                            {
                                "prompt": first_task.prompt,
                                "prompt_html": self.render_markdown(first_task.prompt),
                                "predefined_options": first_task.predefined_options,
                                "predefined_options_defaults": (
                                    _task_predefined_options_defaults(first_task)
                                ),
                                "task_id": first_task.task_id,
                                "auto_resubmit_timeout": first_task.auto_resubmit_timeout,
                                "remaining_time": remaining_time,
                                "server_time": server_time,
                                "deadline": first_task.created_at.timestamp()
                                + first_task.auto_resubmit_timeout,
                                "language": ui_lang,
                                "persistent": True,
                                "has_content": True,
                                "initial_empty": False,
                                # R691：同 active-task 分支，补齐任务级字段
                                "feedback_placeholder": getattr(
                                    first_task, "feedback_placeholder", None
                                ),
                                "question_type": getattr(
                                    first_task, "question_type", None
                                ),
                                "header_label": getattr(
                                    first_task, "header_label", None
                                ),
                            }
                        )
                    elif task_queue.has_tasks():
                        # 所有任务都是 completed 状态，显示无有效内容
                        logger.info("所有任务均已完成，显示无有效内容页面")
                        return jsonify(
                            {
                                "prompt": "",
                                "prompt_html": "",
                                "predefined_options": [],
                                "predefined_options_defaults": [],
                                "task_id": None,
                                "auto_resubmit_timeout": 0,
                                "language": ui_lang,
                                "persistent": True,
                                "has_content": False,
                                "initial_empty": False,
                            }
                        )

                    # 回退到旧的单任务模式
                    # 单任务模式没有创建时间，remaining_time 等于 auto_resubmit_timeout
                    # 【热更新增强】若未显式指定 timeout，则使用配置文件的默认值（运行中修改可立即生效）
                    timeout_explicit = bool(
                        getattr(self, "_single_task_timeout_explicit", True)
                    )
                    with self._state_lock:
                        effective_timeout = int(self.current_auto_resubmit_timeout)
                        prompt_snapshot = str(self.current_prompt)
                        options_snapshot = list(self.current_options)
                        current_options_defaults = getattr(
                            self,
                            "current_options_defaults",
                            _MISSING_OPTION_DEFAULTS,
                        )
                        option_defaults_snapshot = (
                            []
                            if current_options_defaults is _MISSING_OPTION_DEFAULTS
                            else list(cast("Any", current_options_defaults))
                        )
                        task_id_snapshot = self.current_task_id
                        has_content_snapshot = bool(self.has_content)
                        initial_empty_snapshot = bool(self.initial_empty)

                    if not timeout_explicit:
                        try:
                            effective_timeout = (
                                _get_default_auto_resubmit_timeout_from_config()
                            )
                        except Exception:
                            # 配置读取失败不影响主流程，沿用当前值
                            pass
                        with self._state_lock:
                            # 保持实例状态同步，便于其他逻辑复用
                            self.current_auto_resubmit_timeout = effective_timeout

                    prompt_html = ""
                    if has_content_snapshot:
                        try:
                            prompt_html = self.render_markdown(prompt_snapshot)
                        except Exception as e:
                            logger.warning(
                                f"/api/config prompt 渲染失败: {e}", exc_info=True
                            )
                            prompt_html = ""
                    return jsonify(
                        {
                            "prompt": prompt_snapshot,
                            "prompt_html": prompt_html,
                            "predefined_options": options_snapshot,
                            "predefined_options_defaults": option_defaults_snapshot,
                            "task_id": task_id_snapshot,
                            "auto_resubmit_timeout": effective_timeout,
                            "remaining_time": effective_timeout,
                            "language": ui_lang,
                            "persistent": True,
                            "has_content": has_content_snapshot,
                            "initial_empty": initial_empty_snapshot,
                        }
                    )
            except Exception as e:
                logger.error(f"获取配置失败: {e}", exc_info=True)
                # 返回安全的默认响应
                return jsonify(
                    {
                        "prompt": "",
                        "prompt_html": "",
                        "predefined_options": [],
                        "predefined_options_defaults": [],
                        "task_id": None,
                        "auto_resubmit_timeout": 0,
                        "language": "auto",
                        "persistent": True,
                        "has_content": False,
                        "initial_empty": True,
                    }
                ), 500

        @self.app.route("/api/close", methods=["POST"])
        def close_interface() -> ResponseReturnValue:
            """优雅关闭 Flask 服务器
            ---
            tags:
              - System
            responses:
              200:
                description: 关闭指令已接受
                schema:
                  type: object
                  properties:
                    status:
                      type: string
                      example: success
                    message:
                      type: string
            """
            # 关闭计时器**故意**保持 non-daemon（threading.Timer 默认即 non-daemon）：
            # 我们要先把 200 OK 返回给前端，再走 0.5s 延迟去 ``os.kill(SIGINT)`` 优雅
            # 关停 Flask。如果改成 daemon=True，Python 解释器在主线程结束瞬间会立刻
            # 杀掉计时器线程，``shutdown_server`` 可能根本没机会执行 → 出现"前端
            # 收到 success 但服务一直未关"的悬挂状态。non-daemon 让进程**等到**
            # 计时器跑完再退，这是优雅停机契约的关键一环。
            threading.Timer(0.5, self.shutdown_server).start()
            return jsonify({"status": "success", "message": msg("server.shuttingDown")})

        @self.app.route("/api/health", methods=["GET"])
        def health_check() -> ResponseReturnValue:
            """健康检查端点
            ---
            tags:
              - System
            responses:
              200:
                description: 服务正常运行
                schema:
                  type: object
                  properties:
                    status:
                      type: string
                      example: ok
            """
            return jsonify({"status": "ok"})

        @self.app.route("/api/capabilities", methods=["GET"])
        def capabilities() -> ResponseReturnValue:
            """返回服务器协议版本 / 声明的 features / build_id。

            前端在连接早期调用本端点，用于：
            - 依据 `protocol_version` 决定是否需要兼容模式或提示升级
            - 依据 `features` 决定是否启用某个 UI 入口

            `server_version` 来自 pyproject.toml；`build_id` 若可得则为 git short SHA。
            详见 `protocol.py`。
            ---
            tags:
              - System
            responses:
              200:
                description: 能力声明
                schema:
                  type: object
                  properties:
                    protocol_version:
                      type: string
                      example: "1.0.0"
                    server_version:
                      type: string
                      example: "1.5.18"
                    build_id:
                      type: string
                      example: ""
                    features:
                      type: object
            """
            build_id = os.environ.get("AIIA_BUILD_ID", "")
            return jsonify(get_capabilities(get_project_version(), build_id=build_id))

        @self.app.route("/api/time", methods=["GET"])
        def server_time() -> ResponseReturnValue:
            """返回服务器实时时钟与单调时钟（毫秒）。

            客户端用于 wall clock 对齐，避免前后端时间漂移导致 TTL / 动画错乱。
            详见 `protocol.py::get_server_clock`。
            ---
            tags:
              - System
            responses:
              200:
                description: 服务器时钟
                schema:
                  type: object
                  properties:
                    time_ms:
                      type: integer
                    monotonic_ms:
                      type: integer
            """
            return jsonify(get_server_clock())

        @self.app.route("/api/update-language", methods=["POST"])
        @self.limiter.limit("30 per minute")
        def update_language() -> ResponseReturnValue:
            """更新界面语言配置并持久化到 config.toml"""
            try:
                data = request.json or {}
                lang = str(data.get("language", "auto")).strip()

                supported = ("auto", "en", "zh-CN", "zh-TW")
                if lang not in supported:
                    return jsonify(
                        {"status": "error", "message": f"不支持的语言: {lang}"}
                    ), 400

                config_mgr = get_config()
                config_mgr.update_section("web_ui", {"language": lang})

                return jsonify({"status": "success", "language": lang})
            except Exception as e:
                logger.error(f"更新语言配置失败: {e}", exc_info=True)
                return jsonify({"status": "error", "message": str(e)}), 500

        # 路由通过 Mixin 注册（各 Mixin 定义在 web_ui_routes/ 下）
        self._setup_task_routes()
        self._setup_feedback_routes()
        self._setup_notification_routes()
        self._setup_static_routes()
        self._setup_system_routes()

        # 模板缺失降级：返回简洁 HTML 错误页（无外部依赖）
        from jinja2 import TemplateNotFound

        @self.app.errorhandler(TemplateNotFound)
        def handle_template_not_found(
            exc: TemplateNotFound,
        ) -> ResponseReturnValue:
            logger.error("Jinja2 模板缺失: %s", exc)
            from markupsafe import escape

            return (
                '<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8">'
                "<title>模板文件未找到</title></head><body>"
                "<h1>模板文件未找到</h1>"
                f"<p>无法找到 {escape(str(exc))} 文件，请确保模板文件存在。</p>"
                "</body></html>",
                500,
            )

        # 全局异常处理：将 AIAgentError 统一转为标准 JSON 错误响应
        from ai_intervention_agent.exceptions import AIAgentError

        @self.app.errorhandler(AIAgentError)
        def handle_agent_error(exc: AIAgentError) -> ResponseReturnValue:
            status = 500
            if exc.code == "not_found":
                status = 404
            elif exc.code == "validation":
                status = 400
            elif exc.code == "timeout":
                status = 504
            body: dict[str, Any] = {"success": False, "error": str(exc)}
            if exc.code:
                body["code"] = exc.code
            logger.warning(
                f"AIAgentError ({exc.code}): {exc}",
                exc_info=(type(exc), exc, exc.__traceback__),
            )
            return jsonify(body), status

        # mining-cycle-4 §4.5 B.4 borrow #1 — pretty 404 page for
        # stale/broken UI navigation. 借鉴 mcp-feedback-enhanced PR #207
        # session-not-found UX。Plain Flask 404 confuses user (especially
        # after server restart or task TTL expiry); pretty page gives a
        # clear "task not found" message + Home link + i18n.
        #
        # 仅对 HTML 请求（``Accept: text/html``）生效；JSON API 路由
        # 走 AIAgentError("not_found") 已有的 JSON 路径。
        @self.app.errorhandler(404)
        def handle_404(exc: object) -> ResponseReturnValue:
            from flask import render_template
            from flask import request as _request

            wants_html = "text/html" in (_request.accept_mimetypes.best or "")
            if not wants_html:
                return jsonify({"success": False, "error": "not_found"}), 404
            try:
                return (
                    render_template(
                        "not_found.html",
                        request_path=_request.path,
                    ),
                    404,
                )
            except Exception:
                # fallback: 模板不存在或渲染失败 → 简洁 inline HTML
                from markupsafe import escape

                return (
                    '<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8">'
                    "<title>Task / page not found</title></head><body>"
                    "<h1>404 — page or task not found</h1>"
                    f"<p>Path: <code>{escape(_request.path)}</code></p>"
                    '<p><a href="/">Return to home</a></p>'
                    "</body></html>",
                    404,
                )

    def shutdown_server(self) -> None:
        """优雅关闭Flask服务器

        功能说明：
            向当前进程发送SIGINT信号，触发Flask服务器的优雅关闭流程。

        处理逻辑：
            1. 获取当前进程PID（os.getpid()）
            2. 发送SIGINT信号（os.kill()）
            3. Flask接收信号后执行关闭流程

        副作用：
            - 当前进程收到SIGINT信号
            - Flask服务器停止接受新请求
            - 等待现有请求处理完毕后退出

        注意事项：
            - SIGINT相当于Ctrl+C信号
            - 关闭是全局的，影响所有客户端连接
            - 适用于单次任务完成后的自动关闭场景
            - 多任务模式下应避免调用此方法
        """

        os.kill(os.getpid(), signal.SIGINT)

    def _get_template_context(self) -> dict[str, Any]:
        """构建 Jinja2 模板渲染上下文。

        返回 render_template('web_ui.html', **ctx) 所需的全部变量：
        csp_nonce / version / github_url / language / css_version /
        multi_task_version / theme_version / app_version / inline_locale_json。

        R20.12-B: 新增 ``inline_locale_json``（``str | None``）—— lang 非 ``auto`` 时
        是序列化好的 JSON 字符串，让 i18n 跳过 fetch；lang=auto 时是 ``None``，模板
        ``{% if inline_locale_json %}`` 会跳过注入。

        R26.2: 三处热路径优化：
        (1) ``_RTL_LANG_PREFIXES`` 提到模块级 frozenset，避免每次调用重新分配 12
            元素 tuple；frozenset 成员查询 O(1) 还顺手把 ``startswith(p + "-")``
            的 12 次 prefix 比较换成更便宜的「split prefix on hyphen + 集合查询」。
        (2) ``static_dir`` 在 ``__init__`` 里算一次存到 ``self._static_dir``，
            避免每次 ``_get_template_context`` 都跑一次 ``Path(__file__).resolve()``
            （含 syscall）。
        (3) 4 次 ``_get_file_version(static_dir/...)`` 调用换成 module-level
            ``_compute_file_version(str(path))`` 自由函数 + ``@lru_cache``，按
            文件路径字符串缓存 stat 结果——进程级缓存命中后零 syscall。
        """
        try:
            ui_lang = get_config().get_section("web_ui").get("language", "auto")
        except Exception:
            ui_lang = "auto"

        # HTML 根 lang 属性："auto" 时退化为 "en"（客户端 i18n 会在 DOM 上再改 <html lang>）。
        # 必须是有效 BCP-47 tag，避免 <html lang="auto"> 导致屏幕阅读器判断错乱。
        html_lang = ui_lang if ui_lang in ("en", "zh-CN") else "en"

        # HTML 根 dir 属性：用 R26.2 的模块级 frozenset 做 O(1) 成员查询。
        # 取 ``html_lang`` 的 BCP-47 主语言子标签（hyphen 之前的部分），与 RTL
        # 语言集合做单次 ``in`` 查询——比原来 12 次 ``startswith(p + "-") or == p``
        # 比较快一个数量级。
        primary_subtag = html_lang.lower().partition("-")[0]
        html_dir = "rtl" if primary_subtag in _RTL_LANG_PREFIXES else "ltr"

        # R26.2: 优先用 ``__init__`` 填好的 ``self._static_dir``（避免 syscall），
        # 退回到模块级 lru_cache 兜底（``object.__new__(WebFeedbackUI)`` 测试场景）
        static_dir = getattr(self, "_static_dir", None) or _get_module_static_dir()

        # R20.12-B: 当后端已经知道首屏语言（非 ``auto``）时，把对应 locale JSON 内联进 HTML，
        # 让 ``i18n.init()`` 跳过一次 ``fetch /static/locales/<lang>.json``（11 KB / 30-80 ms RTT）。
        # ``auto`` 模式时浏览器要先探测 ``navigator.language`` 才能决定下载哪个 locale，
        # server 没法预知，故仅在显式设置语言时启用。
        inline_locale_json: str | None = None
        if ui_lang in ("en", "zh-CN"):
            locale_path = static_dir / "locales" / f"{ui_lang}.json"
            inline_locale_json = _read_inline_locale_json(str(locale_path))

        return {
            "csp_nonce": self._get_csp_nonce(),
            "version": get_project_version(),
            "github_url": GITHUB_URL,
            "language": ui_lang,
            "html_lang": html_lang,
            "html_dir": html_dir,
            "css_version": _compute_file_version(str(static_dir / "css" / "main.css")),
            "multi_task_version": _compute_file_version(
                str(static_dir / "js" / "multi_task.js")
            ),
            "theme_version": _compute_file_version(str(static_dir / "js" / "theme.js")),
            "app_version": _compute_file_version(str(static_dir / "js" / "app.js")),
            "prism_css_version": _compute_file_version(
                str(static_dir / "css" / "prism.css")
            ),
            "tri_state_panel_css_version": _compute_file_version(
                str(static_dir / "css" / "tri-state-panel.css")
            ),
            "mathjax_loader_version": _compute_file_version(
                str(static_dir / "js" / "mathjax-loader.js")
            ),
            "validation_utils_version": _compute_file_version(
                str(static_dir / "js" / "validation-utils.js")
            ),
            "keyboard_shortcuts_version": _compute_file_version(
                str(static_dir / "js" / "keyboard-shortcuts.js")
            ),
            "dom_security_version": _compute_file_version(
                str(static_dir / "js" / "dom-security.js")
            ),
            "notification_manager_version": _compute_file_version(
                str(static_dir / "js" / "notification-manager.js")
            ),
            "settings_manager_version": _compute_file_version(
                str(static_dir / "js" / "settings-manager.js")
            ),
            "image_upload_version": _compute_file_version(
                str(static_dir / "js" / "image-upload.js")
            ),
            "tri_state_panel_version": _compute_file_version(
                str(static_dir / "js" / "tri-state-panel.js")
            ),
            "tri_state_panel_loader_version": _compute_file_version(
                str(static_dir / "js" / "tri-state-panel-loader.js")
            ),
            "tri_state_panel_bootstrap_version": _compute_file_version(
                str(static_dir / "js" / "tri-state-panel-bootstrap.js")
            ),
            "lottie_min_version": _compute_file_version(
                str(static_dir / "js" / "lottie.min.js")
            ),
            "locale_versions": {
                "en": _compute_file_version(str(static_dir / "locales" / "en.json")),
                "zh-CN": _compute_file_version(
                    str(static_dir / "locales" / "zh-CN.json")
                ),
                "zh-TW": _compute_file_version(
                    str(static_dir / "locales" / "zh-TW.json")
                ),
                "pseudo": _compute_file_version(
                    str(static_dir / "locales" / "_pseudo" / "pseudo.json")
                ),
            },
            # R27.2: 给 i18n.js / state.js / marked.js / prism.min.js 也加上版本号查询
            # 串，模板中下游 ``<link rel="preload">`` 与 ``<script defer>`` 一起统一带
            # ``?v={{ ... }}``，从 ``serve_js`` 的 ``Cache-Control: public, max-age=3600``
            # （1 小时短缓存）升级到 ``public, max-age=31536000, immutable``（1 年永久
            # 缓存），重复打开 web_ui 不再走 304 revalidation 往返。每个 ``_compute_file_version``
            # 调用是 ``Path.stat()`` + ``str`` 截取，命中率 100% 的 ``lru_cache(maxsize=64)``
            # 加持下 4 次新增成本 < 1 µs。
            "i18n_js_version": _compute_file_version(
                str(static_dir / "js" / "i18n.js")
            ),
            "state_js_version": _compute_file_version(
                str(static_dir / "js" / "state.js")
            ),
            "marked_js_version": _compute_file_version(
                str(static_dir / "js" / "marked.js")
            ),
            "prism_min_js_version": _compute_file_version(
                str(static_dir / "js" / "prism.min.js")
            ),
            "quick_phrases_version": _compute_file_version(
                str(static_dir / "js" / "quick_phrases.js")
            ),
            # R137: feedback textarea 高度持久化模块版本号
            "feedback_textarea_height_version": _compute_file_version(
                str(static_dir / "js" / "feedback_textarea_height.js")
            ),
            # R138: feedback 字符计数器模块版本号
            "feedback_char_counter_version": _compute_file_version(
                str(static_dir / "js" / "feedback_char_counter.js")
            ),
            # R139: feedback per-task 草稿持久化模块版本号
            "feedback_drafts_version": _compute_file_version(
                str(static_dir / "js" / "feedback_drafts.js")
            ),
            # R248 / mining-8 Track A: iOS Safari A2HS hint banner 模块版本号
            "ios_a2hs_hint_version": _compute_file_version(
                str(static_dir / "js" / "ios_a2hs_hint.js")
            ),
            # R140: feedback 提交模式切换模块版本号
            "feedback_submit_mode_version": _compute_file_version(
                str(static_dir / "js" / "feedback_submit_mode.js")
            ),
            # R144: 快捷键 cheatsheet overlay 模块版本号
            "keyboard_shortcut_help_version": _compute_file_version(
                str(static_dir / "js" / "keyboard_shortcut_help.js")
            ),
            # ``notification_test_button_version`` / ``activity_dashboard_version``
            # 已随 feat-remove-test 移除：用户不再使用设置页的"发送系统自检通知"
            # 与"活动面板"两个 UI 入口，对应 JS 模块也已经删除。
            # 后端 ``/api/system/notifications/test``、``/api/system/health``、
            # ``/api/system/sse-stats``、``/api/system/recent-logs`` API 保留供
            # CI / 监控脚本独立调用。
            "inline_locale_json": inline_locale_json,
        }

    def update_content(
        self,
        new_prompt: str,
        new_options: list[str] | None = None,
        new_task_id: str | None = None,
    ) -> None:
        """更新页面内容（单任务模式，实例方法）

        功能说明：
            更新当前任务的prompt、选项、任务ID，用于单任务模式下的内容动态更新。

        参数说明：
            new_prompt: 新的提示文本（Markdown格式）
            new_options: 新的预定义选项列表（可选，默认为空列表）
            new_task_id: 新的任务ID（可选）

        处理逻辑：
            1. 更新self.current_prompt
            2. 更新self.current_options（None转为空列表）
            3. 更新self.current_task_id
            4. 更新self.has_content标志
            5. 记录日志（INFO级别）

        副作用：
            - 修改self.current_prompt、current_options、current_task_id
            - 更新self.has_content标志
            - 记录日志到enhanced_logging

        注意事项：
            - 仅更新实例属性，不修改self.feedback_result
            - 适用于单任务模式，多任务模式请使用TaskQueue API
            - 前端需通过/api/config轮询获取更新后的内容
        """
        with self._state_lock:
            self.current_prompt = new_prompt
            self.current_options = new_options if new_options is not None else []
            self.current_options_defaults = []
            self.current_task_id = new_task_id
            self.has_content = bool(new_prompt)
        if new_prompt:
            logger.info(f"内容已更新: {new_prompt[:50]}... (task_id: {new_task_id})")
        else:
            logger.info("内容已清空，显示无有效内容页面")

    _stale_minified_warned: set[str] = set()

    def _get_minified_file(
        self, directory: str | Path, filename: str, extension: str
    ) -> str:
        """获取压缩版本的文件名（如存在且新鲜）。

        功能说明
            自动检测并优先使用压缩版本的静态资源文件，但**仅在压缩
            版本不晚于源文件时才使用**——避免 R242 surfaced 的「修改
            源文件后, 浏览器仍看到旧 minified 代码」沉默 bug。

        参数说明
            directory: 文件所在目录的绝对路径
            filename: 原始请求的文件名
            extension: 文件扩展名（如 ".js" 或 ".css"）

        返回值
            str: 实际使用的文件名（压缩版本或原始版本）

        处理逻辑
            1. 如果请求的已是 ``.min.*`` 文件，直接返回（caller 是
               显式指名, 不做猜测）
            2. 检查对应的 ``.min.*`` 文件是否存在
            3. 如存在且 ``mtime(.min) >= mtime(source)`` → 用压缩版本
            4. 如存在但 stale（``mtime(.min) < mtime(source)``） →
               降级到源文件 + WARN 一次（防止刷屏，按文件名 dedupe）
            5. 不存在 → 直接返回源文件名

        示例
            - 请求 ``multi_task.js``，若 ``multi_task.min.js`` 存在且新鲜
              → 返回 ``multi_task.min.js``
            - 请求 ``multi_task.js``，若 ``multi_task.min.js`` 存在但
              旧于源 → 返回 ``multi_task.js`` + log WARN
            - 请求 ``multi_task.min.js`` → 原样返回（caller 显式选了）
            - 请求 ``prism-xxx.js``（外部库, 没 .min.* counterpart）
              → 返回 ``prism-xxx.js``

        R243 / Cycle 16 · F-cycle16-staleness 防御链
            - R242 (pre-commit hook) 在 commit 时挡住产生 stale .min
            - R243 (本函数 mtime check) 在运行时挡住 serve stale .min
            - 两层 belt-and-suspenders: pre-commit 可被 ``--no-verify``
              绕过 / 历史 stale .min 未被 R242 commit 触及; 运行时检查
              覆盖这些缝隙。
            - 额外成本: 每请求多一次 ``stat()``（~10μs SSD）, 对 static
              资源 hot path 可接受（Flask ``send_from_directory`` 本身
              就 stat 多次）。
        """
        if f".min{extension}" in filename:
            return filename

        base_name = filename.replace(extension, "")
        minified_name = f"{base_name}.min{extension}"
        dir_path = Path(directory)
        minified_path = dir_path / minified_name
        source_path = dir_path / filename

        try:
            if not minified_path.exists():
                return filename
            min_mtime = minified_path.stat().st_mtime
            src_mtime = source_path.stat().st_mtime if source_path.exists() else 0.0
        except OSError:
            return filename

        if min_mtime < src_mtime:
            warn_key = str(minified_path)
            if warn_key not in self._stale_minified_warned:
                self._stale_minified_warned.add(warn_key)
                logger.warning(
                    "R243 stale minified asset: %s mtime=%.0f < source %s mtime=%.0f → "
                    "falling back to source. 修复: 运行 `uv run python "
                    "scripts/minify_assets.py` 重生 .min 文件。",
                    minified_path.name,
                    min_mtime,
                    filename,
                    src_mtime,
                )
            return filename

        return minified_name

    def _get_file_version(self, file_path: str | Path) -> str:
        """获取文件版本号（基于修改时间）。

        R26.2: 实际逻辑已经下沉到模块级 ``_compute_file_version`` 自由函数，配
        ``@lru_cache`` 做进程级缓存。本实例方法保留为向后兼容 API（被
        ``tests/test_web_ui_config.py`` 与历史调用方使用），转调到模块级实现。
        热路径 ``_get_template_context`` 直接调用 ``_compute_file_version`` 跳过
        额外的 self 绑定与方法解析开销。

        功能说明：
            根据文件的最后修改时间生成版本号，用于静态资源缓存控制。
            每次文件更新后**+ 重启 web_ui 进程**版本号会自动变化（lru_cache 仅
            在进程生命周期内缓存）。

        参数说明：
            file_path: 文件的完整路径

        返回值：
            str: 版本号（Unix 时间戳的后 8 位，确保唯一性）

        异常处理：
            - 文件不存在：返回默认版本号 "1"
        """
        return _compute_file_version(str(file_path))

    def run(self) -> FeedbackResult:
        """启动Flask Web服务器并等待用户反馈

        功能说明：
            启动Flask开发服务器，监听指定的host和port，等待用户提交反馈。

        返回值：
            FeedbackResult: 用户反馈结果，包含以下字段：
                - user_input: 用户输入文本
                - selected_options: 选中的选项数组
                - images: 图片数组（Base64编码）

        处理逻辑：
            1. 打印启动信息（访问URL、SSH端口转发命令等）
            2. 调用Flask的app.run()启动服务器
            3. 服务器运行直到收到SIGINT信号或调用shutdown_server()
            4. 返回self.feedback_result（若无反馈则返回空字典）

        启动参数：
            - host: self.host（默认"0.0.0.0"）
            - port: self.port（默认8080）
            - debug: False（禁用调试模式）
            - use_reloader: False（禁用自动重载）

        异常处理：
            - KeyboardInterrupt: 捕获Ctrl+C信号，正常退出

        副作用：
            - 阻塞当前线程，直到服务器关闭
            - 打印启动信息到标准输出

        注意事项：
            - 使用Flask开发服务器，不适合生产环境
            - 生产环境建议使用Gunicorn或uWSGI
            - 若self.feedback_result为None，返回空反馈字典
            - 服务器关闭后才返回，适用于单次任务模式
        """
        print("\nWeb反馈界面已启动")
        # 0.0.0.0 是“监听所有网卡”的服务端绑定地址，但并不适合作为浏览器访问地址。
        # 部分浏览器/环境访问 http://0.0.0.0:PORT 时可能出现异常（例如权限/请求失败）。
        if self.host == "0.0.0.0":
            print(f"监听地址: http://{self.host}:{self.port}")
            print(f"本机访问（推荐）: http://127.0.0.1:{self.port}")
            print(f"本机访问（推荐）: http://localhost:{self.port}")
            print(
                f"SSH端口转发命令: ssh -L {self.port}:localhost:{self.port} user@remote_server"
            )
        else:
            print(f"请在浏览器中打开: http://{self.host}:{self.port}")

        # R225 / Cycle 12: SSH / WSL 远程环境探测。当 host=127.0.0.1 时, 远程
        # 会话的本地浏览器**无法直接访问** 上面打印的 URL — 静默打印
        # "请在浏览器中打开 http://127.0.0.1:8080" 让用户白浪费几分钟排查
        # 网络问题。本块仅当真的检测到远程环境且 bind 是回环时才追加
        # 一句可操作提示, 不替换原有打印, 不改变实际行为。
        if self.host in ("127.0.0.1", "localhost"):
            env_info = detect_remote_environment()
            if env_info["is_ssh"]:
                print(
                    f"⚠ 检测到 SSH 会话 (source={env_info['ssh_source']}) "
                    "且 host=127.0.0.1。本地浏览器无法直接访问上面的 URL。"
                )
                print(
                    f"  方案 A (推荐): 在本地机器执行 "
                    f"`ssh -L {self.port}:127.0.0.1:{self.port} "
                    "user@remote_host` 后访问 "
                    f"http://localhost:{self.port}"
                )
                print(
                    "  方案 B: 重启时设置 "
                    "`AI_INTERVENTION_AGENT_WEB_UI_HOST=0.0.0.0` "
                    "(注意暴露给远程主机的所有网卡, 仅在已信任的网络下使用)"
                )
            elif env_info["is_wsl"]:
                print(
                    f"ℹ 检测到 WSL 环境 (source={env_info['wsl_source']})。"
                    "Windows 宿主机的浏览器一般可直接打开上面的 URL "
                    "(WSL2 自动 localhost 转发); WSL1 用户请改用 "
                    "`AI_INTERVENTION_AGENT_WEB_UI_HOST=0.0.0.0`。"
                )

        # mDNS 发布（默认：bind_interface 不是 127.0.0.1 时启用）
        # R20.11：异步发布以避免 zeroconf.register_service 的 ~1.7s mDNS conflict-probe
        # 阻塞 app.run() 进入 listen。后台 daemon 线程并行注册；_stop_mdns 会 join 线程。
        # 用户访问 http://127.0.0.1:port / http://<lan-ip>:port 不依赖 mDNS 名字解析，
        # 仅 LAN 上的其他设备使用 ai.local 时才会等 mDNS announcement 完成。
        self._mdns_thread = threading.Thread(
            target=self._start_mdns_if_needed,
            name="ai-agent-mdns-register",
            daemon=True,
        )
        self._mdns_thread.start()

        # R59：给 web_ui 子进程的**主线程**显式注册 SIGTERM handler。
        # ----------------------------------------------------------------
        # 默认情况下 Python 的 SIGTERM handler 是直接 SystemExit，bypass
        # ``app.run()`` 的 ``KeyboardInterrupt`` 捕获 → 我们的 ``finally``
        # 永远跑不到，``self._stop_mdns()`` 也就不执行：浏览器侧 SSE 长连
        # 接、mDNS announcement、werkzeug worker thread 都是被 OS 强行 close
        # 而非 graceful close。后果：
        # - LAN 上其它设备仍然把 ``ai.local`` 解析到这个已关闭的进程，要等
        #   下一次 mDNS TTL 过期才能感知；
        # - SSE generator 的 ``finally: bus.unsubscribe(q)`` 不跑 → 内存里
        #   残留的 queue 直到下次 emit 触发 backpressure 才被 GC。
        # 把 SIGTERM 翻译成 ``KeyboardInterrupt``，复用现成的 ``app.run()``
        # 退出路径走 ``finally: self._stop_mdns()``。仅在主线程注册，避免
        # 嵌套 ``ValueError: signal only works in main thread``。
        try:
            if threading.current_thread() is threading.main_thread() and hasattr(
                signal, "SIGTERM"
            ):

                def _term_to_keyboard_interrupt(signum: int, frame: object) -> None:
                    del frame
                    raise KeyboardInterrupt(
                        f"signal {signum} → graceful web_ui shutdown"
                    )

                signal.signal(signal.SIGTERM, _term_to_keyboard_interrupt)
        except (ValueError, OSError) as sig_exc:
            # Windows 不支持某些 signal；非主线程也可能抛 ValueError。
            # 静默跳过：默认 SIGTERM behaviour 仍然是 SystemExit，至少能退。
            logger.debug(f"无法注册 SIGTERM handler: {sig_exc}")

        print("🔄 页面将保持打开，可实时更新内容")
        print()

        try:
            try:
                self.app.run(
                    host=self.host, port=self.port, debug=False, use_reloader=False
                )
            except KeyboardInterrupt:
                pass
        finally:
            self._stop_mdns()

        empty_result: FeedbackResult = {
            "user_input": "",
            "selected_options": [],
            "images": [],
        }
        return self.feedback_result or empty_result


def web_feedback_ui(
    prompt: str,
    predefined_options: list[str] | None = None,
    task_id: str | None = None,
    auto_resubmit_timeout: int = AUTO_RESUBMIT_TIMEOUT_DEFAULT,
    output_file: str | None = None,
    host: str = "0.0.0.0",
    port: int = 8080,
    external_base_url: str = "",
    mdns_hostname: str = MDNS_DEFAULT_HOSTNAME,
    trusted_hosts: list[str] | None = None,
) -> FeedbackResult | None:
    """启动 Web UI（交互反馈界面）的便捷函数

    功能说明：
        创建 WebFeedbackUI 实例并启动服务，收集用户反馈。可选地将结果保存到文件。

    参数说明：
        prompt: 提示文本（Markdown 格式）
        predefined_options: 预定义选项列表（可选）
        task_id: 任务 ID（可选）
        auto_resubmit_timeout: 自动重调倒计时（秒，默认 240；范围 [10, 3600]；0=禁用）
        output_file: 输出文件路径（可选；若指定则将结果保存为 JSON 文件）
        host: 绑定主机地址（默认"0.0.0.0"）
        port: 绑定端口（默认8080）
        external_base_url: 反向代理或自定义域名的外部基地址（可选）
        mdns_hostname: mDNS 主机名（默认 ai.local）
        trusted_hosts: 额外允许的 Host 头（可选）

    返回值：
        FeedbackResult | None: 用户反馈结果字典，包含：
            - user_input: 用户输入文本
            - selected_options: 选中的选项数组
            - images: 图片数组（Base64编码）
        若指定output_file，则返回None（结果已保存到文件）

    处理逻辑：
        1. 创建WebFeedbackUI实例
        2. 调用ui.run()启动服务器并等待反馈
        3. 若指定output_file：
           - 确保输出目录存在
           - 将反馈结果保存为JSON文件（UTF-8编码，格式化缩进）
           - 返回None
        4. 否则直接返回反馈结果

    使用场景：
        - 命令行工具快速启动反馈界面
        - 自动化脚本收集用户输入
        - 测试和开发环境

    注意事项：
        - 服务器会阻塞当前线程，直到用户提交反馈或关闭服务器
        - output_file路径的父目录会被自动创建
        - JSON文件使用ensure_ascii=False保留中文字符
    """
    auto_resubmit_timeout = validate_auto_resubmit_timeout(int(auto_resubmit_timeout))
    ui = WebFeedbackUI(
        prompt,
        predefined_options,
        task_id,
        auto_resubmit_timeout,
        host,
        port,
        external_base_url,
        mdns_hostname,
        trusted_hosts,
    )
    result = ui.run()

    if output_file and result:
        # 确保目录存在
        output_path = Path(str(output_file)).expanduser()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        # 保存结果到输出文件
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        return None

    return result


if __name__ == "__main__":
    """主程序入口：命令行启动 Web UI（交互反馈界面）

    功能说明：
        解析命令行参数，启动 Web UI，并在用户提交后输出反馈结果。

    命令行参数：
        --prompt: 向用户展示的提示/问题（支持 Markdown，默认"我已经实现了您请求的更改。"）
        --predefined-options: 预定义选项列表（用 ||| 分隔）
        --task-id: 任务 ID（可选；主要用于调试/脚本集成）
        --auto-resubmit-timeout: 自动重调倒计时（秒，默认 240；范围 [10, 3600]；0=禁用）
        --output-file: 将反馈结果保存为 JSON 文件的路径
        --host: Web UI 监听地址（默认 "0.0.0.0"）
        --port: Web UI 监听端口（默认 8080）
        --external-base-url: 反向代理或自定义域名的外部基地址（可选）
        --mdns-hostname: mDNS 主机名（默认 ai.local）
        --trusted-hosts: 额外允许的 Host，逗号分隔

    执行流程：
        1. 创建ArgumentParser解析命令行参数
        2. 解析predefined_options（|||分隔符）
        3. 调用web_feedback_ui()启动服务器
        4. 打印反馈结果到标准输出
        5. 退出程序（sys.exit(0)）

    输出格式：
        收到反馈:
        选择的选项: option1, option2
        用户输入: <user text>
        包含 <N> 张图片

    注意事项：
        - 适用于命令行工具和自动化脚本
        - 服务器会阻塞直到用户提交反馈
        - 可通过Ctrl+C中断服务器
    """
    parser = argparse.ArgumentParser(description="运行 Web UI（交互反馈界面）")
    parser.add_argument(
        "--prompt",
        default="我已经实现了您请求的更改。",
        help="向用户展示的提示/问题（支持 Markdown）",
    )
    parser.add_argument(
        "--predefined-options",
        default="",
        help="预定义选项列表（用 ||| 分隔；为空表示无选项）",
    )
    parser.add_argument(
        "--task-id", default=None, help="任务 ID（可选；主要用于调试/脚本集成）"
    )
    parser.add_argument(
        "--auto-resubmit-timeout",
        type=int,
        default=AUTO_RESUBMIT_TIMEOUT_DEFAULT,
        help="自动重调倒计时（秒；0 表示禁用；范围 [10, 3600]，与 server_config.AUTO_RESUBMIT_TIMEOUT_MAX 对齐）",
    )
    parser.add_argument("--output-file", help="将反馈结果保存为 JSON 文件的路径")
    parser.add_argument("--host", default="0.0.0.0", help="Web UI 监听地址")
    parser.add_argument("--port", type=int, default=8080, help="Web UI 监听端口")
    parser.add_argument(
        "--external-base-url",
        default="",
        help="反向代理或自定义域名的外部基地址（可选）",
    )
    parser.add_argument(
        "--mdns-hostname",
        default=MDNS_DEFAULT_HOSTNAME,
        help="mDNS 主机名（默认 ai.local）",
    )
    parser.add_argument(
        "--trusted-hosts",
        default="",
        help="额外允许的 Host，逗号分隔（例如 ai.example.com,10.0.0.5）",
    )
    args = parser.parse_args()

    predefined_options = (
        [opt for opt in args.predefined_options.split("|||") if opt]
        if args.predefined_options
        else None
    )
    trusted_hosts = (
        [item.strip() for item in args.trusted_hosts.split(",") if item.strip()]
        if args.trusted_hosts
        else None
    )

    result = web_feedback_ui(
        prompt=args.prompt,
        predefined_options=predefined_options,
        task_id=args.task_id,
        auto_resubmit_timeout=args.auto_resubmit_timeout,
        output_file=args.output_file,
        host=args.host,
        port=args.port,
        external_base_url=args.external_base_url,
        mdns_hostname=args.mdns_hostname,
        trusted_hosts=trusted_hosts,
    )
    if result:
        user_input = result.get("user_input", "")
        selected_options = result.get("selected_options")
        if not isinstance(selected_options, list):
            selected_options = []
        images = result.get("images")
        if not isinstance(images, list):
            images = []

        print("\n收到反馈:")
        if selected_options:
            print(f"选择的选项: {', '.join(selected_options)}")
        if user_input:
            print(f"用户输入: {user_input}")
        if images:
            print(f"包含 {len(images)} 张图片")
    sys.exit(0)
