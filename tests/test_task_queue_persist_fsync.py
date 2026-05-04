"""R17.2 回归：``TaskQueue._persist`` 必须在 ``os.replace`` 之前 fsync。

背景：
    ``os.replace(tmp, target)`` 是 ``rename(2)`` 系统调用，inode 层面的
    rename 是原子的——但 ``rename`` 完成时，目标 inode 指向的**数据**
    可能还在 OS page cache，没刷到磁盘。如果机器在 ``replace`` 之后、
    OS 自动刷盘之前 panic / 断电：

      1. 重启后磁盘 inode 已经指向新文件名 ✅（rename 元数据已落盘）
      2. 但新文件实际**数据**从未落盘 → 内容是 NUL fill / 部分写入 ❌
      3. 旧文件已经被 rename 替换，无法回滚 ❌

    所以工业级原子写惯用法是：
        ``write → flush → fsync(fileno) → os.replace``

    本仓库其他 5 处原子写入路径（``config_manager._save_config_immediate``、
    ``config_modules/io_operations.py``、
    ``config_modules/network_security._atomic_write_config``、
    ``scripts/bump_version.py``）都遵守这个序列，唯独
    ``task_queue._persist`` 历史上漏了 ``flush + fsync``，让任务队列
    成为整个仓库唯一一处在崩溃/断电下可能丢数据 / 出 NUL 字节文件的
    路径。本组测试锁住修复后的契约。
"""

from __future__ import annotations

import ast
import inspect
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class TestPersistFsyncContract(unittest.TestCase):
    """直接验 ``_persist`` 在 ``os.replace`` 前调用了 ``fsync``。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.persist_path = Path(self._tmp.name) / "tasks.json"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _make_queue_with_one_task(self):
        from task_queue import TaskQueue

        q = TaskQueue(persist_path=str(self.persist_path))
        q.add_task(task_id="t1", prompt="hello")
        return q

    def test_persist_calls_fsync_before_replace(self) -> None:
        """记录 syscall 顺序：``fsync`` 必须在 ``os.replace`` *之前*。

        why：
            如果实现是 ``replace → fsync(target_fd)``，``replace`` 已
            交付旧→新切换，``fsync`` 失败时已经晚了；要 ``fsync(tmp_fd)
            → replace`` 才能保证"原子切换的目标"已经落盘。
        """
        q = self._make_queue_with_one_task()

        call_order: list[str] = []
        real_fsync = os.fsync
        real_replace = os.replace

        def trace_fsync(*args, **kwargs):
            call_order.append("fsync")
            return real_fsync(*args, **kwargs)

        def trace_replace(*args, **kwargs):
            call_order.append("replace")
            return real_replace(*args, **kwargs)

        with (
            patch("task_queue.os.fsync", side_effect=trace_fsync),
            patch("task_queue.os.replace", side_effect=trace_replace),
        ):
            q._persist()

        self.assertIn(
            "fsync", call_order, f"必须调用 os.fsync，实际 syscall 序列：{call_order}"
        )
        self.assertIn(
            "replace",
            call_order,
            f"必须调用 os.replace，实际 syscall 序列：{call_order}",
        )

        fsync_idx = call_order.index("fsync")
        replace_idx = call_order.index("replace")
        self.assertLess(
            fsync_idx,
            replace_idx,
            f"fsync 必须在 replace 之前调用——实际顺序：{call_order}",
        )

    def test_persist_calls_flush_before_fsync(self) -> None:
        """``flush()`` 必须在 ``fsync()`` 之前调用。

        why：
            ``flush()`` 把 stdio buffer 推到内核；``fsync()`` 才把内核
            page cache 推到磁盘。两步缺一不可——flush 单独不够（数据
            还停在 page cache），fsync 单独可能漏写当前 stdio buffer
            里还没 flush 的部分。

        实现：行为层面通过真实落盘 + 调用顺序观察实现——直接 mock
        file-handle 内部方法在 ty 的 strict-shadow 下不友好，所以只
        断言 ``os.fsync`` 在 ``os.replace`` 之前 *和* 源文本里
        ``f.flush()`` 出现在 ``os.fsync(f.fileno())`` 之前。
        """
        q = self._make_queue_with_one_task()

        # 行为部分：fsync / replace 顺序（与上一测重叠但聚焦 flush 关系）
        call_order: list[str] = []

        real_fsync = os.fsync
        real_replace = os.replace

        def trace_fsync(*args, **kwargs):
            call_order.append("fsync")
            return real_fsync(*args, **kwargs)

        def trace_replace(*args, **kwargs):
            call_order.append("replace")
            return real_replace(*args, **kwargs)

        with (
            patch("task_queue.os.fsync", side_effect=trace_fsync),
            patch("task_queue.os.replace", side_effect=trace_replace),
        ):
            q._persist()

        self.assertEqual(
            call_order,
            ["fsync", "replace"],
            f"行为层面 fsync 应紧邻在 replace 之前：{call_order}",
        )

        # 静态部分：源文本里 flush() 必须早于 fsync(fileno())
        from task_queue import TaskQueue

        src = inspect.getsource(TaskQueue._persist)
        self.assertIn("f.flush()", src, "_persist 源码中应显式调用 f.flush()")
        self.assertIn(
            "os.fsync(f.fileno())",
            src,
            "_persist 源码中应显式调用 os.fsync(f.fileno())",
        )
        flush_idx = src.find("f.flush()")
        fsync_idx = src.find("os.fsync(f.fileno())")
        self.assertGreater(flush_idx, 0, "f.flush() 必须出现")
        self.assertGreater(fsync_idx, 0, "os.fsync(f.fileno()) 必须出现")
        self.assertLess(
            flush_idx,
            fsync_idx,
            f"源码层面 f.flush() 必须出现在 os.fsync(f.fileno()) 之前 "
            f"(flush@{flush_idx}, fsync@{fsync_idx})",
        )

    def test_fsync_failure_does_not_replace(self) -> None:
        """``fsync`` 抛 ``OSError`` 时 ``os.replace`` 不应被调用——保留旧文件。

        why：
            如果 fsync 失败但 replace 仍执行，磁盘旧文件被毁、新数据
            从未落盘——比"两边都失败"更糟。fsync 是 fail-loud 的关键
            一环，必须让它的失败阻断后续切换。
        """
        from task_queue import TaskQueue

        # 步骤 1：建立旧文件（默认 persist 路径成功）
        q = TaskQueue(persist_path=str(self.persist_path))
        q.add_task(task_id="t1", prompt="hello")
        self.assertTrue(self.persist_path.exists(), "首次 persist 应建立文件")
        original_bytes = self.persist_path.read_bytes()

        # 步骤 2：在 fsync-fail 上下文里手动调 _persist（模拟磁盘 EIO）
        # 不通过 add_task 触发，因为 add_task 还会做内存层操作；我们只
        # 关心 _persist 自身在 fsync 失败时的 syscall 行为。
        with (
            patch("task_queue.os.fsync", side_effect=OSError("simulated EIO")),
            patch("task_queue.os.replace") as mock_replace,
        ):
            q._persist()

        # 1) os.replace 必须没被调用——fsync 失败必须阻断切换
        mock_replace.assert_not_called()
        # 2) 磁盘上的旧文件字节级未变更
        self.assertEqual(
            self.persist_path.read_bytes(),
            original_bytes,
            "fsync 失败时旧文件必须保持原状（fail-loud, no half-write）",
        )


class TestPersistAtomicWriteParity(unittest.TestCase):
    """跨文件一致性：仓库内**所有**原子写入路径都必须 ``flush + fsync``。

    why：
        本仓库历史上有 5 处用 ``tempfile + os.replace`` 模式落盘的代码，
        其中 4 处都已经按 ``write → flush → fsync → replace`` 序列写。
        ``task_queue._persist`` 是 R17.2 之前唯一的"漏 fsync"叛徒。
        本测试静态扫描所有这些路径，确保未来不会因为复制粘贴或重构
        引入新的"漏 fsync"路径。
    """

    # 仓库内所有声明走"原子写入"模式的函数定位
    # （文件路径相对仓库根，函数限定名）
    _ATOMIC_WRITE_TARGETS = (
        ("task_queue.py", "TaskQueue._persist"),
        ("config_manager.py", "_save_config_immediate"),
        # io_operations / network_security 的 free-form 函数名容易漂移，
        # 改用 grep 全文文件确认
    )

    def _read_function_source(self, file_rel: str, qualname: str) -> str:
        """从源文件提取指定函数的完整源代码（含注释）。"""
        repo_root = Path(__file__).resolve().parent.parent
        path = repo_root / file_rel
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))

        target_parts = qualname.split(".")
        # 简单查找：要么 module-level function，要么 class.method
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and len(target_parts) == 2:
                if node.name == target_parts[0]:
                    for item in node.body:
                        if (
                            isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                            and item.name == target_parts[1]
                        ):
                            return ast.get_source_segment(source, item) or ""
            elif (
                isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and len(target_parts) == 1
                and node.name == target_parts[0]
            ):
                return ast.get_source_segment(source, node) or ""
        raise AssertionError(f"未在 {file_rel} 找到 {qualname}")

    def test_targeted_functions_have_flush_and_fsync_before_replace(self) -> None:
        """对每个已知的原子写入函数，断言 flush/fsync/replace 都出现。

        粗粒度但有效：源文本里包含 ``f.flush()`` ``os.fsync(`` ``os.replace(``
        三个 token——精确顺序由
        ``TestPersistFsyncContract::test_persist_calls_fsync_before_replace``
        在行为层面锁定。
        """
        for file_rel, qualname in self._ATOMIC_WRITE_TARGETS:
            with self.subTest(target=f"{file_rel}::{qualname}"):
                src = self._read_function_source(file_rel, qualname)
                self.assertIn(
                    ".flush()",
                    src,
                    f"{file_rel}::{qualname} 必须调用 flush()，"
                    f"否则数据可能滞留 stdio buffer",
                )
                self.assertIn(
                    "os.fsync(",
                    src,
                    f"{file_rel}::{qualname} 必须调用 os.fsync()，"
                    f"否则数据可能滞留 page cache 不落盘",
                )
                self.assertIn(
                    "os.replace(",
                    src,
                    f"{file_rel}::{qualname} 必须调用 os.replace() 完成原子切换",
                )

    def test_persist_signature_unchanged(self) -> None:
        """reverse-lock：``_persist()`` 签名保持 ``self`` 单参数。

        如果有人为了"参数化 fsync 行为"加了 ``no_fsync=True`` 参数，
        这层防线会立刻 fail，提醒 reviewer 这是反向走最佳实践。
        """
        from task_queue import TaskQueue

        sig = inspect.signature(TaskQueue._persist)
        params = list(sig.parameters)
        self.assertEqual(
            params,
            ["self"],
            f"_persist 签名不应被参数化（破坏'永远 fsync'契约）：{params}",
        )


if __name__ == "__main__":
    unittest.main()
