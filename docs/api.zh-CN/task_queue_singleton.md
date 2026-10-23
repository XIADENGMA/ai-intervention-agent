# task_queue_singleton

> 英文 signature-only 版本（仅函数 / 类签名速查）：[`docs/api/task_queue_singleton.md`](../api/task_queue_singleton.md)

TaskQueue 全局单例访问器（与 server.py 解耦的轻量入口）。

## 函数

### `_default_persist_path() -> Path`

### `_snapshot_path() -> Path`

快照文件路径；绑定了端口的 Web UI 用 ``tasks-<port>.json``（R836）。

### `bind_task_queue_to_port(port: int) -> bool`

让任务快照以 Web UI 监听的端口命名（R836），必须在队列创建之前调用。

同一个安装目录下可以同时跑多个 Web UI（不同配置、不同端口）；它们以前共用
``<package>/data/tasks.json``：后起的那个会把先起的那个还在等回复的任务恢复成自己的，
之后各自覆盖对方的写入。按端口分文件后，同一个端口重启（R825）仍然找回自己的任务，
别的端口看不到。

返回 ``True`` 表示快照已经（或此前已经）绑定到 ``port``；端口不可用（不是 1..65535
的整数）或队列已经按别的名字建好了则返回 ``False``，快照名字保持不变。

### `get_task_queue() -> TaskQueue`

获取全局任务队列实例

### `_shutdown_global_task_queue() -> None`

进程退出时尽量停止 TaskQueue 后台线程（幂等）。
