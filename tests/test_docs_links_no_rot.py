"""docs 内相对链接漂移护栏（R80 docs link-rot guard）。

R76 在重组项目布局时把 24 个 .py + 4 个资源目录全部迁入了
``src/ai_intervention_agent/``，触发了一波 README / docs 内
链接路径的同步更新。R76 之后又陆续做了 R77 / R78 / R79 几轮
test 与 feature 的迭代，每轮都可能把某个 ``[...](docs/foo.md)``
形式的 markdown 链接改坏（典型场景：把 ``docs/foo.md`` 重命名
为 ``docs/foo.zh-CN.md``，或者把 ``../api/server.py`` 重新生成
后路径偏移）。

本测试在 ``tests/`` 里加一道 regression 护栏：

1. 扫描仓库根 + ``docs/`` + ``.github/`` + ``packages/vscode/`` +
   ``scripts/`` 的所有 ``*.md``（不含 ``.venv`` / ``.pytest_cache``
   / ``node_modules`` 等隔离目录）。
2. 用 ``[label](target)`` 正则提取所有 link target。
3. 跳过：外部 URL（``http://``/``https://``/``mailto:``）、纯 fragment
   （``#anchor``）、``javascript:`` 协议、空目标。
4. 对剩余的本地相对路径，剥掉 ``?query`` 与 ``#fragment``，验证
   ``(md_file.parent / target).resolve()`` 命中文件系统里实际存在
   的文件 / 目录。

失败时给出**确切的 md 文件 + 行号 + 链接目标**，便于一次性修复。
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Markdown link 提取：``[label](target)`` —— 不含 ``![alt](src)`` image link。
# 用 negative-lookbehind ``(?<!!)`` 排除 ``!`` 前缀的图片语法。
_MD_LINK_RE = re.compile(r"(?<!!)\[(?P<label>[^\]]*)\]\((?P<target>[^)]+)\)")

# R177 / CR#11 F-1：strip 掉 inline code（单反引号 ``...``）防止形如
# ``[label](./xxx.zh-CN.md)`` 的示例占位符被误识别为真实 link。Markdown 渲染
# 时反引号内的内容是字面 code，不会被解析成 link；本测试 line-by-line 扫描
# 时缺乏这种上下文，需要主动剥掉。
#
# 模式：``[^`]*`` 匹配反引号之间的任意非反引号内容（典型场景：``[xxx](yyy)``
# 占位符整体被一对反引号包裹）。不处理 escape 后的反引号 ``\``\` —— 项目里
# 没有这种用法。
_INLINE_CODE_RE = re.compile(r"`[^`]*`")

# 不需要 fs 校验的 link target 前缀
_EXTERNAL_PREFIXES: tuple[str, ...] = (
    "http://",
    "https://",
    "mailto:",
    "javascript:",
    "tel:",
    "ftp://",
)

# 扫描根目录下哪些子目录的 md
_SCAN_DIRS: tuple[str, ...] = (
    ".",  # 仓库根：README.md / CHANGELOG.md / TODO.md
    "docs",
    ".github",
    "packages/vscode",
    "scripts",
)

# 跳过的目录（即便落在 _SCAN_DIRS 子树里也不扫）
_SKIP_DIRS: tuple[str, ...] = (
    "node_modules",
    ".venv",
    ".pytest_cache",
    "__pycache__",
    ".git",
    "dist",
    "build",
    "out",
    ".cache",
    ".vscode-test",  # VSCode test runtime download — 第三方 README，不归本仓库管
)

# Path 形态启发式：target 必须像「文件路径 / 目录」才校验。这样可以排除
# CHANGELOG / docs 中嵌入的正则字面量被 ``[label](pattern)`` 误识别的
# false positive（比如：```\(['"]([a-zA-Z][a-zA-Z0-9_.]+)['"]\s*[,)]```
# 在 markdown 渲染里是字面 regex，不是链接）。
#
# 校验条件：target 包含 ``/`` （明显是路径）OR 以下列扩展名结尾。
_PATH_LIKE_EXT_RE = re.compile(
    r"\.(?:md|html|json|yaml|yml|toml|txt|py|js|mjs|ts|tsx|css|svg|png|jpg|jpeg|"
    r"gif|webp|ico|webmanifest|wav|mp3|lottie|woff|woff2|ttf|zip|tar|gz)$",
    re.IGNORECASE,
)


def _looks_like_path(target: str) -> bool:
    """target 形态像路径才算需要 fs 校验的 link。"""
    cleaned = target.split("#", 1)[0].split("?", 1)[0].strip()
    if not cleaned:
        return False
    if "/" in cleaned:
        return True
    # 单一文件名形态（同目录）：要求扩展名落在白名单里
    return bool(_PATH_LIKE_EXT_RE.search(cleaned))


def _collect_md_files() -> list[Path]:
    """收集所有需要扫描的 ``*.md`` 文件。"""
    md_files: list[Path] = []
    for scan_dir in _SCAN_DIRS:
        scan_root = REPO_ROOT / scan_dir
        if not scan_root.exists():
            continue
        if scan_dir == ".":
            # 顶层只扫 1 层（不递归到 docs/api 等已经被显式扫的子树）
            md_files.extend(p for p in scan_root.glob("*.md") if p.is_file())
        else:
            for p in scan_root.rglob("*.md"):
                if not p.is_file():
                    continue
                if any(skip in p.parts for skip in _SKIP_DIRS):
                    continue
                md_files.append(p)
    # 去重 + 稳定排序
    return sorted(set(md_files))


def _extract_local_targets(md_file: Path) -> list[tuple[int, str]]:
    """提取 md 文件中所有需要 fs 校验的 ``(line_no, target)`` 对。

    跳过：
    1. 外部 URL（http://、mailto: 等前缀）
    2. 纯 fragment（``#section``）
    3. 不像路径的目标（regex 字面量、变量占位符等 false positive）
    4. **R177 / CR#11 F-1**：fenced code block（``` ``` ``` ```）与 inline
       code（``` `...` ```）内的 markdown-link-shape 字符串 —— 这些是文档
       的「示例占位符」，markdown 渲染时不会解析成真实 link；本测试也应该
       同步忽略。
    """
    targets: list[tuple[int, str]] = []
    text = md_file.read_text(encoding="utf-8")
    in_fence = False  # 状态机：当前是否在 fenced code block 内
    for line_no, raw_line in enumerate(text.splitlines(), start=1):
        # R177 状态机：fenced code block 用 ``` ``` 三连反引号定界。简化处
        # 理：以 ``` ``` 开头的行（前缀空白可选）整段开关 fence。markdown
        # 规范允许 fence 内嵌空格 + 语言标签（```python），都是合法 fence。
        stripped = raw_line.lstrip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        # 行内 inline code 剥掉（``...``）—— 这样 ``[label](./xxx.md)`` 这种
        # 占位符整体被反引号包裹时不会进 _MD_LINK_RE。
        line = _INLINE_CODE_RE.sub("", raw_line)
        for match in _MD_LINK_RE.finditer(line):
            target = match.group("target").strip()
            if not target:
                continue
            if target.startswith("#"):
                continue
            if target.lower().startswith(_EXTERNAL_PREFIXES):
                continue
            if not _looks_like_path(target):
                continue
            targets.append((line_no, target))
    return targets


def _resolve_target(md_file: Path, target: str) -> Path:
    """把 target 解析成绝对路径（去掉 ``?query`` 和 ``#fragment``）。"""
    # 切掉 fragment / query；fragment 可能含编码后的字符，本测试不验
    # anchor 内的 heading 是否真的存在（成本/收益不划算）。
    cleaned = target.split("#", 1)[0].split("?", 1)[0]
    if not cleaned:
        # 纯 fragment（``#section``）已经在调用方过滤
        return md_file
    if cleaned.startswith("/"):
        # 绝对路径：相对仓库根
        return (REPO_ROOT / cleaned.lstrip("/")).resolve()
    return (md_file.parent / cleaned).resolve()


class TestDocsLinksDoNotRot(unittest.TestCase):
    """所有 ``[...](path)`` 相对链接都必须命中存在的文件 / 目录。

    用一个 super-test 收集全部漂移点再一次性 fail，避免 fix 一处又出
    一处反复 CI red 浪费 reviewer 时间。失败信息按 ``md_file:line``
    分组。
    """

    def test_no_broken_relative_links_in_md(self) -> None:
        broken: list[str] = []
        md_files = _collect_md_files()
        self.assertGreater(
            len(md_files),
            5,
            "扫描到的 md 文件数过少，怀疑 _SCAN_DIRS / _SKIP_DIRS 被改坏",
        )
        for md_file in md_files:
            for line_no, target in _extract_local_targets(md_file):
                resolved = _resolve_target(md_file, target)
                if resolved.exists():
                    continue
                rel_md = md_file.relative_to(REPO_ROOT)
                broken.append(f"{rel_md}:{line_no} → {target}")
        if broken:
            joined = "\n  ".join(broken)
            self.fail(
                f"发现 {len(broken)} 条 broken markdown 链接：\n  {joined}\n\n"
                f"修复方法：核对每个 target 的实际路径；如果是已重命名 / "
                f"已删除文件，更新 md 引用或保留一个 stub 重定向。"
            )

    def test_inline_code_link_is_ignored(self) -> None:
        """R177 / CR#11 F-1：``[label](./xxx.md)`` 在 inline code 内不被检查。

        Markdown 渲染时反引号包裹的内容是字面 code，浏览器不会跳转。本测
        试也应该同步忽略 —— 否则 CHANGELOG / code-review doc 写 markdown 链
        接占位符示例时会被误报为 broken link。
        """
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            tmp_md = Path(tmp) / "test_inline_code.md"
            tmp_md.write_text(
                "Examples of fake links inside inline code:\n"
                "* `[demo](./nonexistent.md)` — should NOT be checked\n"
                "* `[xxx](./xxx.zh-CN.md)` — should NOT be checked either\n",
                encoding="utf-8",
            )
            targets = _extract_local_targets(tmp_md)
        self.assertEqual(
            targets,
            [],
            "inline code 内的 markdown 链接占位符不应进入校验队列",
        )

    def test_fenced_code_block_link_is_ignored(self) -> None:
        """R177 / CR#11 F-1：``[label](./xxx.md)`` 在 fenced code block 内不被检查。

        三连反引号开 / 关 fence；fence 内是字面 code，含 markdown link
        语法的字符串不会被渲染成 link，本测试也跳过。
        """
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            tmp_md = Path(tmp) / "test_fenced_code.md"
            tmp_md.write_text(
                "Real link: [README](./README.md)\n"
                "Fenced example:\n"
                "```\n"
                "[demo](./nonexistent.md)\n"
                "[other](./also-nonexistent.zh-CN.md)\n"
                "```\n"
                "More prose here.\n",
                encoding="utf-8",
            )
            targets = _extract_local_targets(tmp_md)
        # 只有 fence 外的 [README](./README.md) 应被提取
        self.assertEqual(
            [t for _, t in targets],
            ["./README.md"],
            "fenced code block 内的 markdown 链接占位符不应进入校验队列",
        )

    def test_real_link_outside_inline_code_is_still_checked(self) -> None:
        """R177 / CR#11 F-1：剥 inline code 不影响行内同段的真实链接。

        典型场景：一行里既有 ``[real](./foo.md)`` 真实 link，又有
        ``[fake](./xxx.md)`` 占位符 —— 真实 link 仍要被检查。
        """
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            tmp_md = Path(tmp) / "test_mixed.md"
            tmp_md.write_text(
                "Example: real link [README](./README.md) coexists with "
                "`[demo](./nonexistent.md)` placeholder on the same line.\n",
                encoding="utf-8",
            )
            targets = _extract_local_targets(tmp_md)
        self.assertEqual(
            [t for _, t in targets],
            ["./README.md"],
            "剥 inline code 后真实 link 仍应被提取",
        )

    def test_scan_covers_at_least_known_files(self) -> None:
        """白名单关键文档必须被扫到，防止 _SCAN_DIRS 配置漂移。"""
        md_files = _collect_md_files()
        rels = {p.relative_to(REPO_ROOT).as_posix() for p in md_files}
        must_cover = (
            "README.md",
            "README.zh-CN.md",
            "CHANGELOG.md",
            "docs/README.md",
            "docs/configuration.md",
            "docs/troubleshooting.md",
            "docs/api/index.md",
            "docs/api.zh-CN/index.md",
            "docs/workflow.md",
            # R176：``docs/noise-levels`` 按 README 模式补齐 EN / zh-CN —— 此前
            # 是孤儿中文文档（违反"默认英文版"约定）。两套都要存在，删任意一份
            # 都会让本测试红。
            "docs/noise-levels.md",
            "docs/noise-levels.zh-CN.md",
            # R175：``.github/`` 四组 governance docs 按 README 模式拆 EN /
            # zh-CN，两套必须始终在场 —— 否则 README / 文档里的 link 会变 404。
            ".github/SECURITY.md",
            ".github/SECURITY.zh-CN.md",
            ".github/CONTRIBUTING.md",
            ".github/CONTRIBUTING.zh-CN.md",
            ".github/CODE_OF_CONDUCT.md",
            ".github/CODE_OF_CONDUCT.zh-CN.md",
            ".github/SUPPORT.md",
            ".github/SUPPORT.zh-CN.md",
            ".github/PULL_REQUEST_TEMPLATE.md",
            ".github/PULL_REQUEST_TEMPLATE.zh-CN.md",
        )
        missing = [name for name in must_cover if name not in rels]
        self.assertEqual(
            missing,
            [],
            f"以下关键 md 文件未被扫到（需要更新 _SCAN_DIRS 或确认文件存在）: {missing}",
        )


if __name__ == "__main__":
    unittest.main()
