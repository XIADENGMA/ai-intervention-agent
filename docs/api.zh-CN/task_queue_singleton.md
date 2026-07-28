# task_queue_singleton

> 英文 signature-only 版本（仅函数 / 类签名速查）：[`docs/api/task_queue_singleton.md`](../api/task_queue_singleton.md)

TaskQueue 全局单例访问器（与 server.py 解耦的轻量入口）。

## 函数

### `get_task_queue() -> TaskQueue`

获取全局任务队列实例

### `_shutdown_global_task_queue() -> None`

进程退出时尽量停止 TaskQueue 后台线程（幂等）。
