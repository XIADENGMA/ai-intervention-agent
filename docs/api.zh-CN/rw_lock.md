# rw_lock

> 英文 signature-only 版本（仅函数 / 类签名速查）：[`docs/api/rw_lock.md`](../api/rw_lock.md)

Small read/write lock primitive shared by config and task queues.

## 类

### `class ReadWriteLock`

多读者并发、写者独占，基于 Condition + RLock 实现。

#### 方法

##### `__init__(self) -> None`

初始化读写锁。

##### `read_lock(self) -> Generator[None, None, None]`

获取读锁（多读者并发，仅在写者持有锁时阻塞）。

##### `write_lock(self) -> Generator[None, None, None]`

获取写锁（独占访问，等待所有读者退出）。
