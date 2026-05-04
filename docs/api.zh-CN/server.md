# server

> 英文 signature-only 版本（仅函数 / 类签名速查）：[`docs/api/server.md`](../api/server.md)

MCP 服务器核心 - interactive_feedback 工具、多任务队列、通知集成。

## 函数

### `_resolve_server_version() -> str`

读取已安装包版本号，失败时返回开发占位符。

通过 MCP initialize 协议暴露给 client，方便 client 做兼容判断 / 调试日志。

### `_build_server_icons() -> list[Icon]`

启动时一次性把本地 icons 转成 data URI，让 server icons 完全 self-contained。

设计取舍：
- 使用 base64 data URI 而不是 GitHub raw URL，避免对 main 分支 push 状态的依赖
  （已发布版本即使 main 上图标资源被删，client 仍能渲染图标）
- 多尺寸覆盖：32/192/512 + SVG，让 client UI 按显示密度自选
- 总开销 ~17KB（base64 化），仅在 initialize 一次性下发，可忽略
- 任何 icon 文件缺失时跳过，不影响 server 启动

### `get_task_queue() -> TaskQueue`

获取全局任务队列实例

返回:
    TaskQueue: 全局任务队列实例

### `_shutdown_global_task_queue() -> None`

进程退出时尽量停止 TaskQueue 后台线程（幂等）。

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

### `main() -> None`

MCP 服务器主入口函数

功能
----
配置日志级别并启动 FastMCP 服务器，使用 stdio 传输协议与 AI 助手通信。
包含自动重试机制，提高服务稳定性。

运行流程
--------
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

注意事项
--------
- 必须确保 stdout 仅用于 MCP 协议通信
- 所有日志输出重定向到 stderr
- 服务进程由 ServiceManager 管理，退出时自动清理
- 重试机制可以自动恢复临时性错误
