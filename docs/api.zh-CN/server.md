# server

> 英文 signature-only 版本（仅函数 / 类签名速查）：[`docs/api/server.md`](../api/server.md)

MCP 服务器核心 - interactive_feedback 工具、多任务队列、通知集成。

## 函数

### `_resolve_server_version() -> str`

读取已安装包版本号，失败时返回开发占位符。

通过 MCP initialize 协议暴露给 client，方便 client 做兼容判断 / 调试日志。

### `_resolve_build_info() -> dict[str, str]`

返回 ``{git_commit, git_branch, git_dirty}``，失败字段填 ``"unknown"``。

Thread-safe + lazy + 单次缓存：第一次拿到的结果在整个进程生命周期内不
会变（即使工作树后续被改了，cache 也不刷——这与 ``_PROCESS_STARTED_AT_UNIX``
的语义一致：「我跑起来时是哪个 commit」）。

返回 dict 是拷贝；调用方修改不影响 module-level cache。

### `reset_sse_stats_cache_for_testing() -> None`

R352 (cycle-39 #C2) · **Test-only**: 清空 ``_sse_stats_cache`` +
重置 timestamp, 让下次 ``_fetch_sse_stats_cached`` 重新拉取。

与 R352 其他 reset helper (build_info / feedback_counters) 同源 —
给 TTL-bound 进程级 cache 暴露测试隔离 API, 防止跨测试 cache 残留
污染断言。

### `reset_recent_logs_cache_for_testing() -> None`

R352 (cycle-39 #C2) · **Test-only**: 清空 ``_recent_logs_cache`` +
重置 timestamp, 让下次 ``_fetch_recent_logs_cached`` 重新拉取。

### `reset_build_info_cache_for_testing() -> None`

R352 (cycle-39 #C2) · **Test-only**: 清空 ``_BUILD_INFO_CACHE`` 让
下次 ``_resolve_build_info()`` 重新调用 git subprocess。

**为什么需要这个 helper?**

``_BUILD_INFO_CACHE`` 是 module-level 进程级单次缓存; 测试 mock 了
``subprocess.check_output`` 后, 如果 cache 已被填充过, mock 的返回值
不会被读取 (因为代码会 short-circuit 返回 cached dict)。这违反了
"测试可以重置全局状态" 的隔离原则。

与 R323 (NotificationManager) / R352 (FEEDBACK_COUNTERS) 同源 — 给
module-level cache 暴露显式 reset API。

**使用方式 (test)**::

    from ai_intervention_agent.server import (
        reset_build_info_cache_for_testing,
    )
    reset_build_info_cache_for_testing()
    # 现在 mock subprocess 后调用 _resolve_build_info() 才会真的走 mock

### `_build_server_icons() -> list[Icon]`

启动时一次性把本地 icons 转成 data URI，让 server icons 完全 self-contained。

设计取舍：
- 使用 base64 data URI 而不是 GitHub raw URL，避免对 main 分支 push 状态的依赖
  （已发布版本即使 main 上图标资源被删，client 仍能渲染图标）
- 多尺寸覆盖：32/192/512 + SVG，让 client UI 按显示密度自选
- 总开销 ~17KB（base64 化），仅在 initialize 一次性下发，可忽略
- 任何 icon 文件缺失时跳过，不影响 server 启动

### `get_mcp_error_stats() -> dict[str, int]`

返回 MCP 中间件累计的异常计数（``{error_type}:{method}`` → 次数）。

供运维 / 测试在不污染 server 进程的情况下抽样诊断热点异常路径。
返回的是副本，外部修改不会影响内部累加器。

### `_fetch_sse_stats_cached(host: str, port: int) -> dict[str, object]`

1.0s TTL 包装 GET /api/system/sse-stats（R54-A）。

返回值约定（永远是新建 dict，绝不返回内部缓存引用）：
- 成功：``{emit_total, latest_event_id, gap_warnings_emitted,
  backpressure_discards, subscriber_count, history_size}``，可能附
  ``cached: True`` 标志（命中 cache）；
- 失败：``{error: "<type>: <msg>"}`` 或 ``{error: "sse-stats HTTP 429"}``
  / ``{error: "sse-stats response not success: ..."}``。

线程安全：cache 的 read-modify-write 受单一 ``threading.Lock`` 保护；
实际网络调用（httpx.get）在锁外执行，避免一个慢请求阻塞所有 caller。

### `_fetch_recent_logs_cached(host: str, port: int, limit: int = 20) -> dict[str, object]`

1.0s TTL 包装 GET /api/system/recent-logs（R55）。

返回值约定：
- 成功：``{entries: list[dict], count: int}``，可能附 ``cached: True``；
- 失败：``{error: ...}``。永远是新建 dict。

注意 ``limit`` 进 cache key 一起：不同 limit 视作不同请求，避免一个
limit=20 的请求填了 cache 后，limit=50 命中误得到 truncated entries。

### `server_info_resource() -> dict[str, object]`

Return diagnostic self-information for this MCP server.

R44 增强（仍然 best-effort，每一个子段都被独立 try/except 包住）：

- ``runtime``：``python_version`` / ``python_executable`` / ``platform``，
  让运维诊断 "用 uv 还是 pipx 起的"、"哪个 interpreter"，无需 ssh 上去
  跑 ``which python``；
- ``fastmcp``：直接读 ``importlib.metadata`` 报本地装的 fastmcp 版本，
  跨 client 比对兼容性时用得上；
- ``middleware``：每个中间件的类名，按运行顺序排列。让 client 端能直
  观看到链路是否被外部 hook 改过，定位"为啥我没看到 timing 日志"这种
  问题；
- ``task_queue``：当前队列长度（best-effort，不实例化新单例），让
  client 一眼看到"是不是有积压任务没人处理"。

### `cleanup_services(shutdown_notification_manager: bool = True) -> None`

清理所有启动的服务进程

功能
----
获取全局 ServiceManager 实例并调用 cleanup_all() 清理所有已注册的服务进程。

使用场景
--------
- main() 函数捕获 KeyboardInterrupt 时
- main() 函数捕获其他异常时
- 程序退出前的清理操作

异常处理
----------
捕获所有异常并记录错误，确保清理过程不会中断程序退出。

注意事项
--------
- 通过 ServiceManager 单例模式访问进程注册表
- 清理失败不会抛出异常，仅记录错误日志

### `_build_arg_parser() -> argparse.ArgumentParser`

构造 ``ai-intervention-agent`` 的 CLI 解析器。

设计目标
----
符合 PyPI CLI 事实标准（pip / ruff / uv / black 等）：
``--version`` / ``--help`` 必须可用，否则 ``uvx ai-intervention-agent
--version`` 会卡进 MCP stdio loop 永远 hang，用户得 Ctrl+C 才能退。

向后兼容
----
无任何参数时（``argv == []``），parser 不报错，调用方继续走原
``mcp.run(transport="stdio")`` 路径——这是 MCP client (Cursor /
Claude Desktop / mcp-cli) 调起 server 的默认调用形态。

扩展点
----
后续若要加 ``--log-level`` / ``--config-file`` 等运行时 flag，在此添加
``parser.add_argument`` 即可；但请注意：相同配置项已经有 env vars
（``AI_INTERVENTION_AGENT_LOG_LEVEL`` / ``_CONFIG_FILE``）和
``config.toml`` 两条路径，加 CLI 会形成 3 套并存——增加用户认知
负担。除非有强需求，否则避免重复造轮子。

### `_is_sensitive_key(key: str) -> bool`

匹配规则：key 名 normalized 后包含任意 ``_SENSITIVE_KEY_SUBSTRINGS`` 子串。

Normalization
-------------
1. 转小写——``Bark_Device_Key`` → ``bark_device_key``；
2. 去掉 ``_`` 和 ``-``——``bark_device_key`` → ``barkdevicekey``，
   这样既兼容 snake_case (``device_key``)、kebab-case
   (``device-key``)、又兼容驼峰 (``BarkDeviceKey`` → ``barkdevicekey``）；
3. 与 substrings 一一比对（substrings 自己保留 ``_-`` 用于注释可读，
   匹配时同样 normalize 一次）。

用 substring + normalization 而不是正则：
- 实际配置项命名风格不统一（``bark_device_key`` vs ``deviceKey`` vs
  ``X-Auth-Token``），normalized substring 一次性覆盖三种风格；
- 维护成本低：将来新增敏感字段只需在 ``_SENSITIVE_KEY_SUBSTRINGS``
  列表加一个串即可。

### `_redact_sensitive(value: object) -> object`

递归扫一棵 config 子树，把敏感字段的值替换成 ``***REDACTED***``。

递归规则
--------
* ``dict`` → 对每个 ``(k, v)``：如果 ``k`` 匹配
  ``_is_sensitive_key``，直接把 v 替换；否则继续递归 v；
* ``list`` / ``tuple`` → 对每个元素递归（元素本身可能是 dict）；
* 其他原子类型 → 原样返回。

不会原地修改输入——返回新的 dict / list；调用方可以安全地共享原配置
（ConfigManager.get_all() 返回的已经是 deepcopy，但这里再加一层
immutability 防御纯属保险）。

### `_is_using_default_config(config_file_path: object) -> bool`

CR#16 F-3：判断 ``config_file_path`` 是否指向项目 bundled 默认配置。

用途
----
给 ``--print-config`` 输出的 ``using_defaults`` 字段提供布尔判断。
``True`` 表示 ConfigManager fallback 到了仓内 bundled ``config.toml``
（fresh install / 用户没创建自己的配置文件）；``False`` 表示用户
确实有一份独立的 config。

判定规则
--------
1. ``config_file_path is None`` / 非 str → 视作 default（保守）；
2. 解析为绝对路径后，前缀是 ``<package_root>/`` → 是 default；
3. 其它情况（绝对路径在 ``~/.config`` / ``~/Library/Application Support``
   / ``%APPDATA%`` 等用户目录下，或显式 ``AI_INTERVENTION_AGENT_CONFIG_FILE``）
   → 不是 default。

安全
----
只读 ``__file__`` 和路径前缀比较——不读文件内容、不调用 ConfigManager
其它 API，所以本函数自身从不抛异常。万一路径解析失败也走 fail-safe
分支返回 ``False``（保守：宁可显示 "用户配置"，避免错误地说用户在跑
默认值；用户看到自己 config.toml 文件路径会立即意识到这是错报）。

### `_print_effective_config() -> int`

实现 ``--print-config``：dump merged config 到 stdout 后退出。

输出内容
--------
一个 JSON object 含四个 top-level key：

* ``config_file_path``：当前 ConfigManager 加载的文件绝对路径
  （与 ``/api/system/health`` 的同名字段、``find_config_file()``
  返回值一致）；
* ``using_defaults``（CR#16 F-3）：bool，表示 ``config_file_path``
  指向的是项目 bundled 默认 config（``True``）还是用户自己创建的
  文件（``False``）。``True`` 时往往意味着 "我还没创建
  ``~/.config/ai-intervention-agent/config.toml``" —— 一眼看出
  "我在跑 built-in 默认值"，对 fresh install 调试非常有用。
* ``sections``（CR#16 F-1）：dict，**所有非敏感配置 section** 的
  原始值（``ConfigManager.get_all()`` 已过滤 ``network_security``）。
  包含 ``web_ui`` / ``mdns`` / ``feedback`` / ``notification`` 等，
  给用户排查 "为什么 mDNS 不工作" / "通知 backend 选了什么" 这类
  问题一个完整视图。``web_ui`` 子树是已 merge env override 的版本
  （host/port/language 反映进程实际绑定值）。
* ``env_overrides``：当前生效的 web_ui env vars 名单（与
  ``/api/system/health`` 的 ``web_ui_env_overrides`` 字段语义
  一致）。

R53-F 契约
----------
与 health endpoint 同样的安全契约——``network_security`` 整段被
``ConfigManager.get_all()`` 显式过滤，**不会**dump 出 IP 白名单
/ CIDR / token 类敏感信息。

返回码：0 = 成功打印，1 = 探测失败（仍输出一个 JSON object 带
``error`` 字段，让脚本能机器解析）。

### `main(argv: list[str] | None = None) -> None`

MCP 服务器主入口函数

功能
----
解析 CLI（``--version`` / ``--help``）后启动 FastMCP 服务器，使用 stdio
传输协议与 AI 助手通信。包含自动重试机制，提高服务稳定性。

参数
----
argv : list[str] | None
    CLI 参数列表（不含 prog name）。默认 ``None`` 时 argparse 自动从
    ``sys.argv[1:]`` 取，与 console_script 入口的零参数调用契约一致。
    测试可以传 ``["--version"]`` / ``["-V"]`` / ``["--help"]`` /
    ``[]`` 等显式 argv 走分支。

运行流程
--------
0. 解析 CLI 参数（``--version`` 会直接 ``sys.exit(0)``，不进入下面）
1. 降低 mcp 和 fastmcp 日志级别为 WARNING（避免污染 stdio）
2. 调用 mcp.run(transport="stdio") 启动 MCP 服务器
3. 服务器持续运行，监听 stdio 上的 MCP 协议消息
4. 捕获中断信号（Ctrl+C）或异常，执行清理
5. 如果发生异常，最多重试 3 次，每次间隔 1 秒

异常处理
----------
- KeyboardInterrupt: 捕获 Ctrl+C，清理服务后正常退出
- 其他异常: 记录错误，清理服务，尝试重启（最多 3 次）
- 重试失败: 达到最大重试次数后以状态码 1 退出

重试策略
----------
- 最大重试次数: 3 次
- 重试间隔: 1 秒
- 每次重试前清理所有服务进程
- 记录完整的错误堆栈和重试历史

日志配置
----------
- mcp 日志级别: WARNING
- fastmcp 日志级别: WARNING
- 避免 DEBUG/INFO 日志污染 stdio 通信通道

传输协议
----------
使用 stdio 传输，MCP 消息通过标准输入/输出进行交换：
- stdin: 接收来自 AI 助手的请求
- stdout: 发送 MCP 响应（必须保持纯净）
- stderr: 日志输出

使用场景
--------
- 直接运行: python server.py
- 作为 MCP 服务器被 AI 助手调用
- CLI 自省: ``ai-intervention-agent --version`` / ``--help``

注意事项
--------
- 必须确保 stdout 仅用于 MCP 协议通信
- 所有日志输出重定向到 stderr
- 服务进程由 ServiceManager 管理，退出时自动清理
- 重试机制可以自动恢复临时性错误
- ``argparse`` 的 ``--version`` / ``--help`` 用 ``sys.exit(0)``
  退出，**绝不**会进入 stdio loop——避免 ``uvx
  ai-intervention-agent --version`` hang 死的常见 PyPI CLI footgun。

向后兼容契约
------------
**``argv is None`` 时跳过 CLI 解析**，直接走 stdio loop。这是为了
保留 ``main()`` 零参数调用契约——历史上 ``test_server_functions``
/ ``test_server_main_retry_backoff`` / ``test_diagnostic_event_log_r40``
都用 ``main()`` 不传 argv 来直接测试 stdio loop 启动行为，
PyPA console_script wrapper 也是零参数调用 ``main()``。如果默认
fallback 到 ``sys.argv[1:]``，pytest 自己的 ``sys.argv`` 会被错当
成 server CLI flag，整套测试都会炸 ``argparse.SystemExit(2)``。

需要 CLI 解析时（如 ``ai-intervention-agent --version``），由
``_cli_main()`` console_script 入口或 ``__main__`` 块显式传
``sys.argv[1:]`` 调用。

### `_cli_main() -> None`

PyPA console_script 入口（``[project.scripts]`` 注册到此函数）。

setuptools / hatchling 生成的 console_script wrapper 等价于：

    from ai_intervention_agent.server import _cli_main
    sys.exit(_cli_main())

**不会**把 ``sys.argv`` 传给入口函数（这是 PyPA 标准行为，与
``argparse.ArgumentParser().parse_args()`` 默认从 sys.argv 读的
自动行为耦合）。本 wrapper 显式从 ``sys.argv[1:]`` 抽取 CLI argv
后调 ``main(argv)``，让 ``main()`` 自己的零参数调用契约
（= 直接走 stdio loop）不被破坏——见 ``main()`` docstring 里的
「向后兼容契约」段落。
