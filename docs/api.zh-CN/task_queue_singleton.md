# task_queue_singleton

> 英文 signature-only 版本（仅函数 / 类签名速查）：[`docs/api/task_queue_singleton.md`](../api/task_queue_singleton.md)

TaskQueue 全局单例访问器（与 server.py 解耦的轻量入口）。

设计动机（R20.8 性能优化）：
============================

`get_task_queue()` 仅由 Web UI 子进程使用——MCP 主进程从不调用它。
但历史上该函数定义在 ``server.py`` 中，于是 ``web_ui.py`` 通过
``from server import get_task_queue`` 触发整条 ``fastmcp`` / ``mcp`` /
``loguru`` 依赖链加载，给 Web UI 子进程平添约 310 ms 启动延迟，
而这 310 ms 全部白费——子进程根本不需要任何 MCP server 能力。

把单例逻辑抽到本模块后：

* Web UI 子进程仅加载 ``task_queue`` + ``threading`` + ``pathlib``，
  ``import web_ui`` 时间从 ~470 ms 降至 ~155 ms；
* ``server.py`` 通过 re-export 保留公开 API ``server.get_task_queue``
  与 ``server._shutdown_global_task_queue``，外部调用者无感知；
* MCP 主进程行为不变——若不调用 ``get_task_queue()``，绝不会创建
  ``TaskQueue`` 实例，也不会启动后台清理线程。

线程安全：
========

采用经典「双重检查锁定（Double-Checked Locking）」模式，确保即使
多个线程并发调用 ``get_task_queue()``，也只创建一个 ``TaskQueue``
实例。Python 的 GIL 保证 ``is None`` 判断与赋值的原子性，``Lock``
则消除两个线程同时通过外层 ``is None`` 检查后重复创建的窗口。

进程退出清理：
============

``_shutdown_global_task_queue`` 通过 ``atexit.register`` 注册，
进程退出时尽力停止后台清理线程；任何异常都被吞掉——退出阶段不
适合再抛错。幂等：未创建 TaskQueue 时为 no-op；多次调用安全。

## 函数

### `get_task_queue() -> TaskQueue`

获取全局任务队列实例

返回:
    TaskQueue: 全局任务队列实例

### `_shutdown_global_task_queue() -> None`

进程退出时尽量停止 TaskQueue 后台线程（幂等）。
